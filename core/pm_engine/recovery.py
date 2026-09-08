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

        通过条件（spec Scenario）：spec 已离开 ready 或已有活跃派发（worktree
        在跑）→ 关闭观察项且不告警；否则触发 dispatch_stalled 信号唤起
        Administrator，并关闭观察项（后续由巡检指纹冷却与处置接管）。

        Returns: 本次发出的信号 spec 列表（审计/测试用）。
        """
        raised = []
        now = time.time()
        for spec_name, item in list(self._recovery_watch.items()):
            if now < float(item.get("due") or 0):
                continue
            self._recovery_watch.pop(spec_name, None)
            self._pm._save_recovery_watch()
            entry = self._pm.state_machine.read_one(spec_name)
            if not entry:
                continue  # spec 已消失（被人工清理）：观察项静默关闭
            status = entry.get("status")
            active_dispatch = False
            try:
                active_dispatch = bool(
                    self._pm.agent_runner.worktree_manager.has_active_worktree(spec_name))
            except Exception:
                active_dispatch = False
            if status != item.get("status_at_register") or active_dispatch:
                self._pm.logger.info(
                    "pm_engine",
                    f"Recovery watch passed for '{spec_name}' "
                    f"(status={status}, active_dispatch={active_dispatch})",
                )
                continue
            evidence = (
                f"auto-recovery/defer at {item.get('registered_at')} "
                f"({item.get('reason')}); spec still ready with no active dispatch "
                f"after followup window, status={status}, "
                f"error={str(entry.get('error') or '')[:120]}"
            )
            self._pm.logger.error(
                "pm_engine",
                f"Recovery watch failed for '{spec_name}' — still stalled in ready, "
                f"escalating dispatch_stalled",
            )
            self._pm._signal_dispatch_stalled(spec_name, evidence)
            raised.append(spec_name)
        return raised


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
