"""
pm_engine.py — Project Management Engine for fenixd.

Handles SPEC auto-review, Agent scheduling, priority management,
concurrency control, daily reporting, and the single human gate (push approval).
"""

import hashlib
import json
import re
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class PMEngine:
    """
    Project Management Engine — the brain of fenixd.

    Responsibilities:
      - Auto-promote drafted → ready
      - Schedule implementer for ready SPECs
      - Schedule verifier for implemented SPECs
      - Handle bug-found → create fix SPECs
      - Enforce concurrency limits
      - Generate project reports
      - Manage the push approval gate
      - Periodic blocker detection and health reporting
    """

    def __init__(self, state_machine, agent_runner, config: dict,
                 project_root: Path, logger):
        self.state_machine = state_machine
        self.agent_runner = agent_runner
        self.config = config
        self.project_root = project_root
        self.logger = logger

        self._active_runs = 0
        self._run_queue = []  # Pending (priority, spec_name, agent_type) tuples
        self._active_priorities = set()  # 当前活动 priority 集合（宽松优先级下可含多个档）
        self._active_priority_counts: Dict[int, int] = {}  # priority → 活动 run 数
        self._handling_events = set()  # 防重入：正在处理的 (event_kind, spec_name)
        self._queue_lock = threading.Lock()  # 保护 _run_queue / _active_runs / _active_priorities

        # Blocker detection state
        self._last_blocker_check = None
        self._last_blocker_report_time = None

    # ── Event Handlers ─────────────────────────────────────────────

    def handle_event(self, event_kind: str, spec_name: str, spec_entry: dict):
        """
        Handle an internal event from the EventBus.
        This is the main scheduling entry point.
        """
        # 防重入：同一 (event, spec) 正在处理中则跳过，打破 event bus 二次派发回路
        event_key = (event_kind, spec_name)
        if event_key in self._handling_events:
            self.logger.debug(
                "pm_engine",
                f"Skipping duplicate event: {event_kind} for '{spec_name}'",
            )
            return
        self._handling_events.add(event_key)

        try:
            self.logger.info(
                "pm_engine",
                f"Handling event: {event_kind} for '{spec_name}'",
            )

            handlers = {
                "spec_drafted": self._on_spec_drafted,
                "spec_ready": self._on_spec_ready,
                "spec_implemented": self._on_spec_implemented,
                "spec_verified": self._on_spec_verified,
                "spec_bug_found": self._on_spec_bug_found,
                "spec_done": self._on_spec_done,
            }

            handler = handlers.get(event_kind)
            if handler:
                handler(spec_name)

            # Process any queued runs
            self._process_queue()
        finally:
            self._handling_events.discard(event_key)

    def _on_spec_drafted(self, spec_name: str):
        """Auto-promote drafted → ready, then immediately schedule implementer."""
        self.logger.info("pm_engine", f"Auto-promoting '{spec_name}': drafted → ready")
        self.state_machine.transition(spec_name, "ready")
        # 直接调用 _on_spec_ready 排队实现，不依赖事件循环
        self._on_spec_ready(spec_name)

    def _on_spec_ready(self, spec_name: str):
        """Schedule implementer for ready SPEC (if dependencies are satisfied)."""
        # 防双派发：该 spec 已有活动 implementer worktree 时跳过。
        # 背景（fix-fenix-token-waste）：启动扫描与 event_bus 都会触发 spec_ready，
        # 第二次派发因 worktree 锁失败会把 spec 打回 ready，形成空转反馈环。
        if self.agent_runner.worktree_manager.has_active_worktree(spec_name):
            self.logger.debug(
                "pm_engine",
                f"Skipping '{spec_name}': worktree already active",
            )
            return
        if not self._dependencies_satisfied(spec_name):
            self.logger.info(
                "pm_engine",
                f"Skipping '{spec_name}': dependencies not satisfied",
            )
            return
        self._enqueue(spec_name, "implementer")

    def _on_spec_implemented(self, spec_name: str):
        """Schedule verifier for implemented SPEC."""
        self._enqueue(spec_name, "verifier")

    def _on_spec_verified(self, spec_name: str):
        """Mark verified SPEC as done."""
        # 防重入：使用独立 key，避免与 handle_event 的 ("spec_verified", spec_name)
        # 冲突（handle_event 在调用 handler 前已 add 该 key，若共用会导致本方法被跳过）
        event_key = ("_guard:verified", spec_name)
        if event_key in self._handling_events:
            self.logger.debug("pm_engine", f"Skipping duplicate verified for '{spec_name}'")
            return
        self._handling_events.add(event_key)
        try:
            self.logger.info("pm_engine", f"Verification passed: '{spec_name}' → done")
            self.state_machine.transition(spec_name, "done")
            # 同步触发 spec_done 处理（fix done → 自动重新验证父 SPEC）。
            # 背景：daemon 启动时 full_scan 在 EventBus watcher 启动前同步调度，
            # 阻塞完成整个 fix 生命周期，使 verified→done 变化在快照初始化前发生，
            # spec_done 事件被吞掉，父 SPEC 永远不被重新验证。这里提供同步直接
            # 调用路径（框架原则：状态转换不能只依赖异步事件轮询）。
            # 幂等：父 SPEC 若已非 implementing，transition 校验失败自动跳过；
            # _enqueue 亦有去重。事件总线后续若重复发出 spec_done 亦无害。
            self._on_spec_done(spec_name)
        finally:
            self._handling_events.discard(event_key)

    def _on_spec_bug_found(self, spec_name: str):
        """Create or reset a fix SPEC for the bug and immediately schedule it."""
        # 防重入：使用独立 key，避免与 handle_event 的 ("spec_bug_found", spec_name)
        # 冲突（handle_event 在调用 handler 前已 add 该 key，若共用会导致本方法被跳过）
        event_key = ("_guard:bug_found", spec_name)
        if event_key in self._handling_events:
            self.logger.debug("pm_engine", f"Skipping duplicate bug_found for '{spec_name}'")
            return
        self._handling_events.add(event_key)
        try:
            self._do_spec_bug_found(spec_name)
        finally:
            self._handling_events.discard(event_key)

    def _resolve_fix_spec_name(self, spec_name: str):
        """确定本轮 bug 应使用的 fix SPEC 名称。

        规则：
        - fix-{spec} 不存在，或处于可重置状态（drafted/ready/implemented/bug-found）
          → 返回该名称（复用）
        - fix-{spec} 已终态完成（done/verified/pushed）
          → 递归加 fix- 前缀（fix-fix-{spec}、fix-fix-fix-{spec}...），生成新一轮修复
        - fix-{spec} 处于进行中（testing/implementing）
          → 返回 None（重复派发竞态，跳过）
        """
        candidate = f"fix-{spec_name}"
        while True:
            existing = self.state_machine.read_one(candidate)
            if existing is None:
                return candidate
            status = existing.get("status", "")
            if status in ("testing", "implementing"):
                # 已有进行中的 fix SPEC，视为重复派发，跳过
                return None
            if status in ("done", "verified", "pushed"):
                # 上一轮修复已终态完成，本轮是新 bug，递归加前缀
                candidate = f"fix-{candidate}"
                continue
            # 可重置状态（drafted/ready/implemented/bug-found），复用
            return candidate

    def _ensure_fix_spec_files(self, fix_spec_name: str, parent_spec_name: str):
        """为自动生成的 fix SPEC 写入 proposal.md 与 tasks.md。

        fix SPEC 由验证引擎发现 bug 后自动创建，仅写入 STATE.md 是不够的——
        implementer Agent 依赖磁盘上的 proposal.md/tasks.md 才能执行，
        缺失会导致 SPEC 卡在 implementing 状态。此处生成最小可执行的 SPEC 文档。
        """
        spec_dir = self.project_root / "openspec" / "changes" / fix_spec_name
        spec_dir.mkdir(parents=True, exist_ok=True)

        proposal = (
            f"# Proposal: 修复 {parent_spec_name} 验证发现的缺陷\n\n"
            f"## Why\n\n"
            f"`{parent_spec_name}` 的验证报告发现产品缺陷，导致验证未通过。"
            f"详见 `openspec/changes/{parent_spec_name}/verification-report.md` 的「真实产品 Bug」部分。\n\n"
            f"## What Changes\n\n"
            f"修复验证报告中列出的真实产品缺陷。实现者应先阅读父 SPEC 的 "
            f"`verification-report.md`，定位每个真实产品 Bug 的根因并修复；"
            f"伪失败（测试框架/场景缺陷）不在本 SPEC 修复范围内。\n\n"
            f"## Impact\n\n"
            f"- **代码**：按验证报告修复真实产品缺陷\n"
            f"- **行为**：修复后，父 SPEC 验证报告中失败的场景应转为通过\n"
        )
        tasks = (
            f"# Tasks: 修复 {parent_spec_name} 验证发现的缺陷\n\n"
            f"## 1. 修复真实产品缺陷\n\n"
            f"- [ ] 1.1 阅读 `openspec/changes/{parent_spec_name}/verification-report.md`，"
            f"定位「真实产品 Bug」的根因并修复\n\n"
            f"## 2. 验证与打包\n\n"
            f"- [ ] 2.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过\n"
            f"- [ ] 2.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归\n"
            f"- [ ] 2.3 执行 `bash scripts/package.sh` 生成最新扩展包\n"
        )

        (spec_dir / "proposal.md").write_text(proposal, encoding="utf-8")
        (spec_dir / "tasks.md").write_text(tasks, encoding="utf-8")
        self.logger.info("pm_engine", f"Ensured fix SPEC files: {fix_spec_name}")

    def _do_spec_bug_found(self, spec_name: str):
        """实际执行 bug-found 处理逻辑。"""
        parent_prio = (self.state_machine.read_one(spec_name) or {}).get("priority", 5)

        # 确定本轮 bug 应使用的 fix SPEC 名称
        fix_spec_name = self._resolve_fix_spec_name(spec_name)
        if fix_spec_name is None:
            # 已有进行中的 fix SPEC，视为重复派发竞态，跳过
            self.logger.info(
                "pm_engine",
                f"Fix SPEC for '{spec_name}' already in progress — "
                f"skipping duplicate bug-found handling",
            )
            return

        # 确保 fix SPEC 在磁盘上有 proposal/tasks，否则 implementer 找不到 SPEC 文件
        self._ensure_fix_spec_files(fix_spec_name, spec_name)

        existing_fix = self.state_machine.read_one(fix_spec_name)
        if existing_fix:
            # 复用可重置的 fix SPEC
            self.logger.info(
                "pm_engine",
                f"Fix SPEC '{fix_spec_name}' already exists "
                f"(status={existing_fix.get('status', '')}) — resetting to ready",
            )
            self.state_machine.update_spec(fix_spec_name, {
                "status": "ready",
                "error": f"Re-triggered from bug found in {spec_name}",
                "implementer_run": None,
                "tester_run": None,
                "branch": None,
            })
        else:
            # 新建 fix SPEC（跳过 drafted —— 自动生成，无需人工评审）
            self.state_machine.add_spec(fix_spec_name, {
                "status": "ready",
                "priority": min(parent_prio + 1, 10),
                "branch": None,
                "error": f"Auto-created from bug found in {spec_name}",
            })
            self.logger.info("pm_engine", f"Created fix SPEC: {fix_spec_name}")

        # 父 spec 保持在 bug-found，等 fix 完成后由 _on_spec_done 重新验证
        # （bug-found → implemented）。不在此过渡到 implementing——那会让父 spec
        # 呈现「无进程却在 implementing」的僵尸假象，且 fix 若卡死父 spec 会永久滞留。
        self._append_project_log(f"🐛 Bug found in **{spec_name}** → scheduling **{fix_spec_name}**")

        # Immediately schedule the fix
        self._enqueue(fix_spec_name, "implementer")

    def _on_spec_done(self, spec_name: str):
        """SPEC is done — log, re-verify parent if this was a fix SPEC.

        若 gates.approve_mode == "auto"，自动执行 git push 并推进到 pushed。
        """
        spec = self.state_machine.read_one(spec_name) or {}
        status = spec.get("status", "")

        self.logger.info(
            "pm_engine",
            f"SPEC '{spec_name}' is done — awaiting push approval",
        )

        self._append_project_log(
            f"✅ SPEC completed: **{spec_name}** — awaiting push approval"
        )

        # 自动审批：approve_mode=auto 且状态为 done 时触发
        # （若已 pushed 则 _auto_approve 内部幂等跳过，不重复推送）
        approve_mode = self._get_approve_mode()
        if approve_mode == "auto" and status == "done":
            self._auto_approve(spec_name)

        # If this is a fix SPEC, re-trigger verification of the original SPEC
        if spec_name.startswith("fix-"):
            # 连续剥离所有 fix- 前缀，得到根 SPEC
            # （fix-fix-{spec} 是 {spec} 的第二轮修复，完成后应重新验证 {spec}）
            original = spec_name
            while original.startswith("fix-"):
                original = original[4:]
            original_spec = self.state_machine.read_one(original)
            if original_spec:
                current_status = original_spec.get("status", "")
                # 幂等保护：若父SPEC已在 testing（验证中），说明已有verifier在处理，跳过
                # 注：父 spec 现在保持在 bug-found 等 fix（不再放置为 implementing）
                if current_status == "testing":
                    self.logger.info(
                        "pm_engine",
                        f"Fix done — original '{original}' already in 'testing', "
                        f"skipping duplicate re-verify",
                    )
                    return
                self.logger.info("pm_engine", f"Fix done — re-verifying original: {original}")
                # 使用 transition 做状态转换；若当前状态无法直接转到 implemented，跳过
                # （不再用 update_spec 兜底，那正是竞态覆写的根因）
                if not self.state_machine.is_valid_transition(current_status, "implemented"):
                    self.logger.info(
                        "pm_engine",
                        f"Fix done — cannot transition '{original}' from '{current_status}' "
                        f"to implemented, skipping",
                    )
                    return
                self.state_machine.transition(original, "implemented")
                self.state_machine.update_spec(original, {
                    "error": f"Re-verifying after fix: {spec_name}",
                })
                self._enqueue(original, "verifier")

    def _find_implementer_worktree(self, spec_name: str) -> Optional[Path]:
        """Find the active implementer worktree for a SPEC, or None."""
        wt_mgr = getattr(self.agent_runner, 'worktree_manager', None)
        if wt_mgr is None:
            return None
        return wt_mgr.find_implementer_worktree(spec_name)

    def _read_implementer_result(self, spec_name: str) -> Optional[dict]:
        """读取 implementer 写入的 .fenix-run-result.json，优先从活跃 worktree 读取。

        Returns the parsed dict, or None if not found/invalid.
        """
        result_path = None
        # Try worktree first
        wt_path = self._find_implementer_worktree(spec_name)
        if wt_path:
            wt_result = wt_path / ".fenix-run-result.json"
            if wt_result.exists():
                result_path = wt_result
                self.logger.debug(
                    "pm_engine",
                    f"Reading implementer result from worktree: {wt_result}",
                )
        # Fallback to project root
        if result_path is None:
            root_result = self.project_root / ".fenix-run-result.json"
            if root_result.exists():
                result_path = root_result
                self.logger.debug(
                    "pm_engine",
                    f"Reading implementer result from project root: {root_result}",
                )
        if result_path is None:
            return None
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def _read_verifier_result(self, result_path: Path) -> str | None:
        """读取 verifier 写入的 .fenix-run-result.json，返回 status 字段。

        返回 None 表示文件不存在或格式无效（视为 verified）。
        返回 "verified" 表示全部通过。
        返回 "bug-found" 表示验证发现 Bug。
        返回 "plan-ready" 表示Planner已生成场景。
        """
        try:
            if not result_path.exists():
                self.logger.warning(
                    "pm_engine",
                    f"Verifier result file not found: {result_path}",
                )
                return None
            data = json.loads(result_path.read_text(encoding="utf-8"))
            status = data.get("status", "")
            if status in ("verified", "bug-found", "plan-ready"):
                bugs = data.get("bugs", [])
                bug_count = len(bugs) if isinstance(bugs, list) else 0
                self.logger.info(
                    "pm_engine",
                    f"Verifier result: status={status}, bugs={bug_count}",
                )
                return status
            self.logger.warning(
                "pm_engine",
                f"Unknown verifier status: '{status}', treating as verified",
            )
            return None
        except (json.JSONDecodeError, OSError) as e:
            self.logger.warning(
                "pm_engine",
                f"Failed to read verifier result: {e}",
            )
            return None

    # ── Queue Management ───────────────────────────────────────────

    def _get_spec_priority(self, spec_name: str) -> int:
        """读取 SPEC 的 priority，缺省为 5。"""
        spec = self.state_machine.read_one(spec_name)
        if spec and isinstance(spec.get("priority"), int):
            return spec["priority"]
        return 5

    def _enqueue(self, spec_name: str, agent_type: str):
        """Add a run request to the queue (thread-safe).

        条目结构：(priority, spec_name, agent_type)。
        priority 从 STATE.md 读取（缺省 5）。
        """
        priority = self._get_spec_priority(spec_name)
        entry = (priority, spec_name, agent_type)
        with self._queue_lock:
            # 去重：忽略 priority 差异，只看 (spec, agent)
            if not any(e[1] == spec_name and e[2] == agent_type for e in self._run_queue):
                self._run_queue.append(entry)
                self.logger.debug(
                    "pm_engine",
                    f"Queued: {spec_name} ({agent_type}, P{priority})"
                )

    def _enqueue_front(self, spec_name: str, agent_type: str):
        """Insert a run request at the front of its priority bucket (thread-safe).

        在优先级调度下，「队首」语义改为同档优先：verifier 与 implementer
        属于同一 SPEC、同一 priority，插入后落回同一档且保持档内 FCFS。
        """
        priority = self._get_spec_priority(spec_name)
        entry = (priority, spec_name, agent_type)
        with self._queue_lock:
            # Remove existing duplicate (ignoring priority)
            self._run_queue = [
                e for e in self._run_queue
                if not (e[1] == spec_name and e[2] == agent_type)
            ]
            # 插入到同优先级档的最前面（保持同一档内的顺序）
            insert_idx = 0
            for i, e in enumerate(self._run_queue):
                if e[0] == priority:
                    insert_idx = i
                    break
                if e[0] > priority:
                    insert_idx = i
                    break
                insert_idx = i + 1
            self._run_queue.insert(insert_idx, entry)
            self.logger.debug(
                "pm_engine",
                f"Queued at front of P{priority}: {spec_name} ({agent_type})"
            )

    def _process_queue(self):
        """Process the run queue — relaxed-priority parallel scheduling.

        调度规则（宽松优先级并行，fix-fenix-token-waste 后按用户要求调整）：
        - 任务 X 可派发当且仅当没有比 X 更重要的活动任务
          （即 min(active_priorities) >= X）：有 P6 在跑时 P5 可并发、P7 不行。
        - 同一档内多个任务可并行至 max_concurrent；不同档可并发（只要满足上述规则）。
        - 不抢占：已在运行的任务不会被新到的高优先级中断。
        - 每轮派发队列中最高优先级的合法就绪条目。
        """
        max_concurrent = self._get_config("agents.max_concurrent", 2)

        while True:
            entry_to_dispatch = None

            with self._queue_lock:
                if self._active_runs >= max_concurrent:
                    return
                if not self._run_queue:
                    return

                # 找队列中所有状态合法条目的最高 priority
                # （先不 pop，只扫描以确定 queued_best）
                best_valid_prio = None
                for entry in self._run_queue:
                    prio, sname, atype = entry
                    spec = self.state_machine.read_one(sname)
                    if not spec:
                        continue
                    status = spec.get("status")
                    if atype == "implementer" and status != "ready":
                        continue
                    if atype == "verifier" and status != "implemented":
                        continue
                    if best_valid_prio is None or prio < best_valid_prio:
                        best_valid_prio = prio
                if best_valid_prio is None:
                    return  # 无就绪条目

                # 确定当前应派发的目标优先级（宽松优先级）：
                # 任务 X 可派发当且仅当没有比 X 更重要的活动任务
                # （即 min(active) >= X；有 P6 在跑时 P5 可并发、P7 不行）。
                # 无活动任务时派发就绪条目中最高优先级档。
                if self._active_priorities:
                    min_active = min(self._active_priorities)
                    if best_valid_prio > min_active:
                        # 队列中最优就绪任务比活动任务更低优先（数值更大）：
                        # 被更高优先的活动任务挡住，本轮不派发
                        return
                target_prio = best_valid_prio

                # 从队列头部开始找第一个 priority == target_prio 且状态合法的条目
                dispatch_idx = None
                for i, entry in enumerate(self._run_queue):
                    prio, sname, atype = entry
                    if prio != target_prio:
                        continue
                    spec = self.state_machine.read_one(sname)
                    if not spec:
                        continue
                    status = spec.get("status")
                    if atype == "implementer" and status != "ready":
                        continue
                    if atype == "verifier" and status != "implemented":
                        continue
                    dispatch_idx = i
                    break

                if dispatch_idx is None:
                    # 目标档位无就绪条目（可能有但状态不合法），本轮不派发
                    return

                entry_to_dispatch = self._run_queue.pop(dispatch_idx)
                self._active_runs += 1
                self._active_priority_counts[target_prio] = (
                    self._active_priority_counts.get(target_prio, 0) + 1
                )
                self._active_priorities.add(target_prio)
                active_count = self._active_runs

            priority, spec_name, agent_type = entry_to_dispatch

            # Update state to in-progress
            if agent_type == "implementer":
                self.state_machine.transition(spec_name, "implementing")
            elif agent_type == "verifier":
                self.state_machine.transition(spec_name, "testing")

            self.logger.info(
                "pm_engine",
                f"Dispatching {agent_type} for '{spec_name}' (P{priority})",
                {"active_runs": active_count},
            )

            t = threading.Thread(
                target=self._run_agent_worker,
                args=(spec_name, agent_type, priority),
                daemon=True,
                name=f"fenix-{agent_type}-{spec_name}",
            )
            t.start()

    def _run_agent_worker(self, spec_name: str, agent_type: str, priority: int):
        """Worker thread body: run the agent and handle result.

        Always decrements _active_runs and re-triggers queue processing
        in finally, so slots are released even on exceptions.
        priority 参数用于 finally 中从 _active_priorities 移除对应档位。
        """
        try:
            if agent_type == "implementer":
                wm = self.agent_runner.worktree_manager
                # 主树健康检查（fix-fenix-token-waste）：dispatch 前自动 stash 主树脏改动，
                # 保证 merge-back 有干净基线；成功后 restore_after_merge 恢复原改动。
                stashed = wm.ensure_clean_tree()
                result = self.agent_runner.run_implementer(spec_name)
                # Read .fenix-run-result.json (worktree first, project root fallback)
                # to determine true status — file is more authoritative than
                # process exit code for semantic success/error.
                impl_result = self._read_implementer_result(spec_name)
                impl_status = None
                impl_error = None
                if impl_result:
                    impl_status = impl_result.get("status")
                    if impl_status == "error":
                        impl_error = impl_result.get("error") or result.error
                    elif impl_status != "success":
                        impl_error = result.error
                is_success = result.success and (
                    impl_status is None or impl_status == "success"
                )
                final_error = impl_error or result.error

                if is_success:
                    # Merge worktree branch back into main tree before advancing state.
                    # worktree 已被 agent_runner 清理，但分支仍保留（success 路径不删分支），
                    # 所以用分支名直接 merge。
                    merge_ok = True
                    merge_error = ""
                    if result.branch:
                        merge_ok, merge_error = wm.merge_back_from_branch(result.branch)

                    if not merge_ok:
                        # merge 失败：指纹熔断（fix-fenix-token-waste）。
                        # 同一错误指纹连续失败 ≥ 阈值 → spec 进入 blocked 停止自动重试，
                        # 避免「根因不消除 → 全量重跑 → 再败」的无限烧钱循环。
                        spec_entry = self.state_machine.read_one(spec_name)
                        max_r = self._get_config("agents.max_retries", 3)
                        fp = self._merge_fingerprint(merge_error)
                        prev_fp = spec_entry.get("_merge_fp")
                        try:
                            prev_streak = int(spec_entry.get("_merge_streak", 0) or 0)
                        except (TypeError, ValueError):
                            prev_streak = 0
                        streak = prev_streak + 1 if prev_fp == fp else 1
                        final_error = f"Merge-back failed (fp={fp}): {merge_error}"
                        breaker_threshold = self._get_config("agents.merge_breaker_threshold", 2)
                        if streak >= breaker_threshold:
                            self.state_machine.transition(spec_name, "blocked")
                            self.state_machine.update_spec(spec_name, {
                                "error": final_error,
                                "_merge_fp": fp,
                                "_merge_streak": streak,
                                "_retry_count": 0,
                            })
                            self.logger.error(
                                "pm_engine",
                                f"Circuit breaker tripped for '{spec_name}' (fp={fp}) — spec blocked",
                            )
                        else:
                            try:
                                prev_retries = int(spec_entry.get("_retry_count", 0) or 0)
                            except (TypeError, ValueError):
                                prev_retries = 0
                            retries = prev_retries + 1
                            self.state_machine.update_spec(spec_name, {
                                "status": "ready",
                                "error": final_error,
                                "_merge_fp": fp,
                                "_merge_streak": streak,
                                "_retry_count": retries,
                            })
                            self.logger.warning(
                                "pm_engine",
                                f"Retry {retries}/{max_r} for '{spec_name}' (merge-back failed)",
                            )
                    else:
                        # 恢复 dispatch 前自动 stash 的主树改动（冲突时保留 stash，不阻塞）
                        if stashed:
                            wm.restore_after_merge()
                        self.state_machine.transition(spec_name, "implemented")
                        self.state_machine.update_spec(spec_name, {
                            "implementer_run": result.run_id,
                            "error": None,
                            "_retry_count": 0,
                            "_merge_fp": None,
                            "_merge_streak": 0,
                        })
                        # Immediately queue verifier at FRONT so it runs next
                        self._enqueue_front(spec_name, "verifier")
                        self.logger.info("pm_engine", f"Implement done, verifier queued for '{spec_name}'")
                else:
                    # Retry or mark error
                    spec_entry = self.state_machine.read_one(spec_name)
                    try:
                        prev_retries = int(spec_entry.get("_retry_count", 0) or 0)
                    except (TypeError, ValueError):
                        prev_retries = 0
                    retries = prev_retries + 1
                    max_r = self._get_config("agents.max_retries", 3)
                    if retries >= max_r:
                        self.state_machine.update_spec(spec_name, {
                            "status": "ready",
                            "error": final_error,
                            "_retry_count": 0,
                        })
                        self.logger.error(
                            "pm_engine",
                            f"All retries exhausted for '{spec_name}'",
                        )
                    else:
                        self.state_machine.update_spec(spec_name, {
                            "status": "ready",
                            "error": final_error,
                            "_retry_count": retries,
                        })
                        self.logger.warning(
                            "pm_engine",
                            f"Retry {retries}/{max_r} for '{spec_name}'",
                        )

            elif agent_type == "verifier":
                self._run_verification_pipeline(spec_name)

        except Exception as e:
            self.logger.error("pm_engine", f"Agent run exception: {e}")
        finally:
            # Release the concurrency slot and try to dispatch more work
            with self._queue_lock:
                self._active_runs -= 1
                # 宽松优先级：按优先级计数释放，仅当该档最后一个 run 结束才移除该档，
                # 避免多档并发时把仍活动的档位误移除（fix：多档并发）
                cnt = self._active_priority_counts.get(priority, 0) - 1
                if cnt <= 0:
                    self._active_priority_counts.pop(priority, None)
                    self._active_priorities.discard(priority)
                else:
                    self._active_priority_counts[priority] = cnt
            self._process_queue()

    @staticmethod
    def _merge_fingerprint(error: str) -> str:
        """对 merge 错误计算稳定指纹（fix-fenix-token-waste）。

        归一化：整体去空白后取 sha1 前 12 位。git 对同一根因的报错逐字节一致，
        因此可用字符串归一化哈希；不同根因会得到不同指纹。
        """
        norm = "".join((error or "").split())
        return hashlib.sha1(norm.encode("utf-8", "replace")).hexdigest()[:12]

    # ── Verification Pipeline ─────────────────────────────────────

    def _run_verification_pipeline(self, spec_name: str):
        """执行三步验证流水线。

        步骤1: Planner Agent 生成测试场景
        步骤2: VerifyEngine 并行执行场景（DOM断言 + 视觉对比）
        步骤3: Planner Agent 判定结果

        新流程失败时自动降级到旧版 verifier。
        """
        use_new_flow = self._get_config("agents.use_new_verifier", True)

        if not use_new_flow:
            self._run_legacy_verification(spec_name)
            return

        try:
            self._run_three_stage_verification(spec_name)
        except Exception as e:
            self.logger.warning(
                "pm_engine",
                f"新验证流程失败 '{spec_name}': {e}，降级到旧版 verifier",
            )
            try:
                self._run_legacy_verification(spec_name)
            except Exception as e2:
                self.logger.error(
                    "pm_engine",
                    f"旧版 verifier 也失败了 '{spec_name}': {e2}",
                )
                self.state_machine.transition(spec_name, "bug-found")
                self.state_machine.update_spec(spec_name, {
                    "tester_run": "failed",
                    "error": f"All verification methods failed: {e2}",
                })

    # ── 应用可达性自愈（最终用户验证必选）────────────────────────

    def _ensure_app_reachable(self, spec_name: str) -> tuple:
        """验证前确保应用可达：自动启动 commands.start、处理端口冲突。

        最终用户验证为必选项：场景执行前先保证应用可被浏览器访问；
        若不可达则自动启动服务（commands.start），端口冲突时换端口重试
        （改写场景 URL）。仅在「需用户参与（如收验证码/登录）」或
        「判定无法解决」时才返回不可达，由上层判定而非静默通过。

        Returns:
            (reachable, user_blocked, note)
            - reachable: 自愈后应用是否可达
            - user_blocked: 是否为需用户参与而无法自动验证（预留判定位）
            - note: 人类可读说明（供错误展示）
        """
        scenarios_path = (self.project_root / ".fenix" / "verify-progress"
                          / spec_name / "test_scenarios.json")
        if not scenarios_path.exists():
            return True, False, ""
        try:
            data = json.loads(scenarios_path.read_text(encoding="utf-8"))
        except Exception:
            return True, False, ""

        # 收集场景 navigate 目标 URL（应用入口）
        urls: list[str] = []
        for sc in (data if isinstance(data, list) else []):
            if not isinstance(sc, dict):
                continue
            for step in sc.get("steps", []) or []:
                if isinstance(step, dict) and step.get("action") == "navigate":
                    # navigate 目标 URL 存于 value（见 scenarios.TestStep）：191 个场景
                    # 全部用 value 携带链接，target/url 为空。旧代码读 url/target 导致
                    # urls 恒空，_ensure_app_reachable 恒判可达，可达性门禁永不触发。
                    u = str(step.get("value") or step.get("url") or step.get("target") or "")
                    if u.startswith("http") and u not in urls:
                        urls.append(u)
        if not urls:
            return True, False, ""

        def _probe(u: str, timeout: float = 2.0) -> bool:
            try:
                req = urllib.request.Request(u, method="GET",
                                             headers={"User-Agent": "fenix-verify-probe"})
                with urllib.request.urlopen(req, timeout=timeout):
                    return True
            except Exception:
                return False

        # 1) 直接探测：已可达则无需自愈
        if all(_probe(u) for u in urls):
            return True, False, ""

        # 2) 自愈：读取 commands.start 自动启动应用
        start_cmd = str(self._get_config("commands.start", "") or "").strip()
        if not start_cmd or start_cmd in ("echo 'No start command configured yet'",):
            return False, False, "应用不可达且未配置 commands.start（无法自动启动验证目标应用）"

        base_port = None
        pm = re.search(r"(?:--port|-p)\s+(\d+)", start_cmd)
        if pm:
            base_port = int(pm.group(1))

        self.logger.warning(
            "pm_engine",
            f"验证目标应用不可达，自动启动服务: {start_cmd}",
        )

        # 启动一次（后台、脱离会话、输出丢弃）；随后等待可达或扫描邻近端口
        try:
            subprocess.Popen(start_cmd, shell=True, cwd=str(self.project_root),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except Exception as e:
            return False, False, f"启动验证目标应用失败: {e}"

        for _ in range(30):
            time.sleep(1)
            if all(_probe(u) for u in urls):
                return True, False, "已自动启动应用服务"

        # 端口自动递增场景（如 --port 被占用时服务上探到邻近端口）：
        # 扫描 base_port 附近的端口，命中则改写场景 URL 并确认可达
        if base_port:
            for port in range(base_port + 1, base_port + 51):
                if _probe(f"http://127.0.0.1:{port}/"):
                    urls_new = [re.sub(r":%d(?=[/\?]|$)" % base_port, f":{port}", u) for u in urls]
                    if all(_probe(u) for u in urls_new):
                        self._rewrite_scenario_port(scenarios_path, base_port, port)
                        return True, False, f"已自动启动应用服务（端口冲突，改用 {port}）"

        return False, False, ("应用仍不可达：已自动执行 commands.start 并扫描邻近端口，"
                              "仍无法连接（可能需人工启动/换端口，或属需用户参与的验证场景）")

    def _rewrite_scenario_port(self, scenarios_path: Path, old_port: int, new_port: int):
        """端口冲突换端口后，重写 test_scenarios.json 中的 URL 端口。"""
        try:
            content = scenarios_path.read_text(encoding="utf-8")
            content = re.sub(r":%d(?=[/\?\"']|$)" % old_port, f":{new_port}", content)
            scenarios_path.write_text(content, encoding="utf-8")
            self.logger.info("pm_engine", f"已重写验证场景端口 {old_port} → {new_port}")
        except Exception as e:
            self.logger.warning("pm_engine", f"重写验证场景端口失败: {e}")

    def _run_three_stage_verification(self, spec_name: str):
        """三步验证流水线主逻辑。"""
        import asyncio
        import importlib
        import sys

        # 重新加载验证引擎模块，确保使用最新代码
        # fenixd 作为常驻进程运行，Python 会缓存已导入的模块，
        # 实现者更新代码后缓存不会自动失效，必须显式重新加载
        # 注意：子模块必须先于父包重新加载（依赖顺序）
        #
        # 额外保障机制（fix-fix-fix-fix）：
        # importlib.reload 不会更新其他模块中已导入的名称引用，
        # 因此在 reload 之后显式重新导入核心类，确保使用最新版本。
        _verify_modules = [
            "core.verify_engine.visual_diff",
            "core.verify_engine.browser",
            "core.verify_engine.assertions",
            "core.verify_engine.scenarios",
            "core.verify_engine.engine",
            "core.verify_engine",
        ]
        for mod_name in _verify_modules:
            if mod_name in sys.modules:
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass  # 重新加载失败时使用缓存版本

        # 额外保障：强制从磁盘重新导入核心模块
        # Python 的 import 系统会检查 sys.modules，但如果 reload 失败，
        # 下面的 import 会使用已更新的 sys.modules 条目
        for mod_name in _verify_modules:
            try:
                if mod_name not in sys.modules:
                    importlib.import_module(mod_name)
            except Exception:
                pass

        from .verify_engine import VerifyEngine
        from .verify_engine.scenarios import load_scenarios

        # ── 阶段1: Planner 生成测试场景 ──
        self.logger.info("pm_engine", f"[阶段1] Planner 生成场景: {spec_name}")
        plan_result = self.agent_runner.run_planner(spec_name, "plan")

        if not plan_result.success:
            raise RuntimeError(f"Planner plan 失败: {plan_result.error}")

        # 验证 Planner 是否成功生成场景文件
        run_result_path = self.project_root / ".fenix-run-result.json"
        plan_status = self._read_verifier_result(run_result_path)
        if plan_status != "plan-ready":
            raise RuntimeError(f"Planner 未生成有效场景，status={plan_status}")

        # ── 阶段2: 验证引擎执行 ──
        self.logger.info("pm_engine", f"[阶段2] 验证引擎执行: {spec_name}")
        scenarios_path = (
            self.project_root / ".fenix" / "verify-progress"
            / spec_name / "test_scenarios.json"
        )
        scenarios = load_scenarios(scenarios_path)

        # ── 阶段2.5: 应用可达性自愈（最终用户验证必选）──
        # 场景执行前确保应用可被浏览器访问；不可达时自动启动 commands.start、
        # 端口冲突换端口重试。自愈失败由下方验证门禁兜底，不静默判定通过。
        app_reachable, _user_blocked, reach_note = self._ensure_app_reachable(spec_name)
        self.logger.info(
            "pm_engine",
            f"[阶段2] 应用可达性: {'OK' if app_reachable else '不可达'} — {reach_note or '无 navigate 依赖'}",
        )

        engine = VerifyEngine(
            spec_name, self.project_root, self.logger, self.config
        )
        report = asyncio.run(engine.run(scenarios))

        fail_count = report["summary"]["failed"] + report["summary"]["errors"]
        self.logger.info(
            "pm_engine",
            f"[阶段2] 完成: {report['summary']['total']}场景, "
            f"{report['summary']['passed']}通过, "
            f"{report['summary']['warnings']}警告, "
            f"{fail_count}失败",
        )

        # ── 阶段2 验证门禁：应用不可达且场景全失败时不判定 verified ──
        # 最终用户验证为必选项：若自愈后应用仍不可达、0 场景通过，则本次验证
        # 并未真正触达最终用户可见功能，不得静默判定 verified/done；将问题与
        # 已尝试的解决方案写入 error 暴露（而非 "0通过/31失败" 却标完成）。
        if (not app_reachable
                and report["summary"]["passed"] == 0
                and fail_count == report["summary"]["total"]):
            self.state_machine.update_spec(spec_name, {
                "tester_run": "blocked:app-unreachable",
                "error": f"验证无法执行（最终用户验证未完成）: {reach_note or '应用不可达'}",
            })
            self.logger.error(
                "pm_engine",
                f"验证门禁: '{spec_name}' 应用不可达，未判定 verified — {reach_note}",
            )
            return

        # ── 阶段3: Planner 判定结果 ──
        self.logger.info("pm_engine", f"[阶段3] Planner 判定: {spec_name}")
        judge_result = self.agent_runner.run_planner(spec_name, "judge")

        if not judge_result.success:
            raise RuntimeError(f"Planner judge 失败: {judge_result.error}")

        # 读取判定结果
        verifier_status = self._read_verifier_result(run_result_path)
        if verifier_status == "bug-found":
            self.state_machine.transition(spec_name, "bug-found")
            self.state_machine.update_spec(spec_name, {
                "tester_run": judge_result.run_id,
                "error": "Verification found bugs — see verification report",
            })
            self.logger.warning(
                "pm_engine",
                f"Verifier found bugs in '{spec_name}', transitioning to bug-found",
            )
            self._on_spec_bug_found(spec_name)
        else:
            self.state_machine.transition(spec_name, "verified")
            self.state_machine.update_spec(spec_name, {
                "tester_run": judge_result.run_id,
                "error": None,
            })
            self._on_spec_verified(spec_name)

    def _run_legacy_verification(self, spec_name: str):
        """降级方案：使用旧版单体 Verifier Agent。"""
        result = self.agent_runner.run_verifier(spec_name)
        if result.success:
            run_result_path = self.project_root / ".fenix-run-result.json"
            verifier_status = self._read_verifier_result(run_result_path)
            if verifier_status == "bug-found":
                self.state_machine.transition(spec_name, "bug-found")
                self.state_machine.update_spec(spec_name, {
                    "tester_run": result.run_id,
                    "error": "Verification found bugs — see verification report",
                })
                self.logger.warning(
                    "pm_engine",
                    f"Verifier (legacy) found bugs in '{spec_name}'",
                )
                self._on_spec_bug_found(spec_name)
            else:
                self.state_machine.transition(spec_name, "verified")
                self.state_machine.update_spec(spec_name, {
                    "tester_run": result.run_id,
                    "error": None,
                })
                self._on_spec_verified(spec_name)
        else:
            self.state_machine.transition(spec_name, "bug-found")
            self.state_machine.update_spec(spec_name, {
                "tester_run": result.run_id,
                "error": f"Verifier agent failed: {result.error}",
            })

    # ── Reporting ──────────────────────────────────────────────────

    def generate_report(self) -> str:
        """Generate a project status report."""
        all_specs = self.state_machine.read_all()

        if not all_specs:
            return "📋 No SPECs yet. Create one with /fenix:new"

        # Count by status
        counts = {}
        for entry in all_specs.values():
            s = entry.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1

        lines = [
            f"## Fenix Project Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "### Summary",
        ]

        status_icons = {
            "drafted": "📝",
            "ready": "📌",
            "implementing": "🔨",
            "implemented": "🧪",
            "testing": "🔍",
            "verified": "✅",
            "bug-found": "🐛",
            "done": "🎯",
            "pushed": "🚀",
        }

        for name, entry in sorted(all_specs.items(),
                                   key=lambda x: x[1].get("priority", 999)):
            status = entry.get("status", "unknown")
            icon = status_icons.get(status, "❓")
            priority = entry.get("priority", "?")
            lines.append(f"- {icon} **{name}** (P{priority}): {status}")

        lines.append("")
        lines.append("### Stats")
        lines.append(f"- Total: {len(all_specs)}")
        for status, count in sorted(counts.items()):
            icon = status_icons.get(status, "❓")
            lines.append(f"- {icon} {status}: {count}")

        return "\n".join(lines)

    def generate_daily_report(self):
        """Generate daily report and append to PROJECT_LOG.md."""
        report = self.generate_report()

        log_path = self.project_root / "PROJECT_LOG.md"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n---\n\n{report}\n")

        self.logger.info("pm_engine", "Daily report generated")

    # ── Push Gate ──────────────────────────────────────────────────

    def get_pushable_specs(self):
        """Get all done SPECs awaiting push approval."""
        return self.state_machine.get_by_status("done")

    def approve_push(self, spec_name: str):
        """Approve and push a done SPEC.

        执行真实 git push，成功后将状态推进到 pushed。
        推送失败返回 False，状态保持 done。
        """
        spec = self.state_machine.read_one(spec_name)
        if not spec or spec.get("status") != "done":
            self.logger.warning("pm_engine", f"Cannot push '{spec_name}': not in done state")
            return False

        branch = self._resolve_push_branch(spec_name, spec)
        success, error = self._git_push_branch(branch)
        if not success:
            self.logger.error(
                "pm_engine",
                f"git push failed for '{spec_name}' (branch={branch}): {error}",
            )
            self.state_machine.update_spec(spec_name, {
                "error": f"git push failed: {error}",
            })
            return False

        self.state_machine.transition(spec_name, "pushed")
        self._append_project_log(f"🚀 SPEC pushed: **{spec_name}** (branch: {branch})")
        self.logger.info("pm_engine", f"SPEC pushed: {spec_name} (branch={branch})")
        return True

    def _auto_approve(self, spec_name: str):
        """自动审批：在 auto 模式下 SPEC 到达 done 后自动执行 git push 并推进到 pushed。

        幂等：若 SPEC 已处于 pushed 状态则直接返回 True（不重复推送）。
        推送失败保留 done 状态并记录 error，供人工兜底。
        """
        spec = self.state_machine.read_one(spec_name)
        if not spec:
            return False
        status = spec.get("status", "")
        if status == "pushed":
            # 已 pushed，不重复触发
            return True
        if status != "done":
            self.logger.warning(
                "pm_engine",
                f"_auto_approve: '{spec_name}' is in '{status}', not done — skipping",
            )
            return False

        self.logger.info("pm_engine", f"Auto-approving '{spec_name}' (approve_mode=auto)")
        return self.approve_push(spec_name)

    def _resolve_push_branch(self, spec_name: str, spec: dict) -> str:
        """解析 SPEC 的推送分支名。

        优先使用 STATE.md 中的 branch 字段，否则按
        {worktree.implement_branch_prefix}/{spec_name} 构造（默认 fenix/<spec_name>）。
        """
        branch = spec.get("branch")
        if branch and isinstance(branch, str) and branch.strip():
            return branch.strip()
        prefix = self._get_config("worktree.implement_branch_prefix", "fenix")
        return f"{prefix}/{spec_name}"

    def _git_push_branch(self, branch: str) -> tuple:
        """在 project_root 执行 git push origin <branch>。

        Returns: (success: bool, error_message: str)
        """
        try:
            result = subprocess.run(
                ["git", "push", "origin", branch],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                return True, ""
            error = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            return False, error
        except subprocess.TimeoutExpired:
            return False, "git push timed out after 120s"
        except Exception as e:
            return False, str(e)

    # ── Helpers ────────────────────────────────────────────────────

    def _append_project_log(self, message: str):
        """Append a timestamped message to PROJECT_LOG.md."""
        log_path = self.project_root / "PROJECT_LOG.md"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n- [{timestamp}] {message}")

    def _get_approve_mode(self) -> str:
        """Return the approve_mode, defaulting to 'manual'."""
        from .config import ConfigLoader
        return ConfigLoader.get_approve_mode(self.config)

    def _get_config(self, key: str, default=None):
        """Get a nested config value."""
        from .config import ConfigLoader
        return ConfigLoader.get(self.config, key, default)

    def _dependencies_satisfied(self, spec_name: str) -> bool:
        """Check if all dependencies of a SPEC are in a terminal complete state."""
        spec = self.state_machine.read_one(spec_name)
        if not spec:
            return True

        deps = spec.get("depends_on")
        if not deps or deps == "null":
            return True

        # deps is a comma-separated list of SPEC names
        dep_names = [d.strip() for d in str(deps).split(",") if d.strip()]
        if not dep_names:
            return True

        for dep_name in dep_names:
            dep_spec = self.state_machine.read_one(dep_name)
            if not dep_spec:
                self.logger.warning("pm_engine", f"Dependency '{dep_name}' not found for '{spec_name}'")
                return False
            dep_status = dep_spec.get("status", "")
            if dep_status not in ("done", "pushed", "implemented", "verified"):
                self.logger.info(
                    "pm_engine",
                    f"'{spec_name}' blocked: dependency '{dep_name}' is '{dep_status}' (need done/pushed/implemented/verified)",
                )
                return False

        return True

    # ── Blocker Detection & Health Reporting ───────────────────────

    def check_blockers(self) -> dict:
        """
        Scan all SPECs for blocking/stuck conditions and generate a health report.
        Called periodically by the EventBus full-scan cycle.

        Returns a dict with blocker details if any found.
        """
        self._last_blocker_check = datetime.now(timezone.utc)
        all_specs = self.state_machine.read_all()

        stuck_threshold_minutes = self._get_config("schedule.stuck_threshold_minutes", 60)
        now = datetime.now(timezone.utc)

        blockers = []
        warnings = []

        for name, entry in all_specs.items():
            status = entry.get("status", "drafted")

            # Terminal states — skip
            if status in ("done", "pushed"):
                continue

            # Transient state — verified should auto-transition to done;
            # if stuck here, flag as blocker
            if status == "verified":
                blockers.append(f"'{name}': 卡在 verified 状态（应为瞬态，需要推进到 done）")
                continue

            # Check if stuck in an active state
            if status in ("implementing", "testing"):
                try:
                    updated_str = entry.get("updated", "")
                    if updated_str:
                        updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                        elapsed = (now - updated).total_seconds() / 60
                        if elapsed > stuck_threshold_minutes:
                            blockers.append({
                                "spec": name,
                                "status": status,
                                "reason": f"Stuck in '{status}' for {int(elapsed)} minutes (threshold: {stuck_threshold_minutes}m)",
                                "error": entry.get("error") or "No error recorded",
                                "elapsed_minutes": int(elapsed),
                            })
                except (ValueError, TypeError):
                    pass

            # Check for persistent errors
            error = entry.get("error")
            if error and status == "ready":
                try:
                    retries = int(entry.get("_retry_count", 0) or 0)
                except (TypeError, ValueError):
                    retries = 0
                if retries > 0:
                    warnings.append({
                        "spec": name,
                        "status": status,
                        "reason": f"Failed {retries} retry attempts, last error: {error[:100]}",
                    })

            # Check for ready-but-starving (never been picked up)
            if status == "ready":
                try:
                    updated_str = entry.get("updated", "")
                    if updated_str:
                        updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                        elapsed = (now - updated).total_seconds() / 60
                        if elapsed > stuck_threshold_minutes * 2:
                            warnings.append({
                                "spec": name,
                                "status": status,
                                "reason": f"Waiting in ready queue for {int(elapsed)} minutes — possible queue starvation",
                                "elapsed_minutes": int(elapsed),
                            })
                except (ValueError, TypeError):
                    pass

        # Log and auto-recover
        if blockers:
            self.logger.warning(
                "pm_engine",
                f"BLOCKER CHECK: {len(blockers)} blocking, {len(warnings)} warnings",
                {"blockers": blockers, "warnings": warnings},
            )
            self._write_blocker_report(blockers, warnings)

            # Auto-recovery: reset stuck SPECs to previous state so they get retried
            for b in blockers:
                spec_name = b["spec"]
                self.logger.info("pm_engine", f"Auto-recovering stuck SPEC: {spec_name}")
                self.state_machine.update_spec(spec_name, {
                    "status": "implemented",
                    "error": f"Auto-recovered from stuck {b['status']} state ({b['elapsed_minutes']} min)",
                })
                self._enqueue(spec_name, "verifier")

        return {"blockers": blockers, "warnings": warnings, "checked_at": now.isoformat()}

    def _write_blocker_report(self, blockers: list, warnings: list):
        """Write a blocker report to PROJECT_LOG.md, throttled to once per hour."""
        now = datetime.now(timezone.utc)

        # Throttle: don't write more than once per hour
        if self._last_blocker_report_time:
            elapsed = (now - self._last_blocker_report_time).total_seconds()
            if elapsed < 3600:
                return

        self._last_blocker_report_time = now

        lines = [
            f"\n### ⚠️ Blocker Report — {now.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
        ]

        if blockers:
            lines.append(f"**{len(blockers)} blocker(s) detected:**")
            lines.append("")
            for b in blockers:
                lines.append(f"- 🔴 **{b['spec']}**: {b['reason']}")
                lines.append(f"  - Status: `{b['status']}`, Elapsed: {b['elapsed_minutes']} minutes")
                lines.append(f"  - Last error: {b['error'][:120]}")
                lines.append("")

        if warnings:
            lines.append(f"**{len(warnings)} warning(s):**")
            lines.append("")
            for w in warnings:
                lines.append(f"- 🟡 **{w['spec']}**: {w['reason']}")
                lines.append("")

        if not blockers and not warnings:
            lines.append("✅ No blockers detected. All SPECs progressing normally.")
            lines.append("")

        lines.append(f"*Next check: ~{self._get_config('schedule.poll_interval_minutes', 30)} minutes*")
        lines.append("")

        # Append to project log
        log_path = self.project_root / "PROJECT_LOG.md"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))

        self.logger.info("pm_engine", "Blocker report written to PROJECT_LOG.md")

    def get_health_summary(self) -> str:
        """Return a human-readable one-line health summary for /fenix-status."""
        all_specs = self.state_machine.read_all()
        if not all_specs:
            return "📋 尚无 SPEC"

        total = len(all_specs)
        done = sum(1 for e in all_specs.values() if e.get("status") in ("done", "pushed"))
        active = sum(1 for e in all_specs.values() if e.get("status") in ("implementing", "testing"))
        blocked = sum(1 for e in all_specs.values()
                      if e.get("status") == "ready" and e.get("error"))

        parts = [f"📦 {total} 个 SPEC"]
        if done:
            parts.append(f"✅ {done} 完成")
        if active:
            parts.append(f"🔨 {active} 进行中")
        if blocked:
            parts.append(f"⚠️ {blocked} 阻塞")

        return " | ".join(parts)
