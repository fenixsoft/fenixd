"""serving_registry.py — .fenix/verify-serving/servers.json 登记制（verify-process-lifecycle D6）。

command 型被测实例（verify.yaml serve.kind=command 与 _ensure_app_reachable 兜底
spawn）创建时登记（pid/port/spec/worktree）、stop 时移除；daemon 启动与周期清扫
按 /proc liveness 收割「无在飞 spec 但进程仍存活」的登记项并移除登记。

文件属运行时状态（`kind: reference`，非仓库交付物，gitignore 排除）；读写走
`.fenix/` 既有 lock 模式（fcntl 文件锁 + 原子写 rename，见 admin_store 同款）。

登记制是兜底增强而非唯一防线：v2 dev-server 仍有 marker pgrep 扫描路径
（core/v2_dev_server.cleanup_orphans）；json 写入失败/崩溃丢条目仅损失
收割效率，不制造新失败。
"""

import fcntl
import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from core.proc_utils import guard_killpg, pid_alive_signal, proc_start_ticks

SERVERS_FILENAME = "servers.json"


def servers_path(project_root) -> Path:
    """登记文件绝对路径：<project_root>/.fenix/verify-serving/servers.json。"""
    return Path(project_root) / ".fenix" / "verify-serving" / SERVERS_FILENAME


class ServingRegistry:
    """servers.json 登记表：进程内互斥 + 跨进程 fcntl 文件锁。"""

    def __init__(self, project_root, logger=None):
        self.project_root = Path(project_root)
        self.path = servers_path(self.project_root)
        self._lockfile = Path(str(self.path) + ".lock")
        self._thread_lock = threading.Lock()
        self.logger = logger

    # ── 内部：加锁读/写（admin_store 同款模式）──────────────────────

    def _lock(self):
        self._lockfile.parent.mkdir(parents=True, exist_ok=True)
        return open(self._lockfile, "w")

    @staticmethod
    def _read_unlocked(path: Path) -> list:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [e for e in data if isinstance(e, dict)]

    def _write_unlocked(self, records: list):
        """原子写（临时文件 + replace），调用方须已持有文件排他锁。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path_str = tempfile.mkstemp(
            prefix=".servers.", suffix=".tmp", dir=str(self.path.parent)
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp_path), str(self.path))
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _mutate(self, fn):
        """在单次排他锁内完成读-改-写，返回 fn(records) 的结果。

        跨进程并发（daemon 周期清扫与验证线程 register/remove）若分别在两次
        锁获取中读改写会互相覆盖丢失记录，必须一次性持锁完成。
        fn 返回 False 表示无变更，跳过写回（文件 mtime 保持不变）。
        """
        with self._thread_lock:
            with self._lock() as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                try:
                    records = self._read_unlocked(self.path)
                    result = fn(records)
                    if result is not False:
                        self._write_unlocked(records)
                    return result
                finally:
                    fcntl.flock(lf, fcntl.LOCK_UN)

    # ── 公开 API ───────────────────────────────────────────────────

    def register(self, pid: int, port, spec: str, worktree) -> bool:
        """登记一条实例（创建时）。同 (pid, spec) 已登记时幂等跳过；
        但若该 pid 的 /proc starttime 与快照不一致（旧进程退出后 pid 被
        复用给同 spec 的新 spawn），就地刷新身份快照后写回。

        Returns: 是否发生写入（False = 已存在且快照未过期，幂等跳过）。
        """

        def _fn(records):
            for r in records:
                if r.get("pid") == pid and r.get("spec") == spec:
                    # pid 复用防护：身份快照过期（cur 与快照不一致）说明登记
                    # 的已是另一个进程实例，沿用旧快照会让 sweep 收割时
                    # _harvest_identity_ok 必然失配——只摘登记不杀组，新实例
                    # 从此脱离登记制无人收割。cur 读不到（进程已亡/无 /proc）
                    # 不刷新：死条目由 sweep 的 liveness 检查兜底摘除。
                    cur = _proc_start_ticks(pid)
                    if cur is not None and cur != r.get("start_ticks"):
                        # 登记切换到新进程实例：port/registered_at/worktree
                        # 与身份快照一并刷新（docstring 所指「身份快照」的
                        # 完整语义）——消费侧 verification/serving 按 pid
                        # 存活 + registered_at 最新取 port 拼 base_url，只刷
                        # start_ticks 会把请求持续打向旧实例端口。
                        r["start_ticks"] = cur
                        r["port"] = port
                        r["worktree"] = str(worktree) if worktree else ""
                        r["registered_at"] = int(time.time())
                        return True
                    return False
            records.append(
                {
                    "pid": pid,
                    "port": port,
                    "spec": spec,
                    "worktree": str(worktree) if worktree else "",
                    "registered_at": int(time.time()),
                    # 进程身份快照（防 pid 复用误杀，见 _harvest_identity_ok）
                    "start_ticks": _proc_start_ticks(pid),
                }
            )
            return True

        try:
            return bool(self._mutate(_fn))
        except OSError:
            if self.logger:
                self.logger.warning("serving_registry", f"登记写盘失败（非阻塞）: {self.path}")
            return False

    def remove(self, pid: int, spec: str = "") -> bool:
        """移除登记（stop 时）。按 pid（+spec 可选）匹配。

        Returns: 是否实际移除（False = 无匹配条目；写盘失败同样返回
        False，但会记 warning 以便排障）。
        """

        def _fn(records):
            before = len(records)
            if spec:
                records[:] = [
                    r for r in records if not (r.get("pid") == pid and r.get("spec") == spec)
                ]
            else:
                records[:] = [r for r in records if r.get("pid") != pid]
            return len(records) != before

        try:
            return bool(self._mutate(_fn))
        except OSError:
            if self.logger:
                self.logger.warning(
                    "serving_registry", f"登记移除写盘失败（非阻塞）: {self.path}"
                )
            return False

    def entries(self) -> list:
        """当前全部登记项（只读快照）。

        锁获取（mkdir/open）与 flock 的 OSError 同 register/remove 口径降级
        warning 并返回空列表：登记制是兜底增强，读失败仅损失收割效率，
        不制造新失败——sweep 被启动清扫直接消费，entries() 不可让 .fenix
        目录异常穿透中断 daemon 启动。finally unlock 仍保证异常路径不漏锁
        （flock(LOCK_EX) 未成功时无锁可放，`with self._lock()` 关闭句柄兜底）。
        """
        try:
            with self._thread_lock:
                with self._lock() as lf:
                    fcntl.flock(lf, fcntl.LOCK_EX)
                    try:
                        return self._read_unlocked(self.path)
                    finally:
                        fcntl.flock(lf, fcntl.LOCK_UN)
        except OSError:
            if self.logger:
                self.logger.warning("serving_registry", f"登记读取失败（非阻塞）: {self.path}")
            return []


# ── 进程存活与收割助手（/proc liveness）──────────────────────────────


def pid_alive(pid: int) -> bool:
    """/proc 探针：kill(pid, 0) 成功即存活（忽略僵尸判定差异，够用）。

    实现上移 core.proc_utils.pid_alive_signal 单点（consistency：探针助手
    收敛；与 v2_dev_server 的 /proc stat 口径各有场景理由，语义不变）。
    """
    return pid_alive_signal(pid)


def _proc_start_ticks(pid: int):
    """/proc/<pid>/stat 的 starttime 字段（系统启动后的 tick 数），读不到返回 None。

    pid + starttime 唯一确定一个进程实例：原进程退出后 pid 被系统复用时，
    新进程的 starttime 必然不同——以此锚定登记项的收割目标（对 exec/argv
    变化免疫，starttime 在 fork 时即固定）。

    实现上移 core.proc_utils.proc_start_ticks 单点（consistency：探针助手
    收敛），本壳保留既有模块内调用点。
    """
    return proc_start_ticks(pid)


def _harvest_identity_ok(entry: dict, pid: int) -> bool:
    """收割前身份核对（防 pid 复用误杀，纪律同 worktree_manager/locks.py）。

    pid_alive 命中只说明「该 pid 有主」；daemon 周期性清扫拉长了「原进程
    已退出、pid 被复用给无关进程」的暴露窗口，此时对进程组 SIGTERM/SIGKILL
    会误杀。双信号任一成立才允许收割：

    1. starttime 精确锚定：register 时快照的 /proc starttime（entry 的
       ``start_ticks``）与当前读数一致；
    2. worktree 路径锚定：登记 worktree 非空且 cwd（realpath 归一）位于
       该目录内——覆盖无 starttime 快照的旧格式登记项（归属核对范式同
       locks.py 的 _pid_in_project_worktrees / _kill_worktree_strays）。
       argv 引用该目录不再是独立放行信号（code-review b23dfb5c0114：
       tail -f <wt>/x.log、grep ... <wt>/src 这类仅引用路径的无关进程
       argv 同样命中），须叠加 cwd 同域第二信号才判命中。

    有快照却读不到当前读数（非 Linux 无 /proc 等）→ 不匹配（宁可少杀）。
    两信号皆不可得（旧格式登记项且 worktree 为空、或非 Linux）→ 放行收割
    保持既有行为：登记制收割是该形态（兜底 spawn 登记空 worktree）唯一的
    孤儿清理通道，保守少杀等于永久放弃清算；新登记项一律带 starttime
    快照，pid 复用主风险面已封。
    """
    recorded = entry.get("start_ticks")
    if isinstance(recorded, int) and recorded > 0:
        return _proc_start_ticks(pid) == recorded
    wt_text = str(entry.get("worktree") or "")
    if wt_text:
        wt_real = os.path.realpath(wt_text)
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv_tokens = [
                    t.decode("utf-8", "replace") for t in f.read().split(b"\0") if t
                ]
        except OSError:
            argv_tokens = []
        # 整 token 匹配（裸子串会把 argv 中恰好含该路径字符串的无关进程
        # 如 grep/tail 误判为身份命中并遭整组击杀）
        argv_hit = any(
            t in (wt_text, wt_real) or t.startswith(wt_real + os.sep)
            for t in argv_tokens
        )
        try:
            cwd_real = os.path.realpath(os.readlink(f"/proc/{pid}/cwd"))
        except OSError:
            cwd_real = None
        cwd_in_wt = cwd_real is not None and (
            cwd_real == wt_real or cwd_real.startswith(wt_real + os.sep)
        )
        if argv_hit and not cwd_in_wt:
            # code-review b23dfb5c0114：argv 的 worktree 等值/前缀命中不再
            # 独立放行——tail -f <wt>/x.log、grep ... <wt>/src 这类仅引用
            # worktree 内路径的无关进程 argv 同样命中，单凭 argv 判身份会
            # 整组误杀，须叠加 cwd 同域第二信号。真实例 spawn 即
            # cwd=worktree（见 serving._serve_command_in_worktree），两信号
            # 俱全不受影响；argv 缺路径的进程形态与旧格式登记项仍可经 cwd
            # 单信号命中，保守少杀但不放弃清算。
            return False
        return cwd_in_wt
    return True


def kill_process_group(pid: int, logger=None) -> bool:
    """进程组 SIGTERM → 短等待 → SIGKILL 兜底（同 CommandVerifyServer.stop 语义）。

    就绪等待以「进程组非空」（killpg(pgid, 0)）为判据而非组长存活，避免
    shell 形态命令后台化实例后组长先退、组内存活成员逃过 SIGKILL 兜底。

    Args:
        pid: 目标进程组长 pid。
        logger: 可选日志器；EPERM 放弃收割时留痕（与 sweep 的 identity
            mismatch 同款 warning）。

    Returns: 是否向进程组发出过信号。
    """
    sent = False
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        pgid = None  # 组长已亡：走下方组长探针分支
    except PermissionError:
        # EPERM（进程属其他用户/受限命名空间）同样无从探组：此时 pid_alive
        # 可能恒 True，固定 3 秒空转后仍发不出任何信号——直接放弃并留痕，
        # 避免白等与静默放弃（行为仍偏保守，不误杀）。
        if logger:
            logger.warning(
                "serving_registry",
                f"skip kill pid={pid}: getpgid denied (EPERM, process owned "
                f"by another user or restricted namespace) — no signal sent",
            )
        return sent
    except OSError:
        pgid = None
    if pgid is not None:
        # 击杀经自保护守卫（add-killpg-self-guard）：pgid 已解析直传；守卫拒绝
        # （自身组/非正 pgid）与组已不存在同样静默（sent 维持 False）。
        if guard_killpg(
            pgid, signal.SIGTERM, caller="serving_registry.kill_process_group", resolve=False
        ):
            sent = True
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        # 就绪判据针对进程组而非组长：shell 形态命令后台化实例后组长可先于
        # 组内成员退出，只探组长会让存活成员跳过等待与 SIGKILL 兜底。
        # sig=0 只做存在性检查、不投递信号，孤儿组（组长已死）语义不受影响；
        # EPERM 等其他 OSError 说明组仍非空，同样按存活继续等待并按期升级。
        if pgid is None:
            # getpgid 失败（组长已亡且未向组发过信号）：组长 pgid 恒等于
            # 自身 pid，shell 形态命令后台化遗留的孤儿组仍可以 killpg(pid, 0)
            # 探测——命中即按 pgid=pid 接管后续就绪等待与 SIGKILL 升级，
            # 不让组内存活成员逃过兜底；组确已空（ESRCH）才返回。pid 复用
            # 误判风险与下方组长探针同源（且进入本函数前 sweep 已做过
            # starttime 身份核对），保守口径不变：无权探测（EPERM）按存活
            # 继续等待但不升级投递。
            try:
                os.killpg(pid, 0)
            except ProcessLookupError:
                return sent  # 孤儿组已空（无存活成员）
            except OSError:
                pass  # 组非空但无权探测 → 按存活继续等待（同 pgid 路径口径）
            else:
                pgid = pid
                # 孤儿组仍存活：接管 pgid 后补发一次 SIGTERM 再进入就绪
                # 等待——本路径因 getpgid 解析不到组长跳过了顶部投递，
                # 组内存活成员从未收到优雅终止信号，直接升级 SIGKILL 会
                # 硬杀被测实例（未 flush 的状态/日志丢失）；补发后「SIGTERM
                # → 短等待 → SIGKILL 兜底」三段式契约同样覆盖孤儿组。
                # 仅在接管时刻发这一次（后续轮次走 pgid 已知分支纯探活），
                # 不与正常路径重复投递；守卫拒绝/组已消失同样静默。
                if guard_killpg(
                    pgid, signal.SIGTERM, caller="serving_registry.kill_process_group", resolve=False
                ):
                    sent = True
        else:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return sent  # 组空（组长已死且无存活成员）
            except OSError:
                pass  # 组非空但无权探测 → 按存活继续等待
        time.sleep(0.2)
    if pgid is not None:
        # SIGKILL 实际发出成功同样置位（守卫拒绝/组已不存在则静默，sent
        # 维持原值），保证返回值与「是否向进程组发出过信号」的契约一致
        # （sweep 的 harvested 计数依赖它）。
        if guard_killpg(
            pgid, signal.SIGKILL, caller="serving_registry.kill_process_group", resolve=False
        ):
            sent = True
    return sent


def sweep(project_root, logger=None, is_spec_in_flight=None) -> int:
    """收割无在飞 spec 的登记项并移除登记（daemon 启动与周期清扫共用）。

    Args:
        project_root: 项目根。
        logger: 可选日志器。
        is_spec_in_flight: callable(spec_name) -> bool，判定 spec 当前是否在飞
            （验证活跃）。缺省 None = 全部视为非在飞（daemon 启动场景）。

    Returns: 收割的进程数。
    """
    reg = ServingRegistry(project_root, logger)
    harvested = 0
    for entry in reg.entries():
        pid = entry.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            continue
        spec = str(entry.get("spec") or "")
        alive = pid_alive(pid)
        in_flight = bool(is_spec_in_flight(spec)) if is_spec_in_flight else False
        if alive and in_flight:
            continue  # 属主 spec 在飞，保留
        if alive:
            # 进程仍存活但属主 spec 不在飞：核对身份后收割进程组再移除登记
            # （pid 复用防误杀：身份不匹配只移除登记，不动无关进程组）
            if _harvest_identity_ok(entry, pid):
                # 仅在真正向进程组发出过信号时计数（进程在 pid_alive 与
                # getpgid 之间已退出的 already-gone 情形不算，避免虚报）
                if kill_process_group(pid, logger):
                    harvested += 1
            elif logger:
                logger.warning(
                    "serving_registry",
                    f"skip harvest pid={pid} (spec={spec or '-'}) identity "
                    f"mismatch — pid likely reused; removed registry entry "
                    f"without killing",
                )
        reg.remove(pid, spec)
    if harvested and logger:
        logger.warning(
            "serving_registry",
            f"harvested {harvested} registered serving instance(s) " f"without in-flight spec",
        )
    return harvested
