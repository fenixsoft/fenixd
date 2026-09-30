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
                        r["start_ticks"] = cur
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
        """当前全部登记项（只读快照）。"""
        with self._thread_lock:
            with self._lock() as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                try:
                    return self._read_unlocked(self.path)
                finally:
                    fcntl.flock(lf, fcntl.LOCK_UN)


# ── 进程存活与收割助手（/proc liveness）──────────────────────────────


def pid_alive(pid: int) -> bool:
    """/proc 探针：kill(pid, 0) 成功即存活（忽略僵尸判定差异，够用）。"""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _proc_start_ticks(pid: int):
    """/proc/<pid>/stat 的 starttime 字段（系统启动后的 tick 数），读不到返回 None。

    pid + starttime 唯一确定一个进程实例：原进程退出后 pid 被系统复用时，
    新进程的 starttime 必然不同——以此锚定登记项的收割目标（对 exec/argv
    变化免疫，starttime 在 fork 时即固定）。
    """
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    # comm 字段可含空格与括号：从最后一个 ')' 之后起算（其后首项是字段 3
    # state），starttime 为字段 22 → 相对 state 的第 20 项。
    tail = data.rpartition(")")[2].split()
    if len(tail) < 20:
        return None
    try:
        return int(tail[19])
    except ValueError:
        return None


def _harvest_identity_ok(entry: dict, pid: int) -> bool:
    """收割前身份核对（防 pid 复用误杀，纪律同 worktree_manager/locks.py）。

    pid_alive 命中只说明「该 pid 有主」；daemon 周期性清扫拉长了「原进程
    已退出、pid 被复用给无关进程」的暴露窗口，此时对进程组 SIGTERM/SIGKILL
    会误杀。双信号任一成立才允许收割：

    1. starttime 精确锚定：register 时快照的 /proc starttime（entry 的
       ``start_ticks``）与当前读数一致；
    2. worktree 路径锚定：登记 worktree 非空且 /proc cmdline 或 cwd
       （realpath 归一）引用该目录——覆盖无 starttime 快照的旧格式登记项
       （cmdline/cwd 双通道同 locks.py 的 _pid_in_project_worktrees /
       _kill_worktree_strays 归属核对范式）。

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
        if any(
            t in (wt_text, wt_real) or t.startswith(wt_real + os.sep)
            for t in argv_tokens
        ):
            return True
        try:
            cwd_real = os.path.realpath(os.readlink(f"/proc/{pid}/cwd"))
        except OSError:
            return False
        return cwd_real == wt_real or cwd_real.startswith(wt_real + os.sep)
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
        try:
            os.killpg(pgid, signal.SIGTERM)
            sent = True
        except (PermissionError, OSError):
            pass
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        # 就绪判据针对进程组而非组长：shell 形态命令后台化实例后组长可先于
        # 组内成员退出，只探组长会让存活成员跳过等待与 SIGKILL 兜底。
        # sig=0 只做存在性检查、不投递信号，孤儿组（组长已死）语义不受影响；
        # EPERM 等其他 OSError 说明组仍非空，同样按存活继续等待并按期升级。
        if pgid is None:
            # getpgid 失败（组长已亡且未向组发过信号）：无从探组，退回组长探针
            if not pid_alive(pid):
                return sent
        else:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return sent  # 组空（组长已死且无存活成员）
            except OSError:
                pass  # 组非空但无权探测 → 按存活继续等待
        time.sleep(0.2)
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (PermissionError, OSError):
            pass
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
