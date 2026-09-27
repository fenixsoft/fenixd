"""locks.py — G3 锁治理/进程判活（refactor-giant-classes D1/D5）。

原为 WorktreeManager 的 10 个方法（`core/worktree_manager/_legacy.py`），
原样搬移为 mixin（方法体零改动）。跨组协作仍经宿主实例 `self.<method>`。

D3 patch 缝隙：本组使用 subprocess/time 等模块名，经包命名空间（__init__.py
re-export）或模块顶部导入均可——mock.patch("core.worktree_manager.subprocess.run")
修改的是 subprocess 模块对象本身，全进程共享，patch 依旧生效。
"""

from __future__ import annotations

import glob
import os
import re
import signal
import subprocess
import time

from pathlib import Path

from core.agent_runner.run_files import run_spec_part  # noqa: E402

from core.worktree_manager import (  # noqa: E402
    PROCESS_SCAN_CACHE_SECONDS,
    STALE_LOCK_IDLE_SECONDS,
    _is_claude_process,
)


class G3LockMixin:
    """G3 锁治理/进程判活——纯工具层，低耦合（design D1 表 A G3）。"""

    @staticmethod
    def _lock_spec_name(lock_key: str) -> str:
        """锁 key（``<spec>:<agent_type>``）→ spec 名。"""
        return lock_key.split(":")[0]

    def _register_spec_locks(self, spec_name: str) -> None:
        """按 spec 名重建两把锁（impl + verify），与 create() 的 key 形态一致。

        孤儿进程可能来自任一 agent 类型，进程表只能证明「该 spec 仍有活跃
        worktree」而无法可靠区分前缀，因此两把一起登记，宁可多拦不漏放。

        add 与 _lock_since 写入全程持 _spec_lock_th（code-review item
        776cffc0a278），与 create / release_spec_lock 的加锁纪律对齐。
        """
        with self._spec_lock_th:
            self._spec_locks.add(f"{spec_name}:implementer")
            self._lock_since[f"{spec_name}:implementer"] = time.time()
            self._spec_locks.add(f"{spec_name}:verifier")
            self._lock_since[f"{spec_name}:verifier"] = time.time()

    def _release_spec_locks(self, spec_name: str, reason: str, not_after: float | None = None) -> list:
        """释放该 spec 的全部在册锁，返回被释放的 key（已不在册则返回空）。

        to_remove 计算与摘除全程持 _spec_lock_th（code-review item
        776cffc0a278）：无锁迭代 _spec_locks 时并发 create/cleanup 增删
        会抛 "Set changed size during iteration"，且摘除须与 _lock_since
        清理原子（纪律同 lifecycle.py:593 段）。调用方（has_active_worktree
        / refresh_locks）均未持该非重入锁，锁内取锁无死锁风险。

        not_after：入口时刻守卫（code-review item cec36ef4e1fb，与 cleanup
        finally 的 cleanup_entry_ts 同款）——仅摘除 _lock_since 不晚于该时刻
        的在册锁。判定链（进程扫描 / 流 mtime）在持锁之前完成，期间并发
        create() / _register_spec_locks 重新登记的同键新锁 _lock_since 晚于
        入口时刻，跳过不误删，防止新 run 在 create 到子进程可被进程表扫到
        的构建窗口内失去锁保护（重开双派发窗口）；None 表示不设限（行为同
        旧版）。
        """
        with self._spec_lock_th:
            to_remove = [
                k
                for k in self._spec_locks
                if self._lock_spec_name(k) == spec_name
                and (not_after is None or self._lock_since.get(k, 0.0) <= not_after)
            ]
            for k in to_remove:
                self._spec_locks.discard(k)
                self._lock_since.pop(k, None)
            return to_remove

    def _lock_young(self, spec_name: str) -> bool:
        """该 spec 任一在册锁的锁龄 < STALE_LOCK_IDLE_SECONDS（create 构建窗口豁免）。

        锁龄缺失（历史锁未登记时刻）按不年轻处理——豁免只对确定年轻的锁生效，
        失败方向保守（宁可走既有陈锁回收，不额外放行）。

        迭代全程持 _spec_lock_th（code-review item 776cffc0a278，纪律同
        上方 _release_spec_locks）；调用方（has_active_worktree /
        refresh_locks）均未持锁，无嵌套取锁。
        """
        now = time.time()
        with self._spec_lock_th:
            for k in self._spec_locks:
                if self._lock_spec_name(k) != spec_name:
                    continue
                since = self._lock_since.get(k)
                if since is not None and (now - since) < STALE_LOCK_IDLE_SECONDS:
                    return True
            return False

    def _spec_process_alive(self, spec_name: str) -> bool:
        """进程表中是否存在指向该 spec worktree 的进程（带短缓存）。

        进程消失/出现以缓存窗口（PROCESS_SCAN_CACHE_SECONDS）为粒度生效，
        避免派发热路径上的 pgrep 风暴。
        """
        now = time.monotonic()
        cached = self._proc_scan_cache.get(spec_name)
        if cached is not None and cached[0] > now:
            return cached[1]
        try:
            alive = bool(self._process_scanner(spec_name))
        except Exception as e:  # 扫描异常视为不可用：保守按无进程处理并记日志
            self.logger.warning(
                "worktree_manager",
                f"Process scan failed for '{spec_name}' (treated as absent): {e}",
            )
            alive = False
        self._proc_scan_cache[spec_name] = (now + PROCESS_SCAN_CACHE_SECONDS, alive)
        return alive

    def _pgrep_spec_process(self, spec_name: str) -> bool:
        """pgrep 匹配 cmdline 含 ``worktrees/{impl,verify}-<spec>-`` 的 agent 进程。

        匹配串锚定 worktree 目录字面量（<prefix>-<spec>-<ts>），不匹配裸 spec 名，
        防止把无关进程当成持锁者；命中后还须经 ``_is_claude_process`` 确认程序为
        claude——测试子进程（dev-server 等）的 cmdline 同样含路径，agent 退出后
        成为永生孤儿，按路径匹配会把锁永久骗走。命中后再经
        ``_pid_in_project_worktrees`` 核对归属本项目（``worktrees/`` 字面匹配是
        全机性的，同机多项目同名 spec 会互相骗锁）。pgrep 不可用/超时时返回
        False（调用方以 run 流新鲜度做二次确认）。

        尾部锚定（code-review ffad20907ac6）：pattern 在 ``-{spec}-`` 之后
        要求时间戳段（``[[:digit:]]+``，create() 的 ts 恒为 int(time.time())
        纯数字）并以路径续接/空白/引号/行尾收尾（与 _worktree_has_live_process
        的锚定纪律一致）。裸 ``-{spec}-`` 尾随连字符在 spec 名互为前缀时过配
        ——fix-x 的 pattern 会命中兄弟 spec fix-x-y 的
        ``worktrees/impl-fix-x-y-<ts>``，其活进程持续把 fix-x 判存活、压制
        孤儿锁清理/重派。锚定后该形态后续字符非数字不再命中，语义等价于
        liveness._pgrep_live_attempt 命中后按 run_spec_part 全等归属的目录名
        解析（``{prefix}-{spec}-<纯数字>`` 同一尾部形状）；收紧只少误报，
        真实 agent cmdline 引用的目录名恒接时间戳，不引入漏报。
        """
        for prefix in ("impl", "verify"):
            pattern = (
                f"worktrees/{prefix}-{re.escape(spec_name)}"
                f"-[[:digit:]]+([/[:space:]\"']|$)"
            )
            try:
                res = subprocess.run(
                    ["pgrep", "-f", pattern],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except (subprocess.SubprocessError, OSError):
                return False
            if res.returncode == 0 and res.stdout.strip():
                if any(
                    _is_claude_process(p) and self._pid_in_project_worktrees(p)
                    for p in res.stdout.split()
                ):
                    return True
        return False

    def _pid_in_project_worktrees(self, pid_str: str) -> bool:
        """核对命中进程归属本项目 worktrees（跨项目 slug 撞名防误判）。

        双重归属信号，任一命中即认：cmdline 含本项目 worktrees 基目录前缀
        （按目录边界匹配，code-review c2b43a144ff0：裸子串会把同前缀更长
        目录名如 worktrees-backup/ 的进程误判归属本项目），或 cwd 经
        realpath 归一后位于基目录之下（argv 缺路径的进程形态）。
        realpath 归一消解符号链接/挂载拼写差异，避免把自家 agent 误判为
        他家进程（自误杀 → 活锁被放行 → 双派发）。两信号皆不可得（/proc
        不可读等）按不归属处理，失败方向与既有扫描异常一致（保守无进程，
        调用方以 run 流新鲜度做二次确认）。
        """
        base_text = str(self.base_dir)
        base_real = os.path.realpath(base_text)
        try:
            with open(f"/proc/{pid_str}/cmdline", "rb") as f:
                argv_text = f.read().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            argv_text = ""
        # argv 命中同样按目录边界匹配（code-review c2b43a144ff0）：口径与
        # 下方 cwd 分支的 startswith(base_real + os.sep) 对齐，同前缀更长
        # 目录名（worktrees-backup/ 等）不再被误判归属本项目
        if base_text + os.sep in argv_text or base_real + os.sep in argv_text:
            return True
        try:
            cwd_real = os.path.realpath(os.readlink(f"/proc/{pid_str}/cwd"))
        except OSError:
            return False
        return cwd_real == base_real or cwd_real.startswith(base_real + os.sep)

    def _latest_stream_mtime(self, spec_name: str) -> float | None:
        """该 spec 全部 run 流文件（.fenix/runs/{impl,verify}-<spec>-*.jsonl）的最新 mtime。

        无任何流文件返回 None。
        """
        runs_dir = self.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return None
        newest: float | None = None
        try:
            for prefix in ("impl", "verify"):
                for p in runs_dir.glob(f"{prefix}-{glob.escape(spec_name)}-*.jsonl"):
                    # 精确归属守卫（范式见 recovery.py）：spec 名互为前缀时
                    # glob 命中不得直接认定——fix-x 不得被 fix-x-y 的流判为残留
                    if run_spec_part(p.stem) != spec_name:
                        continue
                    try:
                        m = p.stat().st_mtime
                    except OSError:
                        continue
                    if newest is None or m > newest:
                        newest = m
        except OSError:
            return None
        return newest

    def _worktree_has_live_process(self, wt_name: str) -> bool:
        """进程表中是否存在引用该 worktree 目录的 agent 进程（启动清理用）。

        与 _pgrep_spec_process 不同：这里按完整 worktree 目录名匹配，不经过
        缓存（启动时一次性调用，结果必须实时）；命中后同样以 claude 进程
        为锚——仅剩 dev-server 孤儿的 worktree 应被判定为无主并进入清理。
        目录名匹配同为全机性字面匹配（同名 worktree 可属不同项目根），命中
        后经 ``_pid_in_project_worktrees`` 核对归属本项目再判存活。pattern
        以路径续接/空白/引号/行尾锚定尾部（与 _pgrep_spec_process 的锚定
        纪律一致）：防止 wt_name 是另一 worktree 目录名严格前缀时 pgrep
        子串过配（同基目录下归属核对无法二次区分）。
        """
        pattern = f"worktrees/{re.escape(wt_name)}([/[:space:]\"']|$)"
        try:
            res = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.SubprocessError, OSError):
            return False
        return res.returncode == 0 and any(
            _is_claude_process(p) and self._pid_in_project_worktrees(p)
            for p in res.stdout.split()
        )

    def _kill_worktree_strays(self, wt_name: str) -> list:
        """杀掉 cmdline 或 cwd 引用该 worktree 的非 agent 残留进程，返回被杀 PID。

        agent 收工后其测试子进程（v2 dev-server 等）可能残留为 PPID=1 孤儿：
        cmdline 仍含 worktree 路径且永不退出，既让 worktree 目录删不干净，
        也曾借存活检测把派发锁永久骗走。claude agent 进程不在清扫范围
        （防误杀在跑的 attempt）。

        verify-process-lifecycle（D8 能力升级）：
        - cmdline 匹配外增加 ``/proc/<pid>/cwd`` readlink 归属匹配——覆盖 argv
          不含 worktree 路径的进程（如 agent 经 Bash 起的 ``npm run dev``，
          argv 是 shell 而 cwd 在 worktree 内）；
        - SIGTERM 后短等待（宽限期），无响应进程补 SIGKILL 兜底，不残留。

        cmdline 命中的跨项目归属核对（code-review 40cfa57f5f02）：
        ``worktrees/<wt_name>`` 与 _pgrep_spec_process /
        _worktree_has_live_process 的匹配串同属全机性字面匹配——同机他项目
        可存在同名 worktree（跨项目 slug 撞名，见 _pid_in_project_worktrees），
        其下 npm/pytest 等进程的 argv 以绝对路径引用自家 worktree 时同样命中
        token，而 cwd 又不在本项目 worktree 内，若不做归属核对会被本清扫
        SIGTERM/SIGKILL 误杀、拖垮对方项目的活跃 run。因此 cmdline 命中须
        核对 argv 中被引用的 worktree 目录绝对路径（绝对前缀 + token 拼合，
        单看前缀无效：前缀按构造是基目录的父目录）：经 realpath 归一后等于
        本项目 token_real 才认，解析到他处即否决；argv 只含裸相对
        token（无绝对路径证据可判异）时维持命中即入候选的既有语义。cwd 分支
        以 token_real 锚定本项目，本就精确，保持直入候选。
        """
        me = os.getpid()
        token = f"worktrees/{wt_name}"
        # token 的 realpath 归一形态（与 _pid_in_project_worktrees 的
        # base_real 同范式），供 cwd 归一后按目录边界精确归属
        token_real = os.path.realpath(os.path.join(str(self.base_dir), wt_name))
        # argv 中「绝对路径 + token」命中提取式：捕获 worktrees/ 之前的绝对
        # 前缀，尾部锚定纪律与 cmdline_hit 一致（路径续接/空白/引号/行尾）
        foreign_pattern = re.compile(
            r"(/[^\s\"']*)" + re.escape(token) + r"(?:[/\s\"']|$)"
        )
        candidates: list = []
        try:
            for pid_str in os.listdir("/proc"):
                if not pid_str.isdigit():
                    continue
                pid = int(pid_str)
                if pid == me or _is_claude_process(pid_str):
                    continue
                proc_dir = Path("/proc") / pid_str
                # cmdline 匹配：尾部以路径续接/空白/引号/行尾锚定（与
                # _worktree_has_live_process 的锚定纪律一致），防止
                # wt_name 是另一 worktree 目录名严格前缀时子串过配、
                # 误杀兄弟 worktree 的残留进程
                try:
                    argv = (proc_dir / "cmdline").read_bytes().split(b"\0")
                    argv_text = " ".join(a.decode("utf-8", "replace") for a in argv if a)
                except OSError:
                    argv_text = ""
                cmdline_hit = re.search(
                    re.escape(token) + r"(?:[/\s\"']|$)", argv_text
                )
                # cwd readlink 归属匹配（覆盖 argv 无路径的 Bash 包装进程）；
                # 与 _pid_in_project_worktrees 一致先 realpath 归一，消解
                # 符号链接/挂载拼写差异，避免同一物理 cwd 归属核对能命中、
                # 清扫却漏杀
                try:
                    cwd_real = os.path.realpath(os.readlink(f"/proc/{pid_str}/cwd"))
                except OSError:
                    cwd_real = ""
                # cmdline 命中的跨项目归属核对（code-review 40cfa57f5f02）：
                # token 是全机性字面匹配，他项目同名 worktree 下进程的 argv
                # 以绝对路径引用自家 worktree 时同样命中——拼合「绝对前缀 +
                # token」得到被引用的 worktree 目录绝对路径（仅比前缀不行：
                # 前缀按构造是基目录的父目录，realpath 后永不等价于基目录），
                # realpath 归一后不等于本项目 token_real 即否决，不入候选
                # （失败方向保守：漏杀的残留可由下次清扫重试，误杀他项目
                # 活跃进程不可逆）。argv 无绝对路径证据（裸相对 token，如
                # 伪装 argv0 的测试进程形态）时无从判异，维持命中即入候选
                # 的既有语义；cwd 分支以 token_real 精确锚定，保持直入候选。
                foreign_hit = False
                if cmdline_hit:
                    for m in foreign_pattern.finditer(argv_text):
                        ref_real = os.path.realpath(m.group(1) + token)
                        if ref_real != token_real:
                            foreign_hit = True
                            break
                if (
                    (cmdline_hit and not foreign_hit)
                    or cwd_real == token_real
                    or cwd_real.startswith(token_real + os.sep)
                ):
                    candidates.append(pid)
        except OSError:
            return []
        killed = []
        for pid in candidates:
            try:
                os.kill(pid, signal.SIGTERM)
                killed.append(pid)
            except OSError:
                continue
        if killed:
            # SIGTERM 宽限期（~2s）：仍存活者 SIGKILL 兜底（D8）
            deadline = time.time() + 2.0
            while time.time() < deadline:
                alive = [p for p in killed if self._pid_alive(p)]
                if not alive:
                    break
                time.sleep(0.2)
            for pid in killed:
                if self._pid_alive(pid):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        continue
        if killed:
            self.logger.warning(
                "worktree_manager",
                f"Killed stray worktree processes for '{wt_name}': {killed}",
            )
        return killed

    def kill_strays(self, wt_name: str) -> list:
        """清扫指定 worktree 的残留进程的公开收口（code-review 2b6a4d03be2e）。

        Manager 外部调用方（agent_runner 终态收割等）只经本方法使用清扫
        能力，不直调下划线私有实现；实现仍委托 ``_kill_worktree_strays``。
        """
        return self._kill_worktree_strays(wt_name)

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """/proc 存活探针（kill 0）：进程存在即存活（僵尸差异可接受）。"""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
