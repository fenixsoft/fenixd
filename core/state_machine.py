"""
state_machine.py — SPEC lifecycle state machine and STATE.md I/O.

Manages the finite state machine for SPECs:
  drafted → ready → implementing → implemented → testing → verified → done → pushed
                                                       ↘ bug-found → implementing

Handles atomic reads/writes of STATE.md with file locking.
"""

import fcntl
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ── State definitions ──────────────────────────────────────────────

class SpecStatus:
    DRAFTED = "drafted"
    READY = "ready"
    IMPLEMENTING = "implementing"
    IMPLEMENTED = "implemented"
    TESTING = "testing"
    VERIFIED = "verified"
    BUG_FOUND = "bug-found"
    BLOCKED = "blocked"
    DONE = "done"
    PUSHED = "pushed"

    ALL = [
        DRAFTED, READY, IMPLEMENTING, IMPLEMENTED,
        TESTING, VERIFIED, BUG_FOUND, BLOCKED, DONE, PUSHED,
    ]


# 人工冻结标记（fix-restart-dual-dispatch S4）：结构化字段替代 error 文本契约。
# 此前 admin 巡检豁免靠 error 文本匹配（frozen: 前缀/「用户指令」子串），文案
# 漂移即失效（「人工冻结（…）」实测绕过豁免 → admin 每 15 分钟空探一次烧 token）。
# 冻结 = update_spec 写 {"frozen": True, "status": BLOCKED, "error": 前缀+原因}；
# 冻结期间所有自动链路对 status 的改写在 update_spec 内被剥离（82 个调用点
# 一次性收口），诊断字段（error/_retry_count 等）照写不丢上下文。
FROZEN_FIELD = "frozen"
FREEZE_ERROR_PREFIX = "用户指令冻结："


# Valid state transitions: from → [to, ...]
VALID_TRANSITIONS: Dict[str, List[str]] = {
    SpecStatus.DRAFTED:      [SpecStatus.READY],
    SpecStatus.READY:        [SpecStatus.IMPLEMENTING],
    SpecStatus.IMPLEMENTING: [SpecStatus.IMPLEMENTED, SpecStatus.READY, SpecStatus.BLOCKED],  # ready=retry, blocked=熔断
    SpecStatus.IMPLEMENTED:  [SpecStatus.TESTING],
    SpecStatus.TESTING:      [SpecStatus.VERIFIED, SpecStatus.BUG_FOUND],
    SpecStatus.BUG_FOUND:    [SpecStatus.IMPLEMENTING, SpecStatus.IMPLEMENTED],  # implemented=fix 完成后重新验证
    SpecStatus.BLOCKED:      [SpecStatus.READY],  # 人工确认后恢复
    SpecStatus.VERIFIED:     [SpecStatus.DONE],
    SpecStatus.DONE:         [SpecStatus.PUSHED],
    SpecStatus.PUSHED:       [],  # terminal state
}

# 门禁自动路径额外允许的「逃生门」转换（verifier-judgment-integrity D7）：
# VERIFIED→TESTING 仅允许由 _on_spec_verified 门禁拦截触发的自动回退调用，
# 人工路径（直接调 transition）仍受 VALID_TRANSITIONS 约束被拒，不得绕过。
# 回退保留 implementer_run 与既有 progress 断点。
GATE_TRANSITIONS: Dict[str, List[str]] = {
    SpecStatus.VERIFIED: [SpecStatus.TESTING],
}

# States that are considered "interrupted" on daemon restart (revert to ready)
INTERRUPTED_STATES = {SpecStatus.IMPLEMENTING, SpecStatus.TESTING}

# ── 实现尝试预算计数（fix-budget-counting-semantics D2）──────────────
# 字段名单点定义（pm_engine 与 state_machine 共用，避免两处漂移）：
# - _impl_run_budget_used：当前 spec 已累计启动的实现 run 次数
# - _budget_exempt_runs：死亡 run 豁免侧车计数（豁免不占预算，仅审计/告警）
# - _exempt_alerted：豁免阈值告警幂等标记（一次性，防重复告警）
IMPL_RUN_BUDGET_USED_FIELD = "_impl_run_budget_used"
BUDGET_EXEMPT_RUNS_FIELD = "_budget_exempt_runs"
BUDGET_EXEMPT_ALERTED_FIELD = "_exempt_alerted"


# ── STATE.md Parser ─────────────────────────────────────────────────

class StateParser:
    """Parse and serialize STATE.md entries."""

    @staticmethod
    def parse(state_path: Path) -> Dict[str, dict]:
        """
        Parse STATE.md and return {spec_name: entry_dict}.

        Expected entry format:
        ### <spec-name>
        - status: <value>
        - priority: <integer>
        - created: <ISO 8601>
        - updated: <ISO 8601>
        - implementer_run: <run-id or null>
        - tester_run: <run-id or null>
        - branch: <branch-name or null>
        - error: <error-message or null>
        """
        if not state_path.exists():
            return {}

        content = state_path.read_text(encoding="utf-8")
        return StateParser._parse_content(content)

    @staticmethod
    def _parse_content(content: str) -> Dict[str, dict]:
        """Parse content string into spec entries."""
        specs = {}
        current_name = None
        current_entry = {}

        for line in content.split("\n"):
            # Skip HTML comment blocks
            if line.strip().startswith("<!--"):
                continue
            if line.strip().endswith("-->"):
                continue

            # Match ### <spec-name>
            header_match = re.match(r"^###\s+(.+)$", line)
            if header_match:
                if current_name and current_entry:
                    if "status" in current_entry:
                        # Only accept entries with valid status values
                        if current_entry["status"] in SpecStatus.ALL:
                            specs[current_name] = current_entry
                current_name = header_match.group(1).strip()
                current_entry = {}
                continue

            # Match - key: value（键名允许小写字母/下划线/数字，支持 _token_warn_80
            # 等带数字的内部字段；原有键名均不含数字，放宽不影响既有解析）
            kv_match = re.match(r"^-\s+([a-z_][a-z0-9_]*):\s*(.*)$", line)
            if kv_match and current_name:
                key = kv_match.group(1)
                value = kv_match.group(2).strip()

                # Type coercion
                if key in ("priority",):
                    try:
                        value = int(value)
                    except ValueError:
                        value = 999
                elif key in (FROZEN_FIELD, "_recovery_resume"):
                    # 布尔字段显式转换：字符串 "False" 也是 truthy，不转会把
                    # 解冻后的 spec 永久误判为冻结（fix-restart-dual-dispatch S4）；
                    # _recovery_resume（interrupt-recovery-preserve）同型处理。
                    value = value.lower() in ("true", "1", "yes")
                elif key in ("implementer_run", "tester_run", "branch", "error",
                             "total_duration"):
                    if value.lower() in ("null", "none", ""):
                        value = None

                current_entry[key] = value

        # Don't forget the last entry
        if current_name and current_entry and "status" in current_entry:
            if current_entry["status"] in SpecStatus.ALL:
                specs[current_name] = current_entry

        return specs

    @staticmethod
    def serialize(specs: Dict[str, dict]) -> str:
        """Serialize spec entries back into STATE.md format."""
        lines = [
            "# Fenix Project State",
            "# ====================",
            "# Auto-generated by fenixd. Records all SPECs and their current status.",
            f"# Last updated: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Specs",
            "",
        ]

        # Sort by priority then created time
        sorted_specs = sorted(
            specs.items(),
            key=lambda item: (
                item[1].get("priority", 999),
                item[1].get("created", ""),
            ),
        )

        for name, entry in sorted_specs:
            lines.append(f"### {name}")
            for key in ["status", "priority", "created", "updated",
                         "implementer_run", "tester_run", "branch", "error",
                         "depends_on", "total_duration", FROZEN_FIELD]:
                val = entry.get(key, "null")
                if val is None:
                    val = "null"
                lines.append(f"- {key}: {val}")
            # 追加内部状态字段（_ 前缀，如 _retry_count/_merge_fp/_merge_streak），
            # 使其跨 daemon 重启持久化（fix-fenix-token-waste：熔断计数依赖它）
            for key, val in entry.items():
                if key.startswith("_") and key != "updated":
                    if val is None:
                        val = "null"
                    lines.append(f"- {key}: {val}")
            lines.append("")

        return "\n".join(lines)


# ── State Machine ───────────────────────────────────────────────────

class _NullLogger:
    """静默日志器：logger 为 None 时兜底，避免各方法无条件调用 self.logger 崩溃。

    适用于脚本直接构造 StateMachine（如 spec 流程）且不需要日志的场景。
    """

    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class StateMachine:
    """
    Manages the lifecycle state machine for all SPECs.
    Provides atomic read/write access to STATE.md.
    """

    def __init__(self, state_path: Path, logger=None):
        self.state_path = Path(state_path)
        # logger 允许为 None（脚本场景）：兜底为静默日志器，保证 add_spec/transition 等
        # 方法内无条件 self.logger.* 调用不崩溃
        self.logger = logger if logger is not None else _NullLogger()
        self._lockfile = Path(str(state_path) + ".lock")
        # 状态文件与 .STATE.md.lock 均在 state_path.parent 下打开；状态文件迁入
        # .fenix/ 后父目录不再恒存在（项目根），构造时确保之（新项目首写路径）
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Read / Write ───────────────────────────────────────────────

    def read_all(self) -> Dict[str, dict]:
        """Read all SPEC entries from STATE.md.

        防御层（fix-dispatch-orphan D3）：解析结果必须被规范化为
        ``{name: dict}``。若解析产物混入非 dict 条目（并发撕裂写入、
        外部工具改写 STATE.md、或未来解析路径回归），跳过该条目并记
        warning，绝不使其进入返回值——否则下游 ``entry.get("status")``
        会抛 ``AttributeError``/``TypeError``（事故家族
        ``string indices must be integers``），整轮 full_scan 静默中止。
        """
        raw = StateParser.parse(self.state_path)
        return self._normalize_entries(raw)

    @staticmethod
    def _normalize_entries(raw: Dict[str, dict]) -> Dict[str, dict]:
        """过滤非 dict 条目，保证返回值的每个条目都是 dict。

        不修改合法条目的任何字段，仅把非法条目（字符串/列表/None 等）
        剔除并记日志。返回新 dict，不改动入参。
        """
        normalized: Dict[str, dict] = {}
        for name, entry in raw.items():
            if isinstance(entry, dict):
                normalized[name] = entry
                continue
            # 非法条目：不得进入返回值，记 warning（用全局静默日志器兜底，
            # 避免 logger 为 None 时崩溃——见 _NullLogger）。
            _NullLogger().warning(
                "state_machine",
                f"跳过非法条目 '{name}'：期望 dict，实际为 "
                f"{type(entry).__name__}，已忽略以防扫描崩溃",
            )
        return normalized

    def read_one(self, spec_name: str) -> Optional[dict]:
        """Read a single SPEC entry."""
        all_specs = self.read_all()
        return all_specs.get(spec_name)

    def write_all(self, specs: Dict[str, dict]):
        """Atomically write all SPEC entries to STATE.md with file locking.

        Thread-safe: each call uses a unique temp file (pid + tid + counter),
        and the final STATE.md write is serialized by flock on a lock file.
        """
        # Serialize the final rename via flock on a dedicated lock file.
        # 注意：调用方若已持有该锁（如 _bump_counter），必须走 _write_all_locked，
        # 否则同进程二次 flock 会自阻塞死锁。
        lock_path = self.state_path.parent / ".STATE.md.lock"
        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                self._write_all_locked(specs)
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

    def _write_all_locked(self, specs: Dict[str, dict]):
        """write_all 的锁内实现（temp 写盘 + rename），不加锁。

        供已持有 .STATE.md.lock 的调用方（_bump_counter）复用；write_all 是
        本方法 + flock 的组合。flock 按打开文件描述符生效，同进程对同一文件
        的第二个 fd 再 flock 会阻塞，故锁内不得再走 write_all。
        """
        import threading

        content = StateParser.serialize(specs)
        parent = self.state_path.parent

        # Use per-thread unique temp name to avoid threads clobbering each other
        tid = threading.get_ident()
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            prefix=f".STATE.md.{os.getpid()}.{tid}.",
            suffix=".tmp",
            dir=str(parent),
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.rename(str(tmp_path), str(self.state_path))
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    # ── 预算计数原子原语（fix-budget-counting-semantics D2）──────────

    def _bump_counter(self, spec_name: str, field: str, delta: int) -> int:
        """文件锁内原子读改写计数器字段并回读校验。

        消除「读 STATE → 改 → 写回」非原子序列在并发（恢复扫描 × 派发）下
        丢失增量的竞态（interaction-contract 复盘：used=2/4 连续出现两次）。
        锁内完成 读→改→写→回读校验；回读不匹配时重试一次并记审计日志。
        结果下限 0（delta=-1 时不会把计数打成负数）。

        Returns: 最终生效值；spec 不存在时记 warning 并返回 0。
        """
        lock_path = self.state_path.parent / ".STATE.md.lock"
        verify = 0
        for attempt in (1, 2):
            with open(lock_path, "w") as lock_f:
                fcntl.flock(lock_f, fcntl.LOCK_EX)
                try:
                    specs = self.read_all()
                    if spec_name not in specs:
                        self.logger.warning(
                            "state_machine",
                            f"bump {field} failed: SPEC not found: {spec_name}",
                        )
                        return 0
                    try:
                        current = int(specs[spec_name].get(field, 0) or 0)
                    except (TypeError, ValueError):
                        current = 0
                    new_value = max(0, current + delta)
                    specs[spec_name][field] = new_value
                    specs[spec_name]["updated"] = datetime.now(timezone.utc).isoformat()
                    self._write_all_locked(specs)
                    # 回读校验：确认增量真正落盘（防并发写覆盖丢增量）
                    verify = int(
                        (self.read_all().get(spec_name) or {}).get(field, 0) or 0
                    )
                finally:
                    fcntl.flock(lock_f, fcntl.LOCK_UN)
            if verify == new_value:
                return new_value
            self.logger.warning(
                "state_machine",
                f"bump {field} verify mismatch for '{spec_name}' "
                f"(attempt {attempt}): wrote {new_value}, read back {verify} — "
                f"并发写覆盖，已重试",
            )
        # 重试后仍不匹配：返回磁盘实际值（以落盘为准），由调用方审计
        return verify

    def bump_impl_budget(self, spec_name: str, delta: int) -> int:
        """实现尝试预算计数原子增减（``_impl_run_budget_used``）。

        启动计数（delta=+1）与死亡豁免（delta=-1，下限 0）统一走本函数。

        Returns: 递增/回退后的使用次数（跨重启持久化）。
        """
        return self._bump_counter(spec_name, IMPL_RUN_BUDGET_USED_FIELD, delta)

    def bump_budget_exempt_runs(self, spec_name: str) -> int:
        """死亡豁免侧车计数原子递增（``_budget_exempt_runs``）。

        Returns: 递增后的豁免次数。
        """
        return self._bump_counter(spec_name, BUDGET_EXEMPT_RUNS_FIELD, 1)

    def update_spec(self, spec_name: str, updates: dict) -> bool:
        """Update a single SPEC's fields atomically. Returns True if updated."""
        specs = self.read_all()
        if spec_name not in specs:
            self.logger.warning("state_machine", f"SPEC not found: {spec_name}")
            return False

        # 人工冻结保护（fix-restart-dual-dispatch S4）：frozen spec 的自动 status
        # 改写一律剥离——dispatch Retry/恢复路径实测会把人工冻结覆盖回 ready。
        # 更新自带 frozen 键视为冻结/解冻操作本身，原样放行。
        entry = specs[spec_name]
        updates = dict(updates)
        if entry.get(FROZEN_FIELD) and FROZEN_FIELD not in updates \
                and "status" in updates:
            stripped = updates.pop("status")
            self.logger.warning(
                "state_machine",
                f"Frozen SPEC '{spec_name}': status update '{stripped}' "
                f"stripped — manual freeze intact, unfreeze via "
                f"unfreeze_spec() to resume",
            )

        # Apply updates
        specs[spec_name].update(updates)
        specs[spec_name]["updated"] = datetime.now(timezone.utc).isoformat()
        self.write_all(specs)
        self.logger.info(
            "state_machine",
            f"Updated SPEC '{spec_name}'",
            {"updates": {k: v for k, v in updates.items() if k != "updated"}},
        )
        return True

    def freeze_spec(self, spec_name: str, reason: str = "") -> bool:
        """人工冻结 spec（fix-restart-dual-dispatch S4 的统一入口）。

        写入 blocked + 结构化 frozen 标记 + 规范前缀 error。error 保留「用户指令」
        子串，与既有文本契约豁免（admin_monitor）双保险兼容。冻结期间自动链路
        （重派/恢复/Retry/admin 唤起）全部失效，唯一出路是 unfreeze_spec。
        """
        error = f"{FREEZE_ERROR_PREFIX}{reason}" if reason else FREEZE_ERROR_PREFIX.rstrip("：:")
        return self.update_spec(spec_name, {
            "status": SpecStatus.BLOCKED,
            FROZEN_FIELD: True,
            "error": error,
        })

    def unfreeze_spec(self, spec_name: str, status: str = None) -> bool:
        """解除人工冻结。status 给定时同时恢复到该状态（绕过冻结保护）。"""
        updates: dict = {FROZEN_FIELD: False}
        if status is not None:
            updates["status"] = status
        return self.update_spec(spec_name, updates)

    def add_spec(self, spec_name: str, entry: dict) -> bool:
        """Add a new SPEC entry. Returns False if already exists."""
        specs = self.read_all()
        if spec_name in specs:
            self.logger.warning("state_machine", f"SPEC already exists: {spec_name}")
            return False

        entry.setdefault("status", SpecStatus.DRAFTED)
        entry.setdefault("priority", 5)
        entry.setdefault("created", datetime.now(timezone.utc).isoformat())
        entry.setdefault("updated", datetime.now(timezone.utc).isoformat())
        entry.setdefault("implementer_run", None)
        entry.setdefault("tester_run", None)
        entry.setdefault("branch", None)
        entry.setdefault("error", None)
        entry.setdefault("depends_on", None)

        specs[spec_name] = entry
        self.write_all(specs)
        self.logger.info("state_machine", f"Added SPEC '{spec_name}'", {"status": entry["status"]})
        return True

    def remove_spec(self, spec_name: str) -> bool:
        """Remove a SPEC entry atomically. Returns True if removed, False if absent.

        Mutates only the in-memory dict then atomically writes back, so a
        concurrent writer cannot resurrect the entry. Used by soft-delete
        (add-spec-priority-and-delete-api): the caller is responsible for
        moving the spec.s directory into spec/archive beforehand/afterward
        and keeping the two operations consistent.
        """
        specs = self.read_all()
        if spec_name not in specs:
            self.logger.warning("state_machine", f"Cannot remove nonexistent SPEC: {spec_name}")
            return False

        specs.pop(spec_name)
        self.write_all(specs)
        self.logger.info("state_machine", f"Removed SPEC '{spec_name}'")
        return True

    # ── State Transitions ──────────────────────────────────────────

    def transition(self, spec_name: str, new_status: str) -> bool:
        """Transition a SPEC to a new status. Validates the transition is legal."""
        spec = self.read_one(spec_name)
        if not spec:
            self.logger.warning("state_machine", f"Cannot transition nonexistent SPEC: {spec_name}")
            return False

        old_status = spec.get("status", SpecStatus.DRAFTED)

        # Validate transition
        if new_status not in VALID_TRANSITIONS.get(old_status, []):
            self.logger.error(
                "state_machine",
                f"Invalid transition: {spec_name} {old_status} → {new_status}",
            )
            return False

        self.logger.info(
            "state_machine",
            f"Transition: {spec_name} {old_status} → {new_status}",
        )
        return self.update_spec(spec_name, {"status": new_status})

    def is_valid_transition(self, from_status: str, to_status: str) -> bool:
        """Check if a transition is legal."""
        return to_status in VALID_TRANSITIONS.get(from_status, [])

    def transition_gate(self, spec_name: str, new_status: str) -> bool:
        """门禁自动路径专用转换（verifier-judgment-integrity D7 逃生门）。

        仅允许 GATE_TRANSITIONS 中声明的转换（当前：VERIFIED→TESTING），
        用于 _on_spec_verified 门禁拦截后的自动回退。人工路径（直接调
        transition）受 VALID_TRANSITIONS 约束，VERIFIED→TESTING 仍被拒，
        不得绕过。返回 False 表示非门禁允许的转换或 spec 不存在。
        """
        spec = self.read_one(spec_name)
        if not spec:
            self.logger.warning("state_machine", f"Cannot gate-transition nonexistent SPEC: {spec_name}")
            return False

        old_status = spec.get("status", SpecStatus.DRAFTED)
        if new_status not in GATE_TRANSITIONS.get(old_status, []):
            self.logger.error(
                "state_machine",
                f"Invalid gate transition: {spec_name} {old_status} → {new_status}",
            )
            return False

        self.logger.info(
            "state_machine",
            f"Gate transition: {spec_name} {old_status} → {new_status}",
        )
        return self.update_spec(spec_name, {"status": new_status})

    # ── Query ──────────────────────────────────────────────────────

    def get_by_status(self, status: str) -> List[Tuple[str, dict]]:
        """Get all SPECs with the given status, sorted by priority."""
        all_specs = self.read_all()
        matching = [
            (name, entry)
            for name, entry in all_specs.items()
            if entry.get("status") == status
        ]
        return self._sort_by_priority(matching)

    def get_ready_specs(self) -> List[Tuple[str, dict]]:
        """Get all ready SPECs sorted by priority."""
        return self.get_by_status(SpecStatus.READY)

    def get_next_ready(self) -> Optional[Tuple[str, dict]]:
        """Get the highest-priority ready SPEC."""
        ready = self.get_ready_specs()
        return ready[0] if ready else None

    def get_pending_verification(self) -> List[Tuple[str, dict]]:
        """Get all SPECs awaiting verification, sorted by priority."""
        return self.get_by_status(SpecStatus.IMPLEMENTED)

    def _sort_by_priority(self, specs: List[Tuple[str, dict]]) -> List[Tuple[str, dict]]:
        """Sort by priority (lower = higher priority), then by created time."""
        return sorted(
            specs,
            key=lambda item: (
                item[1].get("priority", 999),
                item[1].get("created", "z"),
            ),
        )

    # ── Recovery ───────────────────────────────────────────────────

    def recover_interrupted(self, project_root=None, worktree_manager=None) -> List[str]:
        """
        On daemon restart, revert any SPECs stuck in interrupted states.
        Uses update_spec directly (bypasses transition validation for recovery).
        Returns list of recovered SPEC names.

        恢复目标按中断态区分（2026-09-04 help-center 误派实证）：
        - implementing（实现中断）→ ready 重派 implementer。interrupt-recovery-
          preserve（D4）改判定：分支存在且相对 main 有未合并提交 → 保留
          branch/implementer_run + ``_recovery_resume`` 标记，按 resume 续做
          （dispatch 层在保留分支上续做而非从零重派）；仅零提交/分支缺失才走
          现行清空路径（逐字节兼容）。project_root/worktree_manager 缺省时行为
          与旧版完全一致（脚本/测试场景零变化）。
        - testing（验证中断）→ implemented 重派 verifier——实现已合并/落分支，
          重置 ready 会误派 implementer 从头实现已合并代码并劫持 branch 字段
          （pushed 记录被写成 rogue 分支）；配合场景冻结复用，重验代价极小。
        """
        recovered = []
        for status in INTERRUPTED_STATES:
            specs = self.get_by_status(status)
            for name, entry in specs:
                self.logger.warning(
                    "state_machine",
                    f"Recovering interrupted SPEC: {name} (was {status})",
                )
                if status == SpecStatus.TESTING:
                    # 清 tester_run 让验证流水线全新重入；branch/implementer_run
                    # 保留（实现的身份事实，验证不重做实现）
                    self.update_spec(name, {
                        "status": SpecStatus.IMPLEMENTED,
                        "error": f"Recovered from interrupted state: {status}",
                        "tester_run": None,
                        "_retry_count": 0,
                        "_merge_fp": None,
                        "_merge_streak": 0,
                    })
                    recovered.append(name)
                    continue
                # ── 中断恢复保留续做（interrupt-recovery-preserve D4）──
                # 有提交分支 → 保留 branch/implementer_run 并按 resume 续做；
                # 三态载体处置（在场/重建/降级）经 worktree_manager 单源查询
                #（is_available）。零提交/分支缺失/载体不可用 → 现行清空路径。
                preserved = self._recovery_preserve_spec(
                    name, entry, project_root, worktree_manager)
                if preserved:
                    recovered.append(name)
                    continue
                # 清空陈旧的 run 字段，否则 full_scan 的恢复派发会因
                # implementer_run 非空而跳过重新调度（fix-fenix-token-waste）
                self.update_spec(name, {
                    "status": SpecStatus.READY,
                    "error": f"Recovered from interrupted state: {status}",
                    "implementer_run": None,
                    "tester_run": None,
                    "branch": None,
                    "_retry_count": 0,
                    "_merge_fp": None,
                    "_merge_streak": 0,
                })
                recovered.append(name)
        return recovered

    def _recovery_preserve_spec(self, name: str, entry: dict,
                                project_root=None, worktree_manager=None) -> bool:
        """实现中断的恢复保留判定与三态载体处置（interrupt-recovery-preserve D4/D5）。

        判定：branch 在册、分支可解析、且 ``git rev-parse main..branch`` 非空
        （相对 main 有未合并提交）→ 保留。载体处置经 worktree_manager 三态
        单源查询（is_available）：在场原地登记（受清理豁免）；缺失在既有分支
        上重建 worktree；不可用降级清空重建并 WARNING。

        Returns: True 表示已保留并写入恢复续做标记（调用方计入 recovered）。
        """
        if project_root is None or worktree_manager is None:
            return False
        branch = entry.get("branch")
        if not branch:
            return False
        try:
            # 分支可解析 + 相对 main 有未合并提交（rev-list --count > 0）。
            # 分支不存在时 rev-list 非零退出 → 走现行清空路径。
            ahead = subprocess.run(
                ["git", "-C", str(project_root), "rev-list", "--count",
                 f"main..{branch}"],
                capture_output=True, text=True, timeout=15,
            )
            if ahead.returncode != 0:
                return False
            try:
                ahead_commits = int(ahead.stdout.strip() or "0")
            except ValueError:
                return False
            if ahead_commits <= 0:
                return False
        except (subprocess.TimeoutExpired, OSError):
            return False
        # 三态载体处置：在场原地 / 缺失重建 / 不可用降级
        wt, resolved_branch = worktree_manager.resolve_resume_site(name, branch)
        if wt is None:
            self.logger.warning(
                "state_machine",
                f"Recovery preserve unavailable for '{name}': branch '{branch}' "
                f"无可用载体（三态判定失败）——降级清空重建",
            )
            return False
        self.logger.warning(
            "state_machine",
            f"Recovering interrupted SPEC '{name}' with preserved branch "
            f"'{resolved_branch}' (ahead of main) — resume continuation, "
            f"worktree={wt}",
        )
        self.update_spec(name, {
            "status": SpecStatus.READY,
            "error": f"Recovered from interrupted state: implementing "
                     f"(resume preserved branch)",
            "implementer_run": entry.get("implementer_run"),
            "tester_run": None,
            "branch": resolved_branch,
            # dispatch 层据此识别「恢复续做」路径：在保留分支的 worktree 内
            # resume（claude --resume + 继承注记），而非从零新建分支。
            "_recovery_resume": True,
            "_retry_count": 0,
            "_merge_fp": None,
            "_merge_streak": 0,
        })
        return True
