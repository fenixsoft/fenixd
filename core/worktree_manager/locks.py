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

from core.worktree_manager import _is_claude_process  # noqa: E402
from core.worktree_manager.constants import (  # noqa: E402
    PROCESS_SCAN_CACHE_SECONDS,
    STALE_LOCK_IDLE_SECONDS,
)


class G3LockMixin:
    """G3 锁治理/进程判活——纯工具层，低耦合（design D1 表 A G3）。"""

    @staticmethod
    def _lock_spec_name(lock_key: str) -> str:
        """锁 key（``<spec>:<agent_type>``）→ spec 名。"""
        return lock_key.split(":")[0]

    @staticmethod
    def _lock_family_prefix(lock_key: str) -> str | None:
        """锁 key（``<spec>:<agent_type>``）→ 该族 worktree/run 流的目录前缀。

        create() 的前缀裁定只有两族形状（lifecycle.create：verifier → "verify"，
        其余 agent_type → "impl"，与 cleanup finally / keep_for_reuse 的
        verifier/non-verifier 家族口径同源）。解析不出 agent_type（无 ":" 或空
        后缀）返回 None：调用方（refresh_locks 陈锁回收）退回 spec 粒度保守
        判活，宁多留不误放。
        """
        agent_type = lock_key.partition(":")[2]
        if not agent_type:
            return None
        return "verify" if agent_type == "verifier" else "impl"

    def _register_spec_locks(self, spec_name: str) -> None:
        """按 spec 名重建两把锁（impl + verify），与 create() 的 key 形态一致。

        孤儿进程可能来自任一 agent 类型，进程表只能证明「该 spec 仍有活跃
        worktree」而无法可靠区分前缀，因此两把一起登记，宁可多拦不漏放。

        cc3fc088a7db 依赖边界声明：create() 的锁键词表覆盖 fast-track /
        implementer / planner-plan / planner-judge / verifier / code-fix 六种
        agent_type，而本进程判活重建只登记 implementer / verifier 两族。后果
        有界：spec 级探针 has_active_worktree(spec) 仍按 ``<spec>:`` 前缀匹配
        拦截（宁可多拦），仅 runner 侧按 agent_type 精确键的
        has_active_lock(spec, "<agent_type>") 对未登记族（fast-track、code-fix
        等）恒 False——attempt 级并行保护对该族失效，失效方向保守（放行而非
        误拦）。调用方依赖该族探针做 attempt 级互斥前，须先扩展此处的登记
        词表（或为进程 cmdline→agent_type 建立可靠解析）。

        add 与 _lock_since 写入全程持 _spec_lock_th（code-review item
        776cffc0a278），与 create / release_spec_lock 的加锁纪律对齐。
        """
        with self._spec_lock_th:
            self._spec_locks.add(f"{spec_name}:implementer")
            self._lock_since[f"{spec_name}:implementer"] = time.time()
            self._spec_locks.add(f"{spec_name}:verifier")
            self._lock_since[f"{spec_name}:verifier"] = time.time()

    def _release_spec_locks(
        self, spec_name: str, reason: str, not_after: float | None = None,
        lock_key: str | None = None,
    ) -> list:
        """释放该 spec 的全部在册锁，返回被释放的 key（已不在册则返回空）。

        薄委托（code-review item 53b7d6a78045）：摘锁口径单源在
        ``_release_spec_locks_core``（与 legacy_registry._release_spec_locks_of
        同一底层实现，lock_key/family/not_after 三维可选），本方法保持既有签名
        （reason 供调用方表达语境、实现不消费）与行为不变。

        lock_key（code-review item 216784713669，refresh_locks 家族过滤回收
        专用）：传入时只摘这一把锁键——家族过滤判活只证明了本族已死，同 spec
        在飞他族锁的生死未判定，全摘会让其失去锁保护（重开双派发窗口）；None
        保持既有「按 spec 名全摘」语义（has_active_worktree 调用方不变）。

        not_after：入口时刻守卫（code-review item cec36ef4e1fb，与 cleanup
        finally 的 cleanup_entry_ts 同款）——仅摘除 _lock_since 不晚于该时刻
        的在册锁。判定链（进程扫描 / 流 mtime）在持锁之前完成，期间并发
        create() / _register_spec_locks 重新登记的同键新锁 _lock_since 晚于
        入口时刻，跳过不误删，防止新 run 在 create 到子进程可被进程表扫到
        的构建窗口内失去锁保护（重开双派发窗口）；None 表示不设限（行为同
        旧版）。
        """
        return self._release_spec_locks_core(
            spec_name, not_after=not_after, lock_key=lock_key,
        )

    def _release_spec_locks_core(
        self, spec_name: str, not_after: float | None = None,
        lock_key: str | None = None, family: str | None = None,
    ) -> list:
        """spec 摘锁单一底层实现（code-review item 53b7d6a78045）。

        locks._release_spec_locks（lock_key 精确摘除 / spec 前缀全摘 + not_after）
        与 legacy_registry._release_spec_locks_of（spec 前缀 + not_after + family
        过滤）原各有一套并行实现，核心判定高度重叠、口径调整须同改两处且已出现
        能力分叉——收敛为此单源，后续调整摘锁纪律只改此处。三个可选维度的组合
        语义：lock_key 传入时精确匹配该键（spec_name 不参与匹配），否则按
        ``<spec>:`` 前缀匹配；family 按 "verifier"/"non-verifier" 二族过滤锁键
        的 agent_type 后缀；not_after 仅摘 _lock_since 不晚于该时刻的锁
        （None 不设限）。

        to_remove 计算与摘除全程持 _spec_lock_th（code-review item
        776cffc0a278）：无锁迭代 _spec_locks 时并发 create/cleanup 增删
        会抛 "Set changed size during iteration"，且摘除须与 _lock_since
        清理原子（纪律同 lifecycle.py:593 段）。调用方（has_active_worktree
        / refresh_locks / keep_for_reuse）均未持该非重入锁，锁内取锁无死锁
        风险。迭代用 sorted 快照（对齐 _release_spec_locks_of 既有纪律，
        消解 set 迭代序的非确定性），删除顺序不影响语义。
        """
        with self._spec_lock_th:
            to_remove = [
                k for k in sorted(self._spec_locks)
                if (
                    (k == lock_key)
                    if lock_key is not None
                    else (self._lock_spec_name(k) == spec_name)
                )
                and (not_after is None or self._lock_since.get(k, 0.0) <= not_after)
                and (
                    family is None
                    or (
                        (k.partition(":")[2] == "verifier")
                        if family == "verifier"
                        else (k.partition(":")[2] != "verifier")
                    )
                )
            ]
            for k in to_remove:
                self._spec_locks.discard(k)
                self._lock_since.pop(k, None)
            return to_remove

    def _lock_young(self, spec_name: str, family: str | None = None) -> bool:
        """该 spec 任一在册锁的锁龄 < STALE_LOCK_IDLE_SECONDS（create 构建窗口豁免）。

        family（code-review item 5d9601004a62，refresh_locks 家族过滤回收专用）：
        传入时只考察该家族前缀（_lock_family_prefix 口径：verify/impl）的在册
        锁，使构建窗口豁免与家族过滤判活同口径——本族陈锁不因同 spec 他族恰有
        年轻构建而被庇护跳过回收；None（缺省）保持 spec 全量扫描。
        has_active_worktree 调用点维持 spec 粒度（不传 family）：其陈锁释放按
        spec 全摘（含他族键），豁免须覆盖全部将被摘除的家族，按本族过滤会让
        他族年轻锁在全摘中失去锁保护、重开双派发窗口。

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
                if family is not None and self._lock_family_prefix(k) != family:
                    continue
                since = self._lock_since.get(k)
                if since is not None and (now - since) < STALE_LOCK_IDLE_SECONDS:
                    return True
            return False

    def _spec_process_alive(
        self, spec_name: str, prefixes: tuple[str, ...] | None = None,
    ) -> bool:
        """进程表中是否存在指向该 spec worktree 的进程（带短缓存）。

        进程消失/出现以缓存窗口（PROCESS_SCAN_CACHE_SECONDS）为粒度生效，
        避免派发热路径上的 pgrep 风暴。

        prefixes（code-review item 216784713669，refresh_locks 陈锁回收专用）：
        家族限定扫描——只匹配指定 worktree 前缀族（如 ("verify",)）的进程，使
        死家族的锁不被同 spec 他族活进程庇护。默认 None 保持 spec 粒度（
        has_active_worktree 派发闸门语义不变）。注入替身扫描器的契约只收
        spec 名（无家族维度），家族限定调用遇 TypeError 即退回 spec 粒度
        （方向保守：只延后回收，不会误回收）。缓存键按扫描口径区分（spec
        粒度用裸 spec 名、家族限定用 (spec, prefixes) 二元组），互不串味。
        """
        now = time.monotonic()
        cache_key = spec_name if prefixes is None else (spec_name, prefixes)
        cached = self._proc_scan_cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return cached[1]
        try:
            if prefixes is None:
                alive = bool(self._process_scanner(spec_name))
            else:
                try:
                    alive = bool(self._process_scanner(spec_name, prefixes=prefixes))
                except TypeError:
                    alive = bool(self._process_scanner(spec_name))
        except Exception as e:  # 扫描异常视为不可用：保守按无进程处理并记日志
            self.logger.warning(
                "worktree_manager",
                f"Process scan failed for '{spec_name}' (treated as absent): {e}",
            )
            alive = False
        self._proc_scan_cache[cache_key] = (now + PROCESS_SCAN_CACHE_SECONDS, alive)
        return alive

    def _pgrep_spec_process(
        self, spec_name: str, prefixes: tuple[str, ...] = ("impl", "verify"),
    ) -> bool:
        """pgrep 匹配 cmdline 含 ``worktrees/{impl,verify}-<spec>-`` 的 agent 进程。

        prefixes（code-review item 216784713669）：家族限定扫描——refresh_locks
        陈锁回收按锁键的 agent_type 家族只扫本族前缀，使死家族的锁不被他族活
        进程庇护；缺省双族，行为同旧版。

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
        for prefix in prefixes:
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

    def _latest_stream_mtime(
        self, spec_name: str, prefixes: tuple[str, ...] = ("impl", "verify"),
    ) -> float | None:
        """该 spec 全部 run 流文件（.fenix/runs/{impl,verify}-<spec>-*.jsonl）的最新 mtime。

        prefixes（code-review item 216784713669）：家族限定——refresh_locks 只看
        本族流文件，他族流仍在增长不再庇护本族死锁；缺省双族，行为同旧版。

        无任何流文件返回 None。
        """
        runs_dir = self.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return None
        newest: float | None = None
        try:
            for prefix in prefixes:
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
