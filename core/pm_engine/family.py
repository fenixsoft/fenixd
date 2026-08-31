"""family.py — FamilyGovernor：fix 家族治理（谱系解析/家族门/waiver/sibling 修复互斥/族谱爆炸信号/bug-found 打回与人工升级）（refactor-core-packages 阶段 4）。

无状态组件：SPEC 状态全部经门面回引 self._pm.state_machine 落在
STATE.md（design D3 规则 3），本组件不持有实例状态。

"""

from typing import Optional
import re


# ── 原地打回升级阈值（inplace-bug-repair D2）────────────────────
# _verify_fail_rounds 达到此值时冻结为 blocked，停止自动修复，等待人工裁决。
# 模块常量，不进 config（避免触发「配置项必须带 Dashboard 界面」约束）。
MAX_VERIFY_FAIL_ROUNDS = 3


class FamilyGovernor:
    """fix 家族治理组件（门面 PMEngine 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

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
            existing = self._pm.state_machine.read_one(candidate)
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
        spec_dir = self._pm.project_root / "openspec" / "changes" / fix_spec_name
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
        self._pm.logger.info("pm_engine", f"Ensured fix SPEC files: {fix_spec_name}")


    @staticmethod
    def _fix_prefix_depth(name: str) -> int:
        """深度：规范名中连续 `fix-` 前缀层数（name 为子 SPEC 名）。

        fix-x → 1；fix-fix-fix-x → 3。非 fix 名 → 0。
        """
        depth = 0
        s = name
        while s.startswith("fix-"):
            depth += 1
            s = s[len("fix-"):]
        return depth


    @staticmethod
    def _fix_strip_all(name: str) -> str:
        """剥除全部连续 `fix-` 前缀，得到家族根名（fix-fix-x → x）。"""
        return name[4 * FamilyGovernor._fix_prefix_depth(name):] if name.startswith("fix-") else name


    def _family_width(self, child_name: str) -> int:
        """宽度：同根（剥除全部 fix- 前缀后同名）且未完成（非 done/pushed）的 fix 子代数量。

        口径依据 STATE 全量 read_all（design D4：不受 ready 清空字段保留策略影响，
        对历史存在的四层命名按现值评估，不追溯惩罚已 done/pushed 祖先）。
        """
        root = self._fix_strip_all(child_name)
        specs = self._pm.state_machine.read_all() or {}
        count = 0
        for name, entry in specs.items():
            if not isinstance(name, str) or not name.startswith("fix-") or name == child_name:
                continue
            if self._fix_strip_all(name) != root:
                continue
            status = (entry or {}).get("status", "")
            if status in ("done", "pushed"):
                continue
            count += 1
        return count


    def _family_waiver_set(self, spec_name: str) -> bool:
        """父 SPEC 是否持有放行豁免位 `_family_waiver=true`（单次）。"""
        spec = self._pm.state_machine.read_one(spec_name) or {}
        raw = str(spec.get("_family_waiver") or "").strip().lower()
        return raw in ("true", "1", "yes")


    def _consume_family_waiver(self, spec_name: str) -> bool:
        """消费豁免位：若存在则复位为 False，返回原值。"""
        had = self._family_waiver_set(spec_name)
        if had:
            self._pm.state_machine.update_spec(spec_name, {"_family_waiver": False})
        return had


    def _family_gate_blocked(self, parent_name: str, child_name: str) -> bool:
        """越界判定：候选子 SPEC 的深度/宽度是否超过 pm.family 上限。

        深度 > max_depth（默认 3）或 宽度 >= max_width（默认 2，新成员将越界）
        时返回 True。enabled 语义由 config 承载：未配置即采用默认值。
        """
        iw = self._pm._get_config("pm.family.max_depth")
        ns = self._pm._get_config("pm.family.max_width")
        max_depth = int(iw if iw is not None else 3)
        max_width = int(ns if ns is not None else 2)
        depth = self._fix_prefix_depth(child_name)
        if depth > max_depth:
            return True
        width = self._family_width(child_name)
        return width >= max_width


    @staticmethod
    def _is_fix_spec(name: str) -> bool:
        """判定 name 是否为 fix SPEC（连续 `fix-` 前缀命名）。"""
        return isinstance(name, str) and name.startswith("fix-")


    @staticmethod
    def _same_root(name_a: str, name_b: str) -> bool:
        """同根判定：剥除全部连续 `fix-` 前缀后同名（design D1 去重依据）。

        fix-fix-x 与 fix-x、fix-x 与 fix-x 同根；fix-x 与 fix-y、fix-x 与 y 不同根。
        """
        if not (FamilyGovernor._is_fix_spec(name_a) and FamilyGovernor._is_fix_spec(name_b)):
            return False
        return FamilyGovernor._fix_strip_all(name_a) == FamilyGovernor._fix_strip_all(name_b)


    def _same_root_siblings(self, spec_name: str) -> list:
        """返回 spec_name 的同根非终态兄弟列表（排除自身，design 守卫一/三）。

        口径：同根（剥除全部 fix- 前缀后同名）+ 非终态（非 done/pushed）。
        含自身处于进行中的兄弟亦计入——守卫关心的是「同根是否已有非终态修复活动」。
        """
        if not self._is_fix_spec(spec_name):
            return []
        root = self._fix_strip_all(spec_name)
        specs = self._pm.state_machine.read_all() or {}
        siblings = []
        for name, entry in specs.items():
            if not isinstance(name, str) or not self._is_fix_spec(name):
                continue
            if self._fix_strip_all(name) != root:
                continue
            if name == spec_name:
                continue
            status = (entry or {}).get("status", "")
            if status in ("done", "pushed"):
                continue
            siblings.append(name)
        return siblings


    def _sibling_repair_active(self, spec_name: str, my_enqueued_at: float = None) -> str:
        """判定同根兄弟是否存在 actionable 修复活动，返回承载方 spec 名或空串（design D3）。

        actionable 定义（design D3）：兄弟 status ∈ {implementing, ready(其队列含实现器条目)}
        或存在活跃 impl/verify agent（worktree 进程存活探测复用孤儿白名单逻辑）。
        仅 ready 无队列条目不计为 actionable（防僵死 ready 永久阻塞）。

        my_enqueued_at：派发方（守卫三调用点）自身条目的入队时刻，用于先到先得
        裁决（design D2「先到先得，后到抑制」）。批量入队现场（full_scan 一次排入
        同根双 ready）若不做此裁决，兄弟双方都会把对方判为 actionable 而互相抑制
        ——双方永远无法派发（2026-08-28 实证队列死锁）。规则：仅当兄弟的实现器
        条目入队不晚于我时，才由兄弟承载；兄弟更新则我来承载。
        my_enqueued_at 为 None（非派发路径调用）保持原判，全部计 actionable。
        """
        for sib in self._same_root_siblings(spec_name):
            sib_spec = self._pm.state_machine.read_one(sib) or {}
            status = sib_spec.get("status", "")
            if status == "implementing":
                return sib
            if status == "ready":
                # 仅当队列含该兄弟的实现器条目时才视为 actionable
                with self._pm._queue_lock:
                    sib_entry = next(
                        (e for e in self._pm._run_queue
                         if e[1] == sib and e[2] == "implementer"),
                        None,
                    )
                if sib_entry is not None:
                    if my_enqueued_at is None or sib_entry[3] <= my_enqueued_at:
                        return sib
                    # 兄弟条目晚于我入队：先到先得，由我承载，不计 actionable
                    continue
                # ready 但无队列条目：进一步探测活跃 worktree/agent 进程
                # 经门面回引：测试在门面实例上 patch 的补丁缝保持有效
                if self._pm._sibling_has_live_agent(sib):
                    return sib
        # 兜底：直接探测自身/兄弟是否仍有存活 agent 进程（覆盖非 ready 但卡死的边缘态）
        for sib in self._same_root_siblings(spec_name):
            if self._pm._sibling_has_live_agent(sib):
                return sib
        return ""


    def _sibling_has_live_agent(self, spec_name: str) -> bool:
        """探测 spec 是否仍有存活的 agent 子进程（worktree 存活探测，复用孤儿白名单逻辑）。

        - worktree_manager.has_active_worktree 优先（内存活动集合，最可靠）；
        - 否则用 agent_runner.has_live_attempt（姊妹变更落地接口）兜底；
        - 二者皆不可得时回退 pgrep 探测进程表（与 event_bus._ready_has_live_child 同口径）。
        """
        try:
            wm = getattr(self._pm.agent_runner, "worktree_manager", None)
            if wm is not None and hasattr(wm, "has_active_worktree"):
                if wm.has_active_worktree(spec_name):
                    return True
        except Exception:
            pass
        try:
            ar = self._pm.agent_runner
            if hasattr(ar, "has_live_attempt"):
                if ar.has_live_attempt(spec_name):
                    return True
        except Exception:
            pass
        # 回退：pgrep 探测 worktrees 目录下的 claude 进程（与 event_bus 同语义）
        try:
            import subprocess as _sp
            wt_root = self._pm.project_root / ".claude" / "worktrees"
            if not wt_root.is_dir():
                return False
            pat = f"impl-{spec_name}-" if "verify" not in spec_name else f"verify-{spec_name}-"
            for d in wt_root.iterdir():
                if not d.is_dir():
                    continue
                if spec_name in d.name:
                    r = _sp.run(
                        ["pgrep", "-f", f"worktrees/{d.name}"],
                        capture_output=True, text=True, timeout=10,
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        return True
        except Exception:
            return False
        return False


    def _has_non_terminal_child_fix(self, spec_name: str) -> str:
        """判定 spec 是否已存在同根非终态子 fix（守卫一/二共用，design D4 子终态解封）。

        返回承载修复的子 fix 名；无则空串。子 fix 指更深一层的 fix- 前缀 SPEC
        （fix-{spec} 自身或 fix-fix-{spec} 等），非终态 = 非 done/pushed。
        """
        child = f"fix-{spec_name}"
        specs = self._pm.state_machine.read_all() or {}
        # 逐层检查更深前缀的子 fix 是否存在且非终态
        candidate = child
        best = ""
        while True:
            entry = specs.get(candidate)
            if entry is None:
                # 该层不存在：若已有更深层终态子，仍可承载；否则停止
                if best:
                    break
                # 递归尝试更深一层（fix-fix-{spec}）
                deeper = f"fix-{candidate}"
                if deeper in specs:
                    candidate = deeper
                    continue
                break
            status = (entry or {}).get("status", "")
            if status in ("done", "pushed"):
                # 该层终态：不承载，但允许检查更深一层是否仍在飞
                deeper = f"fix-{candidate}"
                if deeper in specs:
                    candidate = deeper
                    continue
                break
            # 非终态：作为承载方；但仍继续检查是否有更深在飞（取最深非终态）
            best = candidate
            deeper = f"fix-{candidate}"
            if deeper in specs:
                candidate = deeper
                continue
            break
        return best


    def _signal_family_explosion(self, parent_name: str, child_name: str, detail: str):
        """越界派生请求转 family_explosion 困境信号（severity=major）写入 admin store。

        不改父 SPEC 状态、不产生 bug-found 处理副作用（design D4）。信号进入既有
        admin_monitor 唤起链（Administrator 处置 → 可对父 SPEC 放行一次）。
        """
        from core.admin_store import AdminStore, SIGNAL
        store = AdminStore(self._pm.project_root, self._pm.logger)
        try:
            store.append({
                "kind": SIGNAL,
                "signal_type": "family_explosion",
                "spec": parent_name,
                "severity": "major",
                "description": (f"fix 族谱爆炸：'{parent_name}' 派生 {child_name} 被"
                                f"深度/宽度上限拦截（{detail}），自动创建已中止"),
                "evidence": f"candidate={child_name}; {detail}",
                "recommended_action": ("人工检修根因环境；若确认放行一次，对该父 SPEC "
                                       "设置 _family_waiver=true（下轮允许再创建一个子 SPEC）"),
            })
            self._pm.logger.error(
                "pm_engine",
                f"fix 族谱收敛拦截: '{parent_name}' → {child_name} 自动创建中止（{detail}）"
                f"，已写入 family_explosion 信号",
            )
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"family_explosion 信号写入 admin store 失败: {e}",
            )


    def _do_spec_bug_found(self, spec_name: str):
        """实际执行 bug-found 处理逻辑。

        新裁决路径（inplace-bug-repair）：父 SPEC 原地打回重修，不再派生 fix-* 子 SPEC。
        存量 fix-* 链保留 legacy 闭环直至自然终态。
        """
        # ── legacy 兼容：存量 fix-* SPEC 保持原有闭环 ──
        if self._is_fix_spec(spec_name):
            # 守卫一（fix-repair-lane-dedup）：fix spec 已有非终态子 fix 时抑制 reset
            carrier = self._has_non_terminal_child_fix(spec_name)
            if carrier:
                self._pm.logger.info(
                    "pm_engine",
                    f"守卫一：'{spec_name}' 为 fix spec 且已有非终态子 fix "
                    f"'{carrier}' 承载修复——抑制 reset，保持 bug-found",
                )
                self._pm.state_machine.update_spec(spec_name, {
                    "error": f"修复由子 fix '{carrier}' 承载，抑制重实现重置",
                })
                return
            # fix-* SPEC 走 legacy 派生闭环（子 fix 完成 → 父 SPEC 自动重验）
            self._do_legacy_fix_spec_bug_found(spec_name)
            return

        # ── 新裁决路径：原地打回（inplace-bug-repair D1-D3）──
        entry = self._pm.state_machine.read_one(spec_name) or {}
        fail_rounds = 0
        try:
            fail_rounds = int(entry.get("_verify_fail_rounds", 0) or 0)
        except (TypeError, ValueError):
            fail_rounds = 0
        fail_rounds += 1

        if fail_rounds >= MAX_VERIFY_FAIL_ROUNDS:
            # ── 升级闸门：冻结为 blocked + human-escalation-alerts 告警 ──
            self._pm.state_machine.update_spec(spec_name, {
                "_verify_fail_rounds": fail_rounds,
                "status": "blocked",
                "error": (
                    f"验证连续失败 {fail_rounds} 轮，已冻结等待人工裁决。"
                    f"详见 `openspec/changes/{spec_name}/verification-report.md`"
                ),
            })
            self._pm.logger.error(
                "pm_engine",
                f"升级闸门：'{spec_name}' 验证失败 {fail_rounds} 轮，"
                f"冻结为 blocked，等待人工裁决",
            )
            self._send_human_escalation_alert(
                spec_name=spec_name,
                signal_type="verify_fail_escalation",
                severity="major",
                description=(
                    f"'{spec_name}' 验证连续失败 {fail_rounds} 轮，已冻结等待人工裁决"
                ),
                evidence=(
                    f"spec={spec_name}; fail_rounds={fail_rounds}; "
                    f"report=openspec/changes/{spec_name}/verification-report.md"
                ),
                recommended_action=(
                    "检查验证报告定位根因，人工调整 SPEC 状态后重跑验证；"
                    "人工重置计数器即重新获得自动修复机会"
                ),
            )
            return

        # ── 正常打回：递增计数 + 重置 implementing + 注入修复任务 ──
        self._pm.state_machine.update_spec(spec_name, {
            "_verify_fail_rounds": fail_rounds,
            "status": "implementing",
            "error": (
                f"验证失败第 {fail_rounds} 轮，原地打回重修"
            ),
        })
        self._pm.logger.warning(
            "pm_engine",
            f"原地打回：'{spec_name}' 第 {fail_rounds} 轮失败，"
            f"重置为 implementing 并注入修复任务",
        )
        # 注入 tasks.md「验证修复」段
        self._inject_verify_fix_task(spec_name, fail_rounds)
        self._pm._append_project_log(
            f"🐛 Bug found in **{spec_name}** → 原地打回（第 {fail_rounds} 轮）"
        )
        # 排队实现器
        self._pm._enqueue(spec_name, "implementer")


    def _do_legacy_fix_spec_bug_found(self, spec_name: str):
        """存量 fix-* SPEC 的 legacy 闭环（design D4：自然终态耗尽）。

        保留原有派生逻辑，直至所有存量 fix 链收敛。
        """
        parent_prio = (self._pm.state_machine.read_one(spec_name) or {}).get("priority", 5)

        # 确定本轮 bug 应使用的 fix SPEC 名称
        fix_spec_name = self._resolve_fix_spec_name(spec_name)
        if fix_spec_name is None:
            self._pm.logger.info(
                "pm_engine",
                f"Legacy fix SPEC for '{spec_name}' already in progress — "
                f"skipping duplicate bug-found handling",
            )
            return

        # ── fix 族谱收敛治理（design D4 legacy）──
        if self._pm.state_machine.read_one(fix_spec_name) is None:
            if self._family_gate_blocked(spec_name, fix_spec_name):
                if self._consume_family_waiver(spec_name):
                    self._pm.logger.warning(
                        "pm_engine",
                        f"family_explosion 人工放行：'{spec_name}' 本轮豁免一次，"
                        f"继续创建 {fix_spec_name}",
                    )
                else:
                    detail = (f"深度={self._fix_prefix_depth(fix_spec_name)}, "
                              f"宽度={self._family_width(fix_spec_name)}")
                    self._signal_family_explosion(spec_name, fix_spec_name, detail)
                    return
            elif self._family_waiver_set(spec_name):
                self._consume_family_waiver(spec_name)

        self._ensure_fix_spec_files(fix_spec_name, spec_name)

        existing_fix = self._pm.state_machine.read_one(fix_spec_name)
        if existing_fix:
            guard_status = existing_fix.get("status", "")
            if guard_status in (
                "implementing", "testing", "implemented",
                "verified", "done", "pushed",
                "blocked",
            ):
                self._pm.logger.info(
                    "pm_engine",
                    f"Fix SPEC '{fix_spec_name}' 处于 '{guard_status}' "
                    f"— bug-found 重发幂等守卫：跳过重置，保留状态与 run 字段",
                )
            else:
                self._pm.logger.info(
                    "pm_engine",
                    f"Fix SPEC '{fix_spec_name}' already exists "
                    f"(status={guard_status}) — resetting to ready",
                )
                reset_fields = {
                    "status": "ready",
                    "error": f"Re-triggered from bug found in {spec_name}",
                }
                if existing_fix.get("implementer_run") is None:
                    reset_fields["implementer_run"] = None
                if existing_fix.get("tester_run") is None:
                    reset_fields["tester_run"] = None
                self._pm.state_machine.update_spec(fix_spec_name, reset_fields)
                self._pm._on_spec_ready(fix_spec_name)
        else:
            self._pm.state_machine.add_spec(fix_spec_name, {
                "status": "ready",
                "priority": min(parent_prio + 1, 10),
                "branch": None,
                "error": f"Auto-created from bug found in {spec_name}",
            })
            self._pm.logger.info("pm_engine", f"Created fix SPEC: {fix_spec_name}")

        self._pm._append_project_log(
            f"🐛 Bug found in **{spec_name}** → scheduling legacy **{fix_spec_name}**"
        )
        self._pm._enqueue(fix_spec_name, "implementer")


    def _inject_verify_fix_task(self, spec_name: str, fail_rounds: int):
        """在父 SPEC 的 tasks.md 末尾追加/更新「## 验证修复」任务段。

        - 首次失败：追加新段
        - 后续失败：更新段内轮数注记
        MUST NOT 改写既有任务与勾选状态（design D3）。
        """
        tasks_path = self._pm.project_root / "openspec" / "changes" / spec_name / "tasks.md"
        if not tasks_path.exists():
            self._pm.logger.warning(
                "pm_engine",
                f"tasks.md 不存在，跳过验证修复段注入：{spec_name}",
            )
            return

        try:
            text = tasks_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return

        report_path = f"openspec/changes/{spec_name}/verification-report.md"
        section = (
            f"\n\n## 验证修复（第 {fail_rounds} 轮失败）\n\n"
            f"- [ ] 阅读 `{report_path}`，定位「真实产品 Bug」并修复\n"
            f"- [ ] 修复后重跑验证确认通过\n"
        )

        m = self._pm._VERIFY_FIX_SECTION_RE.search(text)
        if m:
            # 已有验证修复段：替换为新轮数版本
            # 找到段的起始位置（含前一个 \n\n），到段尾
            start = m.start()
            # 向前找到段落分隔
            while start > 0 and text[start - 1] == '\n':
                start -= 1
            # 向后找到下一个段落标题或文件末尾
            after = text[m.end():]
            next_heading = re.search(r"\n## [^验]", after)
            if next_heading:
                end = m.end() + next_heading.start() + 1  # 包含 \n
            else:
                end = len(text)
            new_text = text[:start] + section.strip() + "\n" + text[end:]
        else:
            # 无现有段：追加到末尾
            new_text = text.rstrip("\n") + section

        tasks_path.write_text(new_text, encoding="utf-8")
        self._pm.logger.info(
            "pm_engine",
            f"验证修复段已{'更新' if m else '注入'}：{spec_name}（第 {fail_rounds} 轮）",
        )


    def _send_human_escalation_alert(
        self, spec_name: str, signal_type: str, severity: str,
        description: str, evidence: str, recommended_action: str,
        trigger: Optional[dict] = None,
    ):
        """发送 human-escalation-alerts 告警（escalation 种类）写入 admin store。

        add-alert-auto-resolve D2：条目附带结构化触发条件（trigger 字段，含
        type/spec/condition），供闭环判定直接消费、无需解析自然语言 description。
        trigger 缺省时按 signal_type 从闭环枚举推导（接入点集中在此一处）；
        未接入枚举的 signal_type 不写 trigger、永不自动闭环（保守默认）。
        """
        from core.admin_store import AdminStore, ESCALATION
        from core.alert_lifecycle import build_trigger
        store = AdminStore(self._pm.project_root, self._pm.logger)
        if trigger is None:
            trigger = build_trigger(signal_type, spec_name)
        try:
            entry = {
                "kind": ESCALATION,
                "signal_type": signal_type,
                "spec": spec_name,
                "severity": severity,
                "description": description,
                "evidence": evidence,
                "recommended_action": recommended_action,
            }
            if trigger:
                entry["trigger"] = trigger
            store.append(entry)
            self._pm.logger.warning(
                "pm_engine",
                f"human-escalation-alert: {signal_type} for '{spec_name}'",
            )
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"Failed to send escalation alert for '{spec_name}': {e}",
            )
