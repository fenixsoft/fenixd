"""recovery.py — RecoveryWatch：恢复闭环复查注册/复查/持久化与 dispatch_stalled 信号上报（refactor-core-packages 阶段 6）。

SPEC 状态经门面回引 self._pm.state_machine（design D3 规则 3）；
组件内非自有状态/方法的 self.X 一律改写为 self._pm.X，保住门面
实例上的测试补丁缝与跨组件调用路径。

"""

from pathlib import Path
import hashlib
import json
import os
import tempfile
import threading
import time
from datetime import datetime

# dispatch_stalled 信号的建议处置（与 admin_monitor.SIGNAL_RECOMMENDATION 同源；
# pm_engine 不反向依赖 admin_monitor，这里单独常量避免循环导入）。三源同表：
# 锁冲突退避耗尽 / 恢复闭环复查未通过 / 假就绪滞留——首句为锁冲突路径（历史主因），
# 后两句覆盖「锁冲突前提为假」的形态（2026-09-17 refactor-facade-delegation 事故：
# 该 spec 从未获得过 worktree 锁，依赖未满足等待定向唤醒）。
SIGNAL_RECOMMENDATION_DISPATCH_STALLED = (
    "先按 evidence 判来源：① 确为锁冲突（evidence 含 backoff schedule/锁冲突计数）→ "
    "检查持锁进程是否为孤儿（ps/pgrep 确认后 kill），清理残留 worktree 锁后让 spec "
    "重新派发；② 依赖未满足（evidence 含 dependencies not satisfied 或原因含依赖）→ "
    "无需处置，等待依赖转入接受态后事件定向唤醒自动派发；③ 恢复闭环复查未通过 → "
    "核查该 spec 卡死根因（run/进程/闸门）"
)

# ── 恢复闭环复查 / 假就绪巡检（improve-run-lifecycle-governance D6）──────────
# auto-recovery（含 defer）后登记观察项，followup_check_minutes 后复查该 spec
# 是否真实恢复推进；条目镜像到 .fenix/recovery_watch.json 供 daemon 重启续查。
RECOVERY_WATCH_FILE = "recovery_watch.json"
DEFAULT_FOLLOWUP_CHECK_MINUTES = 15
# 同 spec 同指纹的巡检/滞留信号冷却（分钟）：指纹未变且冷却期内只记日志
DEFAULT_SIGNAL_COOLDOWN_MINUTES = 30

# 恢复复查「已恢复推进」的后续态集合（post-recovery-patrol D4）：观察窗口
# 到达时 spec 已进入 ready 之后的这些状态之一 → 视为已真实恢复推进，关闭
# 观察项且不告警。implementing 不在其中——实施中的 spec 由「已有活跃派发」
# （worktree 持锁）覆盖；无活跃派发的 implementing 属卡死形态，应告警。
RECOVERY_PROGRESS_STATUSES = ("implemented", "testing", "verified", "done", "pushed")

# ── 过渡窗口豁免（evo-recovery-watch-transition-guard D1/D2）─────────────
# implementer 成功收工后：worktree 先清理（cleanup）→ merge-back 稍后完成，
# 窗口内 spec 状态仍为 implementing 且无活跃派发——recovery watch 若在此时
# 复查会把过渡窗口误判为 stale，dispatch_stalled 唤起无效 admin run
# （2026-09-12 21:13:57Z 复查误报事故：21:13:33 清理 → 21:14:02 merge，仅差
# 5 秒）。故判定 stale 前增加过渡窗口检查：存在归属该 spec 的待合并分支
# （pending merge，D1）或 succeed 痕迹落在缓冲窗口内（D2）时顺延本次判定。
# 缓冲秒数缺省 60：覆盖实测的 21:13:33→21:14:02（29s）窗口并留余量。
DEFAULT_TRANSITION_BUFFER_SECONDS = 60
# 待合并豁免上限（分钟，D1 有界性）：自「年龄起点」起算超过该值仍未合并
# 时回落既有 stale 判定，避免「分支永挂 → 永不告警」把真实卡死洗成健康。
# 缺省 5 分钟，且 MUST < followup_check_minutes（缺省 15），使回落可在
# 下一次复查即可观测（原「与缓冲同量级」在单位上自相矛盾，评审固化此值）。
DEFAULT_TRANSITION_GRACE_MINUTES = 5

# ── 升级前状态/运行痕迹复查（evo-recovery-watch-status-recheck）──────────
# 2026-09-17 16:33:58Z refactor-giant-classes 误报（admin store 信号 id
# `24ae002d605c`）：artifact-gate 不一致触发 runner 原地退避重试
# （transient_retry + superseded 终态补写，core/agent_runner/runner.py:2368/2384），
# 重试 run 开始输出（16:34:55Z，误报 56 秒后）前有约 4.3 分钟间隙；期间终态
# 流又被保留清理归档（16:33:38Z → 16:33:58Z 误报）——spec 状态/锁/流 mtime
# 与真卡死形态完全等价，故误升级。新增正向证据判据 + 有界顺延消除该形态：
# - **框架内重试在途**：该 spec 最近一次归属其自身的 impl 流末事件 ∈
#   {transient_retry, superseded} 且距该事件不超过 inflight_retry_minutes
#   → 顺延本次判定（保留观察项、推进 due），不升级；
# - **有界性**：自观察项首个 due 到期时刻（recheck_deadline）起累计顺延
#   不得超过 defer_limit_minutes（缺省 30），超限回落既有 stale 判定并升级，
#   MUST NOT 以「一直有重试痕迹」把真实卡死洗成健康。
DEFAULT_INFLIGHT_RETRY_MINUTES = 5
DEFAULT_DEFER_LIMIT_MINUTES = 30
# runner 原地退避重试留痕的末事件类型（transient_retry 写后紧跟 superseded
# 终态补写 = 本文件末行恒为终态，runner.py:1915/2472 恢复「终态后置」不变量）。
INFLIGHT_RETRY_EVENT_TYPES = ("transient_retry", "superseded")


def _read_last_nonempty_line(path, chunk_size: int = 65536) -> str:
    """只读文件末尾、返回最后一个非空行（避免全量读大 JSONL）。

    code-review item 40320e04d629 / 97a48d2814f1：run 流可达数 MB，仅需末行。
    从尾部读一块（默认 64 KiB）取其中最后一个非空行；若这**整个块**只有一个
    （可能是被截断的）行，则该行可能不完整——回退全量读以保证正确性（大流文件
    的末行远小于 64 KiB，故正常路径不回退）。
    """
    size = path.stat().st_size
    if size == 0:
        return ""
    with path.open("rb") as f:
        start = max(0, size - chunk_size)
        f.seek(start)
        raw = f.read()
    text = raw.decode("utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    # 尾部块正好从行首开始（start == 0）或块内存在位于末行**之前**的换行
    # （去掉尾换行后仍含 \n）→ 末行为完整行。超长末行（> chunk_size）独占
    # 整块时块内唯一的 \n 是其自身结尾符，判据不成立 → 回退全量读
    # （code-review item c731923c9b36：旧判据「块内含任意 \n」把超长末行
    # 自身的结尾符误当完整行证据，返回首部被截断的半行、json 解析必败，
    # 在途重试豁免对大输出 run 静默失效）。
    if start == 0 or b"\n" in raw.rstrip(b"\n"):
        return lines[-1]
    # 整个块是被截断的单行 → 回退全量读
    full = path.read_text(encoding="utf-8", errors="replace").splitlines()
    nonempty = [ln for ln in full if ln.strip()]
    return nonempty[-1] if nonempty else ""


def _parse_event_timestamp(ts):
    """事件时间戳 → epoch 秒；与 runner._parse_event_timestamp 同口径。

    code-review item fc528d7216ed：接受 epoch 数值与 ISO 字符串；ISO 的 ``Z``
    后缀归一为 ``+00:00``；naive（无时区）时间戳按 UTC 解释（框架全链 UTC，
    旧实现按**本地时区**解释会带来时区漂移）。不可解析返回 None。
    """
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return float(ts)
    s = str(ts).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        from datetime import timezone as _tz

        dt = dt.replace(tzinfo=_tz.utc)
    return dt.timestamp()


class RecoveryWatch:
    """恢复闭环复查注册组件（门面 PMEngine 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

        # 恢复闭环复查（improve-run-lifecycle-governance D6）：
        # {spec: {"fingerprint", "due", "registered_at", "reason"}}，镜像到
        # .fenix/recovery_watch.json，daemon 重启后续查。
        self._recovery_watch: dict = {}
        # 观察项读写互斥（code-review item 1fa5c6b99aad）：check_recovery_watch
        # 会被 daemon 主循环定时器（fenixd.py）与 PMEngine.check_blockers
        # （EventBus 扫描 / 初扫线程）并发调用，registration 点也会插入 dict；
        # 旧实现「pop + 整文件重写」非原子，两次交错的巡检会丢失或复活观察项。
        # 用可重入锁保护 dict 读改写 + 落盘（_save 内部亦加锁，见其实现）。
        self._watch_lock = threading.RLock()
        # 巡检信号指纹去重（D6）：{spec: (fingerprint, raised_at_monotonic)}
        self._signal_fingerprints: dict = {}

    def _recovery_watch_path(self) -> Path:
        return self._pm.project_root / ".fenix" / RECOVERY_WATCH_FILE

    def _load_recovery_watch(self) -> None:
        """重启后从 .fenix/recovery_watch.json 续查观察项（损坏/缺失按空兜底）。

        读取失败**不再静默**（code-review item 905fe4cac7b2）：文件存在但整份
        JSON 损坏时记 WARNING 并把损坏文件改名为 ``.corrupt`` 移开，避免下一次
        写入前一直读取坏文件、且丢失现场无从排查。缺失文件属正常首次启动，不
        记日志。
        """
        path = self._pm._recovery_watch_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            self._pm.logger.warning(
                "pm_engine",
                f"recovery_watch.json 读取失败（按空续查，损坏文件改名移开）: "
                f"{type(e).__name__}: {e}",
            )
            try:
                # 损坏现场带时间戳留存（code-review item f305d725e2b0）：固定
                # ``.corrupt`` 名会让下一次损坏覆盖上一次现场（循环损坏只剩
                # 最后一份，与「丢失现场无从排查」目标相悖）。时间戳 + 存在性
                # 退避保留历史备份；全部候选都建不出时按旧语义放弃改名。
                stamp = time.strftime("%Y%m%d-%H%M%S")
                corrupt = path.with_name(f"{path.name}.{stamp}.corrupt")
                seq = 0
                while corrupt.exists():
                    seq += 1
                    corrupt = path.with_name(f"{path.name}.{stamp}.{seq}.corrupt")
                path.replace(corrupt)
            except OSError:
                pass
            return
        if isinstance(data, dict):
            self._recovery_watch = {k: v for k, v in data.items() if isinstance(v, dict)}

    def _save_recovery_watch(self) -> None:
        """原子持久化观察项（tempfile + fsync + os.replace）。

        旧实现 ``path.write_text`` 原地截断后写：崩溃/SIGKILL/磁盘满发生在截断与
        落盘之间会留下半截（非法）JSON，配合上面的加载侧会**整份**丢弃观察项，
        使卡死 spec 在 daemon 重启后再不被复查/升级——正是本组件要防的故障
        （code-review item 905fe4cac7b2）。改用与 agent_runner / dashboard data
        同款的原子替换惯用法。
        """
        path = self._pm._recovery_watch_path()
        with self._watch_lock:
            self.__save_recovery_watch_locked(path)
            return

    def __save_recovery_watch_locked(self, path) -> None:
        tmp_path = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_str = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
            )
            tmp_path = Path(tmp_str)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(self._recovery_watch, ensure_ascii=False, indent=2))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_str, str(path))
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"Failed to persist recovery watch: {e}",
            )
            if tmp_path is not None:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass

    def register_recovery_watch(self, spec_name: str, reason: str) -> None:
        """登记恢复观察项：followup_check_minutes 后复查 spec 是否真实恢复推进。

        auto-recovery 与 recovery deferred（存活子进程仍在）都会登记——后者防止
        「defer → 下轮仍卡死 → 再 defer」无限循环（tasks 3.1）。
        """
        # 数值容错（code-review item 10fded66b995）：与本文件其它配置助手
        # （_followup_check_minutes 等）同款 try/except——畸形
        # pm.recovery.followup_check_minutes（非数值字符串）此前会让 float()
        # 抛 ValueError 逃出登记路径，中断 auto-recovery 收尾。
        try:
            minutes = float(
                self._pm._get_config(
                    "pm.recovery.followup_check_minutes", DEFAULT_FOLLOWUP_CHECK_MINUTES
                )
                or DEFAULT_FOLLOWUP_CHECK_MINUTES
            )
        except (TypeError, ValueError):
            minutes = float(DEFAULT_FOLLOWUP_CHECK_MINUTES)
        due = time.time() + max(0.5, minutes) * 60
        with self._watch_lock:
            self._register_watch_entry(spec_name, reason, minutes, due)
        return

    def _register_watch_entry(self, spec_name, reason, minutes, due) -> None:
        entry = self._pm.state_machine.read_one(spec_name) or {}
        self._recovery_watch[spec_name] = {
            "fingerprint": self._pm._spec_fingerprint(entry),
            "due": due,
            "registered_at": time.time(),
            # 顺延有界性起算点（recovery-watch-status-recheck D4）= 首个 due
            # 到期时刻。登记时固化（含 followup 钳制后实际 due），daemon 重启
            # 后续算不随当前配置漂移；旧格式观察项（升级前登记）由
            # _recheck_deadline 回退 registered_at + followup 计算。
            "recheck_deadline": due,
            "reason": reason,
            # 登记时的状态：复查通过条件 = 已离开该状态或已有活跃派发
            # （auto-recovery 登记时是 ready/implemented；defer 登记时是
            # implementing/testing 等卡死态——离开它才算恢复推进）。
            "status_at_register": entry.get("status"),
        }
        self._pm._save_recovery_watch()
        self._pm.logger.info(
            "pm_engine",
            f"Recovery watch registered for '{spec_name}' "
            f"(recheck in {minutes:.0f}m): {reason}",
        )

    def check_recovery_watch(self) -> list:
        """到期复查观察项（daemon 周期调用 + BLOCKER CHECK 内调用）。

        通过条件（post-recovery-patrol D4 收紧为声明语义，不再用「status 与
        登记时是否相同」判定）：

        - **已恢复推进**：spec 已进入 ready 之后的后续态
          （implemented/testing/verified/done/pushed），或已有活跃派发
          （worktree 在跑）→ 关闭观察项且不告警（既有行为）。
        - **尚未恢复推进**：spec 处于 ready 且无活跃派发（含「登记时
          implementing、窗口内回退 ready」真实形态）→ **先就地重新派发**
          （走与 spec_ready 事件同源的派发入口，经既有依赖/预算/内容完整性/
          冻结闸门）；派发成立 → 关闭观察项且不产生任何告警；派发未成立
          （被预算/内容完整性/依赖闸门拦下、冻结，或存在活跃派发）→ 关闭
          观察项并以 dispatch_stalled 信号唤起 Administrator 处置（既有兜底）。

        过渡窗口豁免（evo-recovery-watch-transition-guard D1/D2）：判定 stale
        前检查过渡窗口——该 spec 存在归属其实现分支的待合并提交（
        ``has_pending_merge``，D1）或 implementer 成功收工痕迹落在缓冲窗口
        内（D2 判据 (a)）时，**顺延**本次判定（保留观察项、推进 due），不升级
        为 dispatch_stalled。顺延落点（D2 顺延落点）：检查施加于 ``pop``
        **之前**（观察项弹出前已判定豁免 → 保留观察项、推进 due），MUST NOT
        以裸 ``continue`` 静默丢弃观察项（丢弃 = 真实卡死从此无人告警），
        MUST NOT 以「视为已恢复」关闭观察项。顺延推进量（D2 顺延推进量）：
        ``due`` 推进 ``transition_buffer_seconds``（缺省 60s，daemon 主循环
        每 60s 调用一次），且推进后 ``due`` MUST NOT 晚于待合并信号的 grace
        截止（起点 + ``transition_grace_minutes``，缺省 5min），否则有界性
        回落的告警会被推后到更晚复查。

        Returns: 本次发出的信号 spec 列表（审计/测试用）。
        """
        raised = []
        now = time.time()
        for spec_name, item in list(self._recovery_watch.items()):
            # due 字段类型守卫（code-review item a4b93d0d0bd7）：recovery_watch.json
            # 被手工编辑或部分损坏时（_load_recovery_watch 只过滤非 dict 条目，
            # 不校验字段类型）due 可为非数值字符串，裸 float() 抛 ValueError
            # 会中止整轮复查循环，本次到期观察项之后的条目全部漏看（升级信号
            # 静默丢失）。回退 0.0（立即到期）而非跳过：与上方 ``or 0`` 的缺失
            # 字段既有语义一致，且升级观察项宁可提前复查也不静默漏看——复查
            # 路径本身会 pop/顺延/升级闭环该条，提前到期无重入风险。
            try:
                due = float(item.get("due") or 0)
            except (TypeError, ValueError):
                due = 0.0
            if now < due:
                continue

            # ── 升级前复查第 1 层：pop 之前的顺延判据（D1/D2 + 重试在途）──
            # 顺延（recovery-watch-status-recheck 1.6 落点：pop 之前检查，
            # MUST NOT 以裸 continue 静默丢弃观察项）MUST 有界
            # （defer_limit_minutes，1.7）：自首个 due 到期时刻起累计顺延
            # 超限 → 回落既有 stale 判定并升级，不因「一直有重试痕迹」把
            # 真实卡死洗成健康。有界性门施加于全部顺延分支之前。
            defer_exhausted = self._defer_exhausted(item, now)
            if not defer_exhausted:
                # 过渡窗口豁免（D1/D2 既有）：该 spec 存在待合并分支（未并入
                # main 的提交）或 succeed 痕迹在缓冲窗内 → 顺延本次判定
                # （保留观察项、推进 due），MUST NOT 静默丢弃观察项或关闭它。
                deferred_due = self._transition_defer_due(spec_name, now)
                if deferred_due is not None:
                    # due 顺延读改写 + 落盘持锁（code-review item dbf6069ef584）：
                    # 本方法可从 daemon 定时器与 PMEngine.check_blockers 并发进入，
                    # 无锁 RMW 会让交错巡检覆盖对方刚推进的 due（重复派发）。
                    with self._watch_lock:
                        item["due"] = deferred_due
                        self._pm._save_recovery_watch()
                    self._pm.logger.info(
                        "pm_engine",
                        f"Recovery watch deferred for '{spec_name}' "
                        f"(transition window active, due={deferred_due:.0f})",
                    )
                    continue
                # 框架内重试在途（recovery-watch-status-recheck）：最近一次
                # 归属该 spec 的 impl 流末事件 ∈ {transient_retry, superseded}
                # 且距 now ≤ inflight_retry_minutes → 顺延本次判定（重试间隙
                # 形态：2026-09-17 16:33:58Z 误报，16:34:55Z 重试 run 开始
                # 输出——顺延让框架内推进先行，避免唤起无效 admin run）。
                retry_due = self._inflight_retry_defer_due(spec_name, now)
                if retry_due is not None:
                    # 同上：读改写 + 落盘整体持锁（code-review item dbf6069ef584）
                    with self._watch_lock:
                        item["due"] = retry_due
                        self._pm._save_recovery_watch()
                    self._pm.logger.info(
                        "pm_engine",
                        f"Recovery watch deferred for '{spec_name}' "
                        f"(in-flight retry active, due={retry_due:.0f})",
                    )
                    continue
            else:
                self._pm.logger.info(
                    "pm_engine",
                    f"Recovery watch defer limit reached for '{spec_name}' "
                    f"(cumulative defer > defer_limit_minutes), falling back "
                    f"to stale check",
                )

            # 读取先于 pop（code-review item 8af911fa12a3）：观察项此前在读取
            # STATE 之前就被 pop 并从磁盘移除，读取失败的 except 只记 WARNING
            # 后 continue——一次瞬态 STATE 读取失败会永久丢弃该观察项（丢失=
            # 真实卡死从此无人告警），与本文件「MUST NOT 静默丢弃观察项」不变量
            # 直接冲突（同族先例：_register_watch_entry/第 3 层重读均按失败
            # 保守处理）。现改为仅读取成功后才 pop；读取失败保留观察项并顺延
            # due（重试窗口沿用 inflight_retry_minutes 口径），下轮巡检重试。
            try:
                entry = self._pm.state_machine.read_one(spec_name)
            except Exception as e:
                # 有界性门（code-review item 78beed6b0814）：读取失败顺延分支
                # 原先不受 _defer_exhausted 约束——STATE 持续不可读（文件损坏/
                # 解析异常）时每轮重新把 due 推到 now + inflight_retry_minutes
                # 并 continue，观察项永远到不了下方升级，与上方「有界性门施加
                # 于全部顺延分支之前」矛盾（真实卡死从此无人告警）。本任轮
                # defer 已超限 → 不再顺延，升级 dispatch_stalled（evidence
                # 注明 STATE 不可读）；信号记录失败则保留观察项下轮重试，
                # 不静默丢弃。
                if defer_exhausted:
                    self._pm.logger.error(
                        "pm_engine",
                        f"Recovery watch read-failure defer limit reached for "
                        f"'{spec_name}' (STATE unreadable, cumulative defer > "
                        f"defer_limit_minutes), escalating dispatch_stalled",
                    )
                    evidence = (
                        f"auto-recovery/defer at {item.get('registered_at')} "
                        f"({item.get('reason')}); STATE unreadable: read_one "
                        f"kept failing past defer_limit_minutes so the watch "
                        f"could not re-check spec status — escalating instead "
                        f"of deferring indefinitely, "
                        f"last_read_error={type(e).__name__}: {str(e)[:120]}"
                    )
                    try:
                        self._pm._signal_dispatch_stalled(spec_name, evidence)
                    except Exception as signal_exc:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"dispatch_stalled escalation failed for "
                            f"'{spec_name}' (watch retained for retry): "
                            f"{type(signal_exc).__name__}: {signal_exc}",
                        )
                        continue
                    # 升级成功才关闭观察项（与既有升级路径「pop + 落盘持锁」
                    # 同款）；失败路径上方已保留观察项并 continue。
                    with self._watch_lock:
                        self._recovery_watch.pop(spec_name, None)
                        self._pm._save_recovery_watch()
                    raised.append(spec_name)
                    continue
                retry_due = now + self._inflight_retry_minutes() * 60
                with self._watch_lock:
                    item["due"] = retry_due
                    self._pm._save_recovery_watch()
                self._pm.logger.warning(
                    "pm_engine",
                    f"Recovery watch 复查读取 STATE 失败 '{spec_name}'"
                    f"（保留观察项，顺延 due={retry_due:.0f}）: "
                    f"{type(e).__name__}: {e}",
                )
                continue
            # pop + 落盘作为一个整体持锁（code-review item 1fa5c6b99aad）：两次
            # 交错巡检否则会把对方刚 pop 的项写回（复活）或丢失未落盘的变更。
            # 读取成功后才 pop（read_one 异常隔离，code-review item 3c7ed59e424d
            # 语义保持：单条失败仅跳过该条并记 WARNING，其余观察项继续）。
            with self._watch_lock:
                self._recovery_watch.pop(spec_name, None)
                self._pm._save_recovery_watch()
            if not entry:
                continue  # spec 已消失（被人工清理）：观察项静默关闭（2.4 不变）
            status = entry.get("status")
            # ── 升级前复查第 2 层：blocked（含 frozen）→ 关闭观察项、不升级 ──
            # blocked 由 admin_monitor._detect_blocked_stuck 通道
            # （core/admin_monitor.py:690）告警，recovery watch 重复升级属
            # 重复告警（2026-09-17 事故 16:37Z 双通道并存同一 spec）。frozen
            # blocked 的 status 仍为 blocked（frozen 标记在 error/FROZEN_FIELD），
            # 同一分支覆盖。观察项此处已 pop，直接 continue 即关闭。
            if status == "blocked":
                self._pm.logger.info(
                    "pm_engine",
                    f"Recovery watch closed for '{spec_name}' "
                    f"(status=blocked, delegated to blocked_stuck channel)",
                )
                continue
            active_dispatch = False
            try:
                active_dispatch = bool(
                    self._pm.agent_runner.worktree_manager.has_active_worktree(spec_name)
                )
            except Exception:
                active_dispatch = False
            # 2.1：已恢复推进 = 已进入 ready 之后的后续态，或已有活跃派发
            if status in RECOVERY_PROGRESS_STATUSES or active_dispatch:
                self._pm.logger.info(
                    "pm_engine",
                    f"Recovery watch passed for '{spec_name}' "
                    f"(status={status}, active_dispatch={active_dispatch})",
                )
                continue
            # 2.2/2.3：尚未恢复推进 → 先就地重新派发（仅 ready 且无活跃派发
            # 值得尝试；其余状态由各自事件路径接管，直接走信号兜底）。
            dispatched = False
            if status == "ready" and not active_dispatch:
                dispatched = self._redispatch_stalled_ready(spec_name)
            if dispatched:
                self._pm.logger.info(
                    "pm_engine",
                    f"Recovery watch redispatch for '{spec_name}' succeeded "
                    f"(in-place dispatch from ready, no alert)",
                )
                continue
            # ── 升级前复查第 3 层：升级前重读状态（design 缺口 3）──
            # 首次 read_one 的 status 一直用到升级；期间就地派发/闸门检查
            # 可能变更状态——升级前重读命中「已恢复推进」（进入 ready 之后的
            # 后续态或已有活跃派发）→ 不升级。blocked 豁免已由第 2 层按首次
            # read_one 判定（就地重派被内容闸门冻结 blocked 属「ready 滞留
            # 重派未成立」既有形态，仍升级——2.6/3fad3350 语义保持，见
            # _redispatch_stalled_ready docstring）。重读失败/异常 → 保守升级
            # （不因本机制漏报真滞留，不静默关闭）。
            try:
                fresh = self._pm.state_machine.read_one(spec_name) or {}
            except Exception:
                fresh = {}
            # 第 3 层「已有活跃派发」须**重新探测**（code-review item 838ada899c96）：
            # 旧实现复用 `active_dispatch`——它在上方计算，且控制流能到达此处
            # 意味着 2.1 已返回（`status ∈ RECOVERY_PROGRESS_STATUSES or
            # active_dispatch` 为假），故此处 `active_dispatch` 可证为 False，
            # `or active_dispatch` 恒假，docstring 声称的「升级前重读…已有活跃
            # 派发 → 不升级」实际从未执行。就地重派窗口内 worktree 可能已变活跃，
            # 故重读时一并重探，避免误升级。
            try:
                active_dispatch_now = bool(
                    self._pm.agent_runner.worktree_manager.has_active_worktree(spec_name)
                )
            except Exception:
                active_dispatch_now = False
            if fresh.get("status") in RECOVERY_PROGRESS_STATUSES or active_dispatch_now:
                self._pm.logger.info(
                    "pm_engine",
                    f"Recovery watch passed for '{spec_name}' (status now "
                    f"{fresh.get('status')}, active_dispatch={active_dispatch_now} "
                    f"before escalation, no alert)",
                )
                continue
            evidence = (
                f"auto-recovery/defer at {item.get('registered_at')} "
                f"({item.get('reason')}); spec still {fresh.get('status')} "
                f"with no active dispatch after followup window, in-place "
                f"redispatch "
                f"{'succeeded' if dispatched else 'not established'}, "
                f"error={str(fresh.get('error') or '')[:120]}"
            )
            self._pm.logger.error(
                "pm_engine",
                f"Recovery watch failed for '{spec_name}' — not recovered, "
                f"escalating dispatch_stalled",
            )
            try:
                self._pm._signal_dispatch_stalled(spec_name, evidence)
            except Exception as signal_exc:
                # 与读取失败分支（上方升级调用）同款守卫（code-review item
                # 96b3b5771561）：本观察项已在上方 pop 落盘，而
                # _signal_dispatch_stalled 的模块导入 / 裸 read_one /
                # get_admin_config 窄捕（仅 TypeError/ValueError）之外的异常
                # 仍可向上逃逸——不接住会中止整轮复查：本条观察项已丢失、
                # raised 未记录、其余到期观察项全部漏看。失败路径恢复观察项
                # （due 不变，下轮重试升级；setdefault 不覆盖并发窗口内的
                # 重新登记）后 continue，不中止整轮。
                with self._watch_lock:
                    self._recovery_watch.setdefault(spec_name, item)
                    self._pm._save_recovery_watch()
                self._pm.logger.warning(
                    "pm_engine",
                    f"dispatch_stalled escalation failed for "
                    f"'{spec_name}' (watch restored for retry): "
                    f"{type(signal_exc).__name__}: {signal_exc}",
                )
                continue
            raised.append(spec_name)
        return raised

    # ── 过渡窗口豁免（evo-recovery-watch-transition-guard D1/D2）────────────
    # implementer 成功收工后 → worktree 清理 → merge-back 完成的窗口内，spec
    # 状态仍为 implementing 且无活跃派发；此时复查会把过渡窗口误判为 stale，
    # dispatch_stalled 唤起无效 admin run（2026-09-12 21:13:57Z 事故：21:13:33
    # 清理 → 21:14:02 merge，仅差 5 秒）。判定 stale 前检查过渡窗口：存在
    # 归属该 spec 的待合并分支（D1）或 succeed 痕迹落在缓冲窗口内（D2）时
    # 顺延本次判定（保留观察项、推进 due），而不是关闭观察项或升级信号。

    def _transition_buffer_seconds(self) -> float:
        """过渡缓冲窗口（秒）：pm.recovery.transition_buffer_seconds（缺省 60）。

        覆盖实测的 21:13:33→21:14:02（29s）窗口并留余量（design D2 缓冲秒数
        固化）。daemon 主循环每 60s 调一次 check_recovery_watch（fenixd.py:483）
        ，顺延推进量直接复用此值，使下一次复查恰好落在窗口边界。
        """
        try:
            return max(
                0.0,
                float(
                    self._pm._get_config(
                        "pm.recovery.transition_buffer_seconds", DEFAULT_TRANSITION_BUFFER_SECONDS
                    )
                ),
            )
        except (TypeError, ValueError):
            return float(DEFAULT_TRANSITION_BUFFER_SECONDS)

    def _transition_grace_minutes(self) -> float:
        """待合并豁免上限（分钟）：pm.recovery.transition_grace_minutes（缺省 5）。

        不变量（D1 有界性）：grace MUST < followup_check_minutes（缺省 15），
        使「回落」在下一次复查即可观测。配置违反不变量（>= followup）时按
        followup 钳制（下沉到 followup - 1，下限 0——极端配置下直接不豁免，
        有界性优先，绝不把真实卡死洗成健康）。
        """
        try:
            grace = max(
                0.0,
                float(
                    self._pm._get_config(
                        "pm.recovery.transition_grace_minutes", DEFAULT_TRANSITION_GRACE_MINUTES
                    )
                ),
            )
        except (TypeError, ValueError):
            grace = float(DEFAULT_TRANSITION_GRACE_MINUTES)
        try:
            followup = max(
                0.0,
                float(
                    self._pm._get_config(
                        "pm.recovery.followup_check_minutes", DEFAULT_FOLLOWUP_CHECK_MINUTES
                    )
                ),
            )
        except (TypeError, ValueError):
            followup = float(DEFAULT_FOLLOWUP_CHECK_MINUTES)
        if grace >= followup:
            grace = max(0.0, followup - 1)
        return grace

    def _followup_check_minutes(self) -> float:
        """复查间隔（分钟）：pm.recovery.followup_check_minutes（缺省 15）。

        供顺延有界性起算（_recheck_deadline 旧格式回退）等复用；与
        register_recovery_watch / _transition_grace_minutes 同源读取。
        """
        try:
            return max(
                0.0,
                float(
                    self._pm._get_config(
                        "pm.recovery.followup_check_minutes", DEFAULT_FOLLOWUP_CHECK_MINUTES
                    )
                ),
            )
        except (TypeError, ValueError):
            return float(DEFAULT_FOLLOWUP_CHECK_MINUTES)

    def _defer_limit_minutes(self) -> float:
        """顺延累计上限（分钟）：pm.recovery.defer_limit_minutes（缺省 30）。

        不变量（recovery-watch-status-recheck 1.7）：defer_limit MUST >
        followup_check_minutes（缺省 15）——否则首个顺延窗口即可能越过上限。
        配置违反不变量（<= followup）时按 ``_transition_grace_minutes`` 同一
        钳制范式收敛（上浮到 followup + 1；上限只会更大不会失效，有界性
        优先，绝不把真实卡死洗成健康）。
        """
        try:
            defer = max(
                0.0,
                float(
                    self._pm._get_config(
                        "pm.recovery.defer_limit_minutes", DEFAULT_DEFER_LIMIT_MINUTES
                    )
                ),
            )
        except (TypeError, ValueError):
            defer = float(DEFAULT_DEFER_LIMIT_MINUTES)
        followup = self._followup_check_minutes()
        if defer <= followup:
            defer = followup + 1
        return defer

    def _inflight_retry_minutes(self) -> float:
        """框架内重试在途豁免窗口（分钟）：pm.recovery.inflight_retry_minutes（缺省 5）。

        不变量（recovery-watch-status-recheck 1.7）：inflight_retry MUST <
        defer_limit_minutes（缺省 30）——否则重试痕迹窗口可长于顺延上限，
        窗口内恒顺延把真实卡死洗成健康。配置违反不变量（>= defer_limit）时
        按 ``_transition_grace_minutes`` 同一钳制范式收敛（下沉到
        defer_limit - 1，下限 0——极端配置下直接不豁免，有界性优先）。
        """
        try:
            retry = max(
                0.0,
                float(
                    self._pm._get_config(
                        "pm.recovery.inflight_retry_minutes", DEFAULT_INFLIGHT_RETRY_MINUTES
                    )
                ),
            )
        except (TypeError, ValueError):
            retry = float(DEFAULT_INFLIGHT_RETRY_MINUTES)
        defer = self._defer_limit_minutes()
        if retry >= defer:
            retry = max(0.0, defer - 1)
        return retry

    def _recheck_deadline(self, item: dict) -> float:
        """观察项顺延累计起算点（绝对时间戳）。

        起算点 = 观察项首个 due 到期时刻（``registered_at + followup_check_minutes``）。
        登记时已固化 ``recheck_deadline`` 字段（含 followup 钳制后的实际 due），
        daemon 重启后续算不随当前配置漂移；旧格式观察项（本机制上线前登记）
        回退 ``registered_at + 当前 followup``，再回退 ``due``。
        """
        rd = item.get("recheck_deadline")
        if isinstance(rd, (int, float)) and rd > 0:
            return float(rd)
        registered = item.get("registered_at")
        if isinstance(registered, (int, float)) and registered > 0:
            return float(registered) + self._followup_check_minutes() * 60
        due = item.get("due")
        if isinstance(due, (int, float)) and due > 0:
            return float(due)
        return 0.0

    def _defer_exhausted(self, item: dict, now: float) -> bool:
        """顺延累计是否已达上限（recovery-watch-status-recheck 1.7 有界性）。

        自 ``_recheck_deadline``（首个 due 到期时刻）起累计顺延不得超过
        ``defer_limit_minutes``（缺省 30）；now 已越过该截止 → 回落既有 stale
        判定并升级——MUST NOT 以「一直有重试痕迹 / 长期活跃态」把真实卡死洗成
        健康。调用点：``check_recovery_watch`` 第 1 层，施加于全部顺延分支之前
        （读取失败顺延分支复用同一判定：超限不再顺延而是升级，evidence 注明
        STATE 不可读）。
        """
        return now >= self._recheck_deadline(item) + self._defer_limit_minutes() * 60

    def _inflight_retry_defer_due(self, spec_name: str, now: float):
        """框架内重试在途的顺延 due（绝对时间戳）；不在途返回 None。

        2026-09-17 误报形态（proposal Why）：artifact-gate 不一致触发 runner
        原地退避重试（``transient_retry`` + ``superseded`` 终态补写，
        runner.py:2368/2384），重试 run 开始输出（16:34:55Z，误报 56 秒后）
        前有分钟级间隙——期间 spec 状态/锁/流 mtime 与真卡死形态完全等价。
        末事件 ∈ {``transient_retry``, ``superseded``} 且距 now 不超过
        ``inflight_retry_minutes``（缺省 5）→ 判「框架内重试在途」顺延本次判定
        （保留观察项、推进 due），不升级。

        顺延推进量 = ``now + transition_buffer_seconds``（与过渡窗口顺延同一
        推进量，daemon 每 60s 复查一次，下一次复查恰好落在窗口边界）。有界性
        由调用方（check_recovery_watch 第 1 层）在顺延分支前统一施加
        （``defer_limit_minutes``）。

        返回 None 的保守方向：流不可读 / 末事件解析失败 / 末事件非重试标记 /
        已超窗口 → 不豁免（设计「无正向证据 → 维持既有升级」，不把真实卡死
        洗成健康）。

        Returns: 顺延后的绝对 due（float）；不在途返回 None。
        """
        event = self._spec_recent_impl_stream_last_event(spec_name)
        if event is None:
            return None
        etype, event_ts = event
        if etype not in INFLIGHT_RETRY_EVENT_TYPES:
            return None
        retry_window = self._inflight_retry_minutes() * 60
        if now - event_ts > retry_window:
            return None
        return now + self._transition_buffer_seconds()

    def _latest_impl_stream(self, spec_name: str):
        """该 spec 最近一次 impl 流文件（顶层 + archive/ 中 mtime 最新），或 None。

        检索口径（recovery-watch-status-recheck 1.3）：`.fenix/runs` 顶层 +
        `.fenix/runs/archive/`——终态 run 会在告警前被保留清理归档
        （2026-09-17 16:33:38Z 归档、16:33:58Z 误报，只查顶层即漏判最后一条
        活性痕迹；归档含检先例 engine.py:798 `get_runs(..., include_archive=True)`）。

        归属精确（D2 判据 (a) 归属须精确）：MUST NOT 仅凭
        ``f"impl-{spec_name}-*.jsonl"`` glob 命中即算活动——spec 名互为前缀会
        误命中他 spec 的运行流（spec ``a-b`` 命中 ``impl-a-b-c-<ts>.jsonl``，
        凭空制造「近期活动」→ 豁免真 stale）；须对 glob 命中的每个候选再用
        ``run_spec_part``（core/agent_runner/run_files.py 既有单一来源解析器，
        与 dashboard 读侧同口径，不另造）解析出完整 spec 名精确比较。
        """
        from core.agent_runner.run_files import run_spec_part

        runs_dir = self._pm.project_root / ".fenix" / "runs"
        latest = None  # (mtime, Path)
        for base in (runs_dir, runs_dir / "archive"):
            if not base.is_dir():
                continue
            try:
                for p in base.glob(f"impl-{spec_name}-*.jsonl"):
                    if run_spec_part(p.stem) != spec_name:
                        continue  # 精确归属守卫：他 spec 的前缀命中全部排除
                    try:
                        mtime = p.stat().st_mtime
                    except OSError:
                        continue
                    if latest is None or mtime > latest[0]:
                        latest = (mtime, p)
            except OSError:
                continue
        return latest[1] if latest else None

    def _spec_recent_impl_stream_mtime(self, spec_name: str):
        """该 spec 最近一次 impl run 流的 mtime（D2 判据 (a) 事实源），或 None。

        implementer 成功收工的可见痕迹：STATE 的 ``branch``/``implementer_run``
        只在 merge-back 成功之后才写（dispatch.py:1042-1045），过渡窗口内恒为
        null；而 impl run 流 ``.fenix/runs/impl-<spec>-<ts>.jsonl`` 在 run
        生命周期内持续写入，其 mtime 是过渡窗口可复用的可观测源（与
        ``engine._spec_has_recent_run_activity`` 同源代理，engine.py:1956）。

        检索口径（recovery-watch-status-recheck 1.3）：顶层 + archive/
        均由 ``_latest_impl_stream`` 覆盖；归属精确性（前缀歧义守卫）亦在其中
        实施，见其 docstring。

        Returns: 最新 impl 流的 mtime（float）；无流/目录缺失/io 失败返回 None。
        """
        stream = self._latest_impl_stream(spec_name)
        if stream is None:
            return None
        try:
            return stream.stat().st_mtime
        except OSError:
            return None

    def _spec_recent_impl_stream_last_event(self, spec_name: str):
        """该 spec 最近一次归属自身 impl 流的末事件，或 None。

        末事件 = JSONL 最后一行 ``type`` 字段（runner.py 原地退避重试留痕：
        ``transient_retry`` 写后紧跟 ``superseded`` 终态补写 = 本文件末行恒为
        终态，runner.py:1915/2472「终态后置」不变量）；时间取事件
        ``timestamp``（UTC ISO）解析为 epoch。最近 = ``_latest_impl_stream``
        （mtime 最新，顶层 + archive/）。

        异常/损坏/不可读/字段缺失一律返回 None——保守不豁免（宁可多报 stale，
        不把真实卡死洗成健康；design「重读失败保守升级」）。

        Returns: (type, timestamp_epoch) 元组；不可得返回 None。
        """
        stream = self._latest_impl_stream(spec_name)
        if stream is None:
            return None
        # 只读文件末尾一行（code-review item 40320e04d629 / 97a48d2814f1）：run 流
        # 累积全部 stdout/stderr 行可达数 MB，而本方法每 60s tick 对每个到期观察项
        # 调用一次，旧实现全量 read_text + splitlines 是 O(文件大小) 重复开销。
        # 从尾部读一块（64 KiB）取最后一个非空行即可；不足则回退全量读。
        try:
            last_line = _read_last_nonempty_line(stream)
        except OSError:
            return None
        if not last_line:
            return None
        try:
            last = json.loads(last_line)
        except (json.JSONDecodeError, ValueError):
            return None
        etype = last.get("type")
        ts = last.get("timestamp")
        if not etype or not ts:
            return None
        try:
            # Z 后缀与 epoch 数值容错（code-review item fc528d7216ed）：与
            # runner._parse_event_timestamp 同口径——旧实现 datetime.fromisoformat
            # 遇 'Z' 后缀抛 ValueError → 返回 None → 在途重试顺延静默失效
            # （正是本机制要防的误升级形态）。naive 时间戳按 UTC 解释（框架全链 UTC）。
            event_ts = _parse_event_timestamp(ts)
        except (ValueError, TypeError):
            return None
        if event_ts is None:
            return None
        return (etype, float(event_ts))

    def _transition_defer_due(self, spec_name: str, now: float):
        """过渡窗口内的顺延 due（绝对时间戳）；不在过渡窗口返回 None。

        由 check_recovery_watch 在 ``pop`` **之前**调用（D2 顺延落点）：命中时
        保留观察项并推进 due，MUST NOT 静默丢弃观察项（丢失 = 真实卡死从此
        无人告警）或视为已恢复关闭。双重判据，任一命中即顺延：

        - **D2 判据 (a)（succeed 缓冲窗口）**：该 spec 最近 impl run 流 mtime
          落在 ``transition_buffer_seconds``（缺省 60）内——implementer 成功
          收工痕迹。窗口自限（60s 后 mtime 越过窗口自然过期），无额外上限。
        - **D1 待合并信号**：``worktree_manager.has_pending_merge(spec) is True``
          （归属该 spec 的实现分支存在未并入 main 的提交）。受**有界性**约束：
          年龄起点 = max(分支最新未合并提交时间 [``pending_merge_since``],
          succeed 痕迹时间)——超过 ``transition_grace_minutes``（缺省 5）仍未
          合并时回落（返回 None），避免「分支永挂 → 永不告警」（缺省 81 条约
          48 个 spec 的存量未并入分支不致洗成健康）。

        调用点严格判定（D2 mock 替身回归）：``has_pending_merge`` 用 ``is True``、
        ``pending_merge_since`` 用 ``isinstance(ts, (int, float))``——既有
        recovery-watch 夹具的 ``worktree_manager`` 为 MagicMock
        （``bool(MagicMock()) is True``），裸真值 / ``is not None`` 会把替身
        误判为待合并、误豁免而转红既有用例。

        顺延推进量（D2 顺延推进量）：``now + buffer_seconds``（缺省 60s，
        与 daemon 每 60s 复查一次对齐），且 MUST NOT 晚于待合并信号的 grace
        截止（年龄起点 + ``transition_grace_minutes``）——否则有界性回落的
        告警被推后到更晚复查、甚至越过下一次复查才可观测。

        Returns: 顺延后的绝对 due（float）；不在过渡窗口返回 None（走既有
        stale 判定）。
        """
        buffer_seconds = self._transition_buffer_seconds()
        grace_minutes = self._transition_grace_minutes()
        succeed_ts = self._spec_recent_impl_stream_mtime(spec_name)

        # ── D2 判据 (a)：succeed 痕迹在缓冲窗口内 → 顺延（窗口自限，无 grace）──
        if succeed_ts is not None and (now - succeed_ts) <= buffer_seconds:
            return now + buffer_seconds

        # ── D1 待合并信号（严格判定，mock 替身回归）──
        pending = False
        pending_since = None
        try:
            wm = self._pm.agent_runner.worktree_manager
            if (
                getattr(wm, "has_pending_merge", None) is not None
                and wm.has_pending_merge(spec_name) is True
            ):
                pending = True
                raw_since = wm.pending_merge_since(spec_name)
                if isinstance(raw_since, (int, float)):
                    pending_since = float(raw_since)
        except Exception:
            pending = False
        if not pending:
            return None
        if pending_since is None:
            # has_pending_merge 为真而年龄不可度量（异常替身组合）：无法兑现
            # 有界性（D1），保守不豁免（宁可多报 stale，不把真实卡死洗成健康）。
            return None
        # 年龄起点 = max(分支最新未合并提交时间, succeed 痕迹时间)（D1 年龄起点）
        age_start = pending_since
        if succeed_ts is not None and succeed_ts > age_start:
            age_start = succeed_ts
        grace_cutoff = age_start + grace_minutes * 60
        if now >= grace_cutoff:
            return None  # 年龄超过 grace → 回落既有 stale 判定（1.4 有界性）
        deferred = now + buffer_seconds
        return min(deferred, grace_cutoff)

    def _redispatch_stalled_ready(self, spec_name: str) -> bool:
        """就地重新派发滞留 ready 的 spec（post-recovery-patrol D4/2.2/2.3）。

        走与 ``spec_ready`` 事件**同源**的派发入口 ``_on_spec_ready``，复用既有
        依赖（``_dependencies_satisfied``，同一接受态集合）/预算/内容完整性
        闸门——不另立判据（D2）。返回派发是否成立：
        - 成立（成功入队）→ 关闭观察项且不告警；
        - 未成立（被预算/内容完整性/依赖闸门拦下、冻结）→ 由调用方以
          dispatch_stalled 信号唤起 Administrator（不静默关闭）。

        异常一律捕获降级 WARNING 返回 False（fail-closed：不误判成立）。
        """
        try:
            # 冻结态（frozen 标记或 blocked+冻结 error）不可派发 → 未成立
            if self._pm._frozen_state(self._pm.state_machine.read_one(spec_name) or {}):
                self._pm.logger.info(
                    "pm_engine",
                    f"In-place redispatch skipped for '{spec_name}': frozen",
                )
                return False
            # 预算闸门（发前判定，复用既有 _check_impl_budget_exhausted）
            if self._pm._check_impl_budget_exhausted(spec_name):
                self._pm.logger.info(
                    "pm_engine",
                    f"In-place redispatch skipped for '{spec_name}': " f"impl budget exhausted",
                )
                return False
            # 内容完整性闸门（发前判定，复用既有 _check_spec_content_missing）
            if self._pm._check_spec_content_missing(spec_name):
                self._pm.logger.info(
                    "pm_engine",
                    f"In-place redispatch skipped for '{spec_name}': " f"spec content missing",
                )
                return False
            # 依赖闸门（复用既有 _dependencies_satisfied，同一接受态集合）
            if not self._pm._dependencies_satisfied(spec_name):
                self._pm.logger.info(
                    "pm_engine",
                    f"In-place redispatch skipped for '{spec_name}': "
                    f"dependencies not satisfied",
                )
                return False
            # 与 spec_ready 同源的派发入口：冷却/去重/优先级/并发等其余闸门
            # 在 _on_spec_ready 内生效；返回 True 即成功入队（派发成立）。
            ok = bool(self._pm._on_spec_ready(spec_name))
            if not ok:
                return False
            # 入队后立即处理队列，使就地派发当轮完成（对齐唤起后立即处理
            # 队列的既有模式）；队列处理失败由 full_scan 周期兜底。
            try:
                self._pm._process_queue()
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine",
                    f"In-place redispatch queue process failed '{spec_name}' "
                    f"（非阻塞，full_scan 兜底）: {e}",
                )
            return True
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"In-place redispatch failed for '{spec_name}': " f"{type(e).__name__}: {e}",
            )
            return False

    @staticmethod
    def _spec_fingerprint(entry: dict) -> str:
        """spec 状态指纹 = hash(status + error 摘要)（D6 信号去重依据）。"""
        basis = f"{entry.get('status')}|{str(entry.get('error') or '')[:120]}"
        return hashlib.sha1(basis.encode("utf-8", "replace")).hexdigest()[:12]

    def _signal_dispatch_stalled(
        self, spec_name: str, evidence: str, fingerprint: str | None = None
    ) -> None:
        """退避耗尽仍持锁 / 恢复复查未通过 / 假就绪滞留 → dispatch_stalled 信号（D5/D6）。

        写入 admin store（kind=SIGNAL, severity major），由 AdminMonitor 摄取唤起
        Administrator。双重去重避免反复拉起：
          - 指纹去重（D6）：同 spec 同一状态指纹在
            ``pm.recovery.signal_cooldown_minutes``（默认 30）内只记日志；
            指纹变化或冷却结束方可再次写入。
          - admin_alerts 去重：store 内冷却期内已有同类信号时同样抑制。
        """
        from core.admin_store import AdminStore, SIGNAL

        entry = self._pm.state_machine.read_one(spec_name) or {}
        fp = fingerprint or self._pm._spec_fingerprint(entry)
        # 取值容错（code-review item c31eb4352989）：裸 float 在畸形
        # pm.recovery.signal_cooldown_minutes（非数值字符串）时抛 ValueError
        # 逃出 check_recovery_watch 循环，静默跳过其余到期观察项的升级；
        # `or DEFAULT_` 只兜 None/0，兜不住非法字符串。与本文件下方
        # get_admin_config 取值同款 try/except 回落权威缺省。
        try:
            cooldown = (
                float(
                    self._pm._get_config(
                        "pm.recovery.signal_cooldown_minutes", DEFAULT_SIGNAL_COOLDOWN_MINUTES
                    )
                    or DEFAULT_SIGNAL_COOLDOWN_MINUTES
                )
                * 60
            )
        except (TypeError, ValueError):
            cooldown = DEFAULT_SIGNAL_COOLDOWN_MINUTES * 60
        # 指纹冷却 check-then-act 持锁（code-review item dbf6069ef584）：
        # check_recovery_watch 并发进入时，两线程可同时通过下方指纹检查并各自
        # 写 admin store（重复信号）。与 _recovery_watch 同一把可重入锁序列化
        # 「查指纹 + 记指纹」，判定与记录不再交错。
        with self._watch_lock:
            prev = self._signal_fingerprints.get(spec_name)
            now = time.time()
            suppressed = bool(prev and prev[0] == fp and (now - prev[1]) < cooldown)
            if not suppressed:
                self._signal_fingerprints[spec_name] = (fp, now)
        if suppressed:
            self._pm.logger.info(
                "pm_engine",
                f"dispatch_stalled for '{spec_name}' suppressed (same fingerprint "
                f"{fp} within {int(cooldown / 60)}m cooldown) — logged only",
            )
            return

        # 同源路径（family.py bug_repair_mode 先例）：get_admin_config 缺省填充，
        # 旁路 _get_config + 硬编码 fallback 会与权威缺省漂移（缺省现为 60 分钟）。
        # 取值容错（code-review item b9df0f065a8d）：直接下标 + 裸 float 在缺键
        # （自定义/部分配置）或非数值时抛 KeyError/ValueError，而本方法在
        # check_recovery_watch 循环内被调用——异常会中止整轮复查、静默丢弃其余
        # 到期条目的升级。改用 .get + try/except 回落权威缺省。
        from core.config import ConfigLoader

        try:
            store_cooldown = float(
                ConfigLoader.get_admin_config(self._pm.config).get(
                    "escalation_cooldown_minutes"
                )
            )
        except (TypeError, ValueError):
            store_cooldown = 60.0
        if not store_cooldown or store_cooldown <= 0:
            store_cooldown = 60.0
        store = AdminStore(self._pm.project_root, self._pm.logger)
        try:
            if store.latest_signal(spec_name, "dispatch_stalled", store_cooldown) is not None:
                self._pm.logger.info(
                    "pm_engine",
                    f"dispatch_stalled for '{spec_name}' suppressed "
                    f"(cooldown {store_cooldown:.0f}m)",
                )
                return
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"dispatch_stalled dedup check failed '{spec_name}' (proceeding): {e}",
            )
        try:
            store.append(
                {
                    "kind": SIGNAL,
                    "signal_type": "dispatch_stalled",
                    "spec": spec_name,
                    "severity": "major",
                    # 文案中性化（2026-09-17）：本信号有三条来源（派发锁冲突退避
                    # 耗尽 / 恢复闭环复查未通过 / 假就绪滞留），固定述为「锁冲突 +
                    # 退避耗尽」只对第一条成立——2026-09-17 refactor-facade-delegation
                    # 事故里该 spec 从未获得过 worktree 锁（依赖未满足，等待定向唤醒），
                    # 信号文案却把 Administrator 引向「清理残留 worktree 锁」这一无关
                    # 方向。处置方向由 evidence 给出（各调用点自带现场），描述只陈述
                    # 共性事实，不再断言单一根因。
                    "description": (f"'{spec_name}' 长期滞留 ready 且派发未成立（处置方向见 evidence）"),
                    "evidence": evidence,
                    "recommended_action": SIGNAL_RECOMMENDATION_DISPATCH_STALLED,
                }
            )
            self._pm.logger.warning(
                "pm_engine",
                f"dispatch_stalled signal recorded for '{spec_name}'",
            )
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"Failed to record dispatch_stalled for '{spec_name}': {e}",
            )

    def _clear_dispatch_conflict(self, spec_name: str) -> dict:
        """派发成功后清零锁冲突计数与退避窗口（返回 update 字段供合并写入）。"""
        return {
            "_lock_conflict_count": 0,
            "_dispatch_backoff_until": None,
            "_last_lock_conflict_at": None,
        }
