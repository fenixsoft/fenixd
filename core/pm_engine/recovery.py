"""recovery.py — RecoveryWatch：恢复闭环复查注册/复查/持久化与 dispatch_stalled 信号上报（refactor-core-packages 阶段 6）。

SPEC 状态经门面回引 self._pm.state_machine（design D3 规则 3）；
组件内非自有状态/方法的 self.X 一律改写为 self._pm.X，保住门面
实例上的测试补丁缝与跨组件调用路径。

"""

from pathlib import Path
import hashlib
import json
import time


# dispatch_stalled 信号的建议处置（与 admin_monitor.SIGNAL_RECOMMENDATION 同义；
# pm_engine 不反向依赖 admin_monitor，这里单独常量避免循环导入）
SIGNAL_RECOMMENDATION_DISPATCH_STALLED = (
    "检查持锁进程是否为孤儿（ps/pgrep 确认后 kill），清理残留 worktree 锁后让 spec 重新派发"
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
#（worktree 持锁）覆盖；无活跃派发的 implementing 属卡死形态，应告警。
RECOVERY_PROGRESS_STATUSES = ("implemented", "testing", "verified", "done", "pushed")

# ── 过渡窗口豁免（evo-recovery-watch-transition-guard D1/D2）─────────────
# implementer 成功收工后：worktree 先清理（cleanup）→ merge-back 稍后完成，
# 窗口内 spec 状态仍为 implementing 且无活跃派发——recovery watch 若在此时
# 复查会把过渡窗口误判为 stale，dispatch_stalled 唤起无效 admin run
# （2026-09-12 21:13:57Z 复查误报事故：21:13:33 清理 → 21:14:02 merge，仅差
# 5 秒）。故判定 stale 前增加过渡窗口检查：存在归属该 spec 的待合并分支
#（pending merge，D1）或 succeed 痕迹落在缓冲窗口内（D2）时顺延本次判定。
# 缓冲秒数缺省 60：覆盖实测的 21:13:33→21:14:02（29s）窗口并留余量。
DEFAULT_TRANSITION_BUFFER_SECONDS = 60
# 待合并豁免上限（分钟，D1 有界性）：自「年龄起点」起算超过该值仍未合并
# 时回落既有 stale 判定，避免「分支永挂 → 永不告警」把真实卡死洗成健康。
# 缺省 5 分钟，且 MUST < followup_check_minutes（缺省 15），使回落可在
# 下一次复查即可观测（原「与缓冲同量级」在单位上自相矛盾，评审固化此值）。
DEFAULT_TRANSITION_GRACE_MINUTES = 5


class RecoveryWatch:
    """恢复闭环复查注册组件（门面 PMEngine 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

        # 恢复闭环复查（improve-run-lifecycle-governance D6）：
        # {spec: {"fingerprint", "due", "registered_at", "reason"}}，镜像到
        # .fenix/recovery_watch.json，daemon 重启后续查。
        self._recovery_watch: dict = {}
        # 巡检信号指纹去重（D6）：{spec: (fingerprint, raised_at_monotonic)}
        self._signal_fingerprints: dict = {}

    def _recovery_watch_path(self) -> Path:
        return self._pm.project_root / ".fenix" / RECOVERY_WATCH_FILE


    def _load_recovery_watch(self) -> None:
        """重启后从 .fenix/recovery_watch.json 续查观察项（损坏/缺失按空兜底）。"""
        try:
            data = json.loads(self._pm._recovery_watch_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict):
            self._recovery_watch = {
                k: v for k, v in data.items() if isinstance(v, dict)
            }


    def _save_recovery_watch(self) -> None:
        try:
            path = self._pm._recovery_watch_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self._recovery_watch, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine", f"Failed to persist recovery watch: {e}",
            )


    def register_recovery_watch(self, spec_name: str, reason: str) -> None:
        """登记恢复观察项：followup_check_minutes 后复查 spec 是否真实恢复推进。

        auto-recovery 与 recovery deferred（存活子进程仍在）都会登记——后者防止
        「defer → 下轮仍卡死 → 再 defer」无限循环（tasks 3.1）。
        """
        minutes = float(self._pm._get_config(
            "pm.recovery.followup_check_minutes", DEFAULT_FOLLOWUP_CHECK_MINUTES) or
            DEFAULT_FOLLOWUP_CHECK_MINUTES)
        entry = self._pm.state_machine.read_one(spec_name) or {}
        self._recovery_watch[spec_name] = {
            "fingerprint": self._pm._spec_fingerprint(entry),
            "due": time.time() + max(0.5, minutes) * 60,
            "registered_at": time.time(),
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
            if now < float(item.get("due") or 0):
                continue

            # ── 过渡窗口豁免（D1/D2 顺延落点：pop 之前检查）──
            # 该 spec 存在待合并分支（未并入 main 的提交）或 succeed 痕迹
            # 在缓冲窗内 → 顺延本次判定（保留观察项、推进 due），
            # MUST NOT 静默丢弃观察项或关闭它。
            deferred_due = self._transition_defer_due(spec_name, now)
            if deferred_due is not None:
                item["due"] = deferred_due
                self._pm._save_recovery_watch()
                self._pm.logger.info(
                    "pm_engine",
                    f"Recovery watch deferred for '{spec_name}' "
                    f"(transition window active, due={deferred_due:.0f})",
                )
                continue

            self._recovery_watch.pop(spec_name, None)
            self._pm._save_recovery_watch()
            entry = self._pm.state_machine.read_one(spec_name)
            if not entry:
                continue  # spec 已消失（被人工清理）：观察项静默关闭（2.4 不变）
            status = entry.get("status")
            active_dispatch = False
            try:
                active_dispatch = bool(
                    self._pm.agent_runner.worktree_manager.has_active_worktree(spec_name))
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
            evidence = (
                f"auto-recovery/defer at {item.get('registered_at')} "
                f"({item.get('reason')}); spec still {status} with no active "
                f"dispatch after followup window, in-place redispatch "
                f"{'succeeded' if dispatched else 'not established'}, "
                f"error={str(entry.get('error') or '')[:120]}"
            )
            self._pm.logger.error(
                "pm_engine",
                f"Recovery watch failed for '{spec_name}' — not recovered, "
                f"escalating dispatch_stalled",
            )
            self._pm._signal_dispatch_stalled(spec_name, evidence)
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
            return max(0.0, float(self._pm._get_config(
                "pm.recovery.transition_buffer_seconds",
                DEFAULT_TRANSITION_BUFFER_SECONDS)))
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
            grace = max(0.0, float(self._pm._get_config(
                "pm.recovery.transition_grace_minutes",
                DEFAULT_TRANSITION_GRACE_MINUTES)))
        except (TypeError, ValueError):
            grace = float(DEFAULT_TRANSITION_GRACE_MINUTES)
        try:
            followup = max(0.0, float(self._pm._get_config(
                "pm.recovery.followup_check_minutes",
                DEFAULT_FOLLOWUP_CHECK_MINUTES)))
        except (TypeError, ValueError):
            followup = float(DEFAULT_FOLLOWUP_CHECK_MINUTES)
        if grace >= followup:
            grace = max(0.0, followup - 1)
        return grace

    def _spec_recent_impl_stream_mtime(self, spec_name: str):
        """该 spec 最近一次 impl run 流的 mtime（D2 判据 (a) 事实源），或 None。

        implementer 成功收工的可见痕迹：STATE 的 ``branch``/``implementer_run``
        只在 merge-back 成功之后才写（dispatch.py:1042-1045），过渡窗口内恒为
        null；而 impl run 流 ``.fenix/runs/impl-<spec>-<ts>.jsonl`` 在 run
        生命周期内持续写入，其 mtime 是过渡窗口可复用的可观测源（与
        ``engine._spec_has_recent_run_activity`` 同源代理，engine.py:1956）。

        归属精确（D2 判据 (a) 归属须精确）：MUST NOT 仅凭
        ``f"impl-{spec_name}-*.jsonl"`` glob 命中即算活动——spec 名互为前缀会
        误命中他 spec 的运行流（spec ``a-b`` 命中 ``impl-a-b-c-<ts>.jsonl``，
        凭空制造「近期活动」→ 豁免真 stale）；须对 glob 命中的每个候选再用
        ``run_spec_part``（core/agent_runner/run_files.py 既有单一来源解析器，
        与 dashboard 读侧同口径，不另造）解析出完整 spec 名精确比较。

        Returns: 最新 impl 流的 mtime（float）；无流/目录缺失/io 失败返回 None。
        """
        from core.agent_runner.run_files import run_spec_part
        runs_dir = self._pm.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return None
        latest = None
        try:
            for p in runs_dir.glob(f"impl-{spec_name}-*.jsonl"):
                if run_spec_part(p.stem) != spec_name:
                    continue  # 精确归属守卫：他 spec 的前缀命中全部排除
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    continue
                if latest is None or mtime > latest:
                    latest = mtime
        except OSError:
            return None
        return latest

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
            if getattr(wm, "has_pending_merge", None) is not None \
                    and wm.has_pending_merge(spec_name) is True:
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
            if self._pm._frozen_state(
                    self._pm.state_machine.read_one(spec_name) or {}):
                self._pm.logger.info(
                    "pm_engine",
                    f"In-place redispatch skipped for '{spec_name}': frozen",
                )
                return False
            # 预算闸门（发前判定，复用既有 _check_impl_budget_exhausted）
            if self._pm._check_impl_budget_exhausted(spec_name):
                self._pm.logger.info(
                    "pm_engine",
                    f"In-place redispatch skipped for '{spec_name}': "
                    f"impl budget exhausted",
                )
                return False
            # 内容完整性闸门（发前判定，复用既有 _check_spec_content_missing）
            if self._pm._check_spec_content_missing(spec_name):
                self._pm.logger.info(
                    "pm_engine",
                    f"In-place redispatch skipped for '{spec_name}': "
                    f"spec content missing",
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
                f"In-place redispatch failed for '{spec_name}': "
                f"{type(e).__name__}: {e}",
            )
            return False


    @staticmethod
    def _spec_fingerprint(entry: dict) -> str:
        """spec 状态指纹 = hash(status + error 摘要)（D6 信号去重依据）。"""
        basis = f"{entry.get('status')}|{str(entry.get('error') or '')[:120]}"
        return hashlib.sha1(basis.encode("utf-8", "replace")).hexdigest()[:12]


    def _signal_dispatch_stalled(self, spec_name: str, evidence: str,
                                 fingerprint: str | None = None) -> None:
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
        cooldown = float(self._pm._get_config(
            "pm.recovery.signal_cooldown_minutes", DEFAULT_SIGNAL_COOLDOWN_MINUTES) or
            DEFAULT_SIGNAL_COOLDOWN_MINUTES) * 60
        prev = self._signal_fingerprints.get(spec_name)
        now = time.time()
        if prev and prev[0] == fp and (now - prev[1]) < cooldown:
            self._pm.logger.info(
                "pm_engine",
                f"dispatch_stalled for '{spec_name}' suppressed (same fingerprint "
                f"{fp} within {int(cooldown / 60)}m cooldown) — logged only",
            )
            return
        self._signal_fingerprints[spec_name] = (fp, now)

        # 同源路径（family.py bug_repair_mode 先例）：get_admin_config 缺省填充，
        # 旁路 _get_config + 硬编码 fallback 会与权威缺省漂移（缺省现为 60 分钟）
        from core.config import ConfigLoader
        store_cooldown = float(ConfigLoader.get_admin_config(
            self._pm.config)["escalation_cooldown_minutes"])
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
            store.append({
                "kind": SIGNAL,
                "signal_type": "dispatch_stalled",
                "spec": spec_name,
                "severity": "major",
                "description": (
                    f"'{spec_name}' 派发长期被 worktree 锁冲突滞留，"
                    f"退避计划耗尽仍未获得锁"
                ),
                "evidence": evidence,
                "recommended_action": SIGNAL_RECOMMENDATION_DISPATCH_STALLED,
            })
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
