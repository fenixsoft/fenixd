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

from core.admin_store import _fsync_parent_dir
from core.proc_utils import guard_killpg, pid_alive_signal, proc_start_ticks

SERVERS_FILENAME = "servers.json"

# kill_process_group 的 SIGTERM→SIGKILL 升级固定等待秒数（就绪判据为组非空
# 轮询）。与 core.proc_utils.kill_process_group 的 TERM_GRACE_SECONDS（默认
# 5 秒）构成并行两套击杀时序常量（未并入的差异理由见 kill_process_group
# docstring）；两侧取值由 tests/test_serving_registry_kill_timing.py 守卫
# 钉住，单侧调整须两侧同步修订并更新守卫断言，防同名语义静默分叉。
KILL_WAIT_SECONDS = 3.0


def servers_path(project_root) -> Path:
    """登记文件绝对路径：<project_root>/.fenix/verify-serving/servers.json。"""
    return Path(project_root) / ".fenix" / "verify-serving" / SERVERS_FILENAME


def _pid_eq(stored, pid) -> bool:
    """登记 pid 严格比对（两侧都须为真整型）。

    bool 是 int 子类：手改 servers.json 写入的 ``{"pid": true}`` 在纯 ``==``
    比对下会与整型 pid=1 互相匹配（True == 1），导致 register 幂等误命中、
    remove 误摘合法条目——此处双侧都排除 bool 后才允许值比较。
    """
    return (
        isinstance(stored, int)
        and not isinstance(stored, bool)
        and isinstance(pid, int)
        and not isinstance(pid, bool)
        and stored == pid
    )


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
            # fdopen 失败路径显式接管（对齐 regression._atomic_write /
            # verdict_evidence 先例 cbb57806fbfd）：with 的 close 只在 fdopen
            # 成功后才生效，fdopen 自身抛错时裸 fd 无人关闭——f 为 None 时
            # 兜底 os.close。
            f = None
            try:
                f = os.fdopen(fd, "w", encoding="utf-8")
                json.dump(records, f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            finally:
                if f is not None:
                    f.close()
                else:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            os.replace(str(tmp_path), str(self.path))
            # rename 生效后刷父目录项，防掉电后 servers.json 整体回退为旧
            # 内容（对齐 admin_store 原子写四段式；复用 _fsync_parent_dir，
            # 内部吞 EINVAL 等目录 fsync 不支持的异常，尽力而为）
            _fsync_parent_dir(self.path)
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

        Returns: 是否发生写入（False = 已存在且快照未过期，幂等跳过；
        写盘失败同样返回 False，但会记 warning 以便排障）。
        """

        def _fn(records):
            for r in records:
                if _pid_eq(r.get("pid"), pid) and r.get("spec") == spec:
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
                    r
                    for r in records
                    if not (_pid_eq(r.get("pid"), pid) and r.get("spec") == spec)
                ]
            else:
                records[:] = [r for r in records if not _pid_eq(r.get("pid"), pid)]
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

    有快照而当前读数读不到（/proc/<pid>/stat 瞬时不可读等）→ 返回 None
    （「读不到＝无法核实」，≠「核实为另一实例」）：sweep 侧跳过本轮收割
    且不摘登记、下轮重试——刚被 pid_alive 确认存活的实例不因瞬时读失败
    被永久摘出登记、失去唯一收割通道。非 Linux 无 /proc 的登记项
    start_ticks 快照本就为 None、不进快照分支（仍走下方 worktree/放行
    路径），恒 None 形态不受影响。
    两信号皆不可得（旧格式登记项且 worktree 为空、或非 Linux）→ 放行收割
    保持既有行为：登记制收割是该形态（兜底 spawn 登记空 worktree）唯一的
    孤儿清理通道，保守少杀等于永久放弃清算；新登记项一律带 starttime
    快照，pid 复用主风险面已封。

    Returns: True＝允许收割；False＝身份失配（摘登记不杀组）；None＝
    无法核实（快照在而读数缺失，跳过本轮收割且保留登记）。
    """
    recorded = entry.get("start_ticks")
    # bool 是 int 子类（口径同 _pid_eq / sweep 的 pid 校验）：手改文件写入
    # 的 {"start_ticks": true} 若放行进快照分支，True(==1) 对真实 tick 数
    # 恒为假 → 恒判「身份失配」摘登记不杀；排除后落回下方 worktree/放行路径。
    if (
        isinstance(recorded, int)
        and not isinstance(recorded, bool)
        and recorded > 0
    ):
        cur = _proc_start_ticks(pid)
        if cur is None:
            # 「读不到＝无法核实」不在此判失配：返回 None 让 sweep 跳过
            # 本轮收割且保留登记（下轮重试），仅读数存在且不等才摘除。
            return None
        return cur == recorded
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

    与 core.proc_utils.kill_process_group（「SIGTERM→等待→SIGKILL」收口
    单点，item 21d8a42c21c1）构成并行的两套实现，未并入的差异清单：本
    函数句柄是裸 pid（登记条目无 Popen 句柄，无 wait/收尸环节）、等待
    时长固定 3 秒 vs 单点 term_grace=5、就绪判据是进程组非空轮询
    （killpg(pgid, 0)，覆盖组长先退的组内孤儿）vs 单点 popen.poll()（leader
    回收即返回，组内孤儿另由 sig=0 探活补刀口径覆盖）。两套时序参数与
    语义今后演化须两侧同步修订，防单侧漂移。

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
    deadline = time.monotonic() + KILL_WAIT_SECONDS
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
    malformed = []
    # 待摘名单（收割/死亡条目的 (pid, spec) 对）：收尾与 malformed 合并为
    # 单次 _mutate 批量摘除，避免逐条 remove 造成的一轮清扫 N+1 次完整落盘
    stale = []
    for entry in reg.entries():
        pid = entry.get("pid")
        if not (isinstance(pid, int) and not isinstance(pid, bool)) or pid <= 0:
            # 畸形条目（手改文件/旧格式残留，含 bool 形态——bool 是 int 子类，
            # {"pid": true} 若放行会被当作 pid=1 走收割路径：pid_alive(1) 恒
            # 存活，进而对 pgid 1 投递 SIGTERM/SIGKILL）既不可收割也无 pid 可
            # 供 remove 匹配，直接跳过会让它在 servers.json 永久滞留、每轮
            # 清扫重复跳过——记入待摘名单，收尾统一摘除保证登记表可自清。
            malformed.append(entry)
            continue
        raw_spec = entry.get("spec")
        if raw_spec and not isinstance(raw_spec, str):
            # 畸形条目（手改文件变体，与上方 bool pid 同一威胁模型）：spec 非
            # 字符串时本函数归一的 str 形态（如 str(5)="5"）与 remove 内
            # r.get("spec") == spec 的严格值比较永不相等，remove 静默返回
            # False——进程已亡则条目每轮清扫永久滞留空转；进程存活被收割后
            # 登记项同样永远摘不掉。记入待摘名单，收尾统一摘除保证登记表可
            # 自清；身份已损坏的条目不做收割投递（宁少杀，同
            # _harvest_identity_ok 的保守纪律）。falsy 非字符串（0/False/None）
            # 归一为空串后走 remove 的仅 pid 匹配分支，本就能被摘除，不在此列。
            malformed.append(entry)
            continue
        spec = str(entry.get("spec") or "")
        alive = pid_alive(pid)
        in_flight = bool(is_spec_in_flight(spec)) if is_spec_in_flight else False
        if alive and in_flight:
            continue  # 属主 spec 在飞，保留
        if alive:
            # 进程仍存活但属主 spec 不在飞：核对身份后收割进程组再移除登记
            # （pid 复用防误杀：身份不匹配只移除登记，不动无关进程组）
            identity_ok = _harvest_identity_ok(entry, pid)
            if identity_ok is None:
                # starttime 快照在而当前读数读不到（瞬时 /proc 读失败）：
                # 无法核实≠身份失配，本轮跳过收割且不摘登记（下轮重试）
                # ——否则刚被 pid_alive 确认存活的实例会被永久摘出登记、
                # 失去唯一收割通道（command 型 serve 无 marker pgrep 兜底）。
                if logger:
                    logger.warning(
                        "serving_registry",
                        f"skip harvest pid={pid} (spec={spec or '-'}) identity "
                        f"unverifiable (proc stat unreadable) — keeping entry "
                        f"for next sweep",
                    )
                continue
            if identity_ok:
                # 仅在真正向进程组发出过信号时计数（进程在 pid_alive 与
                # getpgid 之间已退出的 already-gone 情形不算，避免虚报）
                delivered = kill_process_group(pid, logger)
                if delivered:
                    harvested += 1
                elif pid_alive(pid):
                    # 投递失败（getpgid 遭 EPERM、guard_killpg 守卫拒绝等，
                    # 未发出任何信号）且进程仍存活：与 identity unverifiable
                    # 同口径——本轮跳过收割且不摘登记（下轮重试），否则刚被
                    # pid_alive 确认存活的实例被永久摘出登记、失去唯一收割
                    # 通道（command 型 serve 无 marker pgrep 兜底）。复核已亡
                    # 的 already-gone 情形照旧落入待摘名单收尾摘除。
                    if logger:
                        logger.warning(
                            "serving_registry",
                            f"skip harvest pid={pid} (spec={spec or '-'}) "
                            f"kill delivery failed (no signal sent) but "
                            f"process alive — keeping entry for next sweep",
                        )
                    continue
            elif logger:
                logger.warning(
                    "serving_registry",
                    f"skip harvest pid={pid} (spec={spec or '-'}) identity "
                    f"mismatch — pid likely reused; removed registry entry "
                    f"without killing",
                )
        # 记入待摘名单（匹配语义同 remove：_pid_eq 严格 pid 匹配，spec 非空
        # 时叠加同值限定），收尾统一批量摘除；随行携带身份锚点快照
        # （start_ticks/registered_at）：快照取得与收尾摘除之间隔着收割等待
        # 等秒级窗口（kill_process_group 最长 3 秒），期间旧条目进程已亡、
        # 同 spec 重验 spawn 新实例且系统复用同一 pid 时，register 会就地
        # 刷新该 (pid, spec) 的身份快照——收尾须按锚点复核（范式同
        # state_machine._anchor_recheck_locked 的锁内锚点复核）仍等于快照值
        # 才摘，防 stale 名单按值匹配误删新登记、使新实例脱离登记制收割面。
        stale.append(
            (
                pid,
                spec,
                {
                    "start_ticks": entry.get("start_ticks"),
                    "registered_at": entry.get("registered_at"),
                },
            )
        )
    if malformed or stale:
        # stale 按 (pid, spec) 匹配（语义同 remove），malformed 按值相等匹配
        # （entries() 快照与 _mutate 内重读是两次独立 json 解析，对象身份必然
        # 不同）；pid 须类型精确一致——bool 是 int 子类，畸形 {"pid": true} 与
        # 合法 pid=1 值相等，纯值匹配会把合法条目一并误摘，类型锚定后无误摘
        # 风险，并发 register 的新条目同样不受波及。
        # 锚点已刷新（期间同 (pid, spec) 发生新实例登记）而保留的条目：
        # (pid, spec) 锁内收集，_mutate 返回后（锁外）统一留痕——持锁窗口
        # 不含日志（同 state_machine._anchor_recheck_locked 范式）
        kept_fresh = []

        def _purge(records):
            before = len(records)
            kept = []
            for r in records:
                if any(
                    type(r.get("pid")) is type(m.get("pid")) and r == m
                    for m in malformed
                ):
                    continue
                hit = next(
                    (
                        (pid, spec, anchor)
                        for pid, spec, anchor in stale
                        if _pid_eq(r.get("pid"), pid)
                        and (not spec or r.get("spec") == spec)
                    ),
                    None,
                )
                if hit is None:
                    kept.append(r)
                    continue
                _, _spec, anchor = hit
                # 锁内锚点复核：锚点仍等于 sweep 快照值才认定是快照所指条目
                # 并摘除；不等（register 已刷新 start_ticks/registered_at）
                # 说明是 pid 复用后新登记的身份快照，保留该条目（否则新实例
                # 自此脱离登记制收割面）。
                if all(
                    r.get(f) == anchor.get(f)
                    for f in ("start_ticks", "registered_at")
                ):
                    continue
                kept_fresh.append((hit[0], _spec))
            records[:] = kept
            return len(records) != before

        try:
            reg._mutate(_purge)
        except OSError:
            pass  # 非阻塞：写盘失败下轮清扫再清（同 register/remove 口径）
        for pid, spec in kept_fresh:
            if logger:
                logger.warning(
                    "serving_registry",
                    f"skip purge pid={pid} (spec={spec or '-'}) stale-entry "
                    f"anchor refreshed since snapshot (pid reused by new "
                    f"register?) — keeping refreshed entry",
                )
    if harvested and logger:
        logger.warning(
            "serving_registry",
            f"harvested {harvested} registered serving instance(s) " f"without in-flight spec",
        )
    return harvested
