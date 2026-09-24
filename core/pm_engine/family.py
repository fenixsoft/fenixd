"""family.py — FamilyGovernor：fix 家族治理（谱系解析/家族门/waiver/sibling 修复互斥/族谱爆炸信号/bug-found 打回与人工升级）（refactor-core-packages 阶段 4）。

无状态组件：SPEC 状态全部经门面回引 self._pm.state_machine 落在
STATE.md（design D3 规则 3），本组件不持有实例状态。

"""

from typing import Optional
import json
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
        spec_dir = self._pm.project_root / "spec" / "changes" / fix_spec_name
        spec_dir.mkdir(parents=True, exist_ok=True)

        proposal = (
            f"# Proposal: 修复 {parent_spec_name} 验证发现的缺陷\n\n"
            f"## Why\n\n"
            f"`{parent_spec_name}` 的验证报告发现产品缺陷，导致验证未通过。"
            f"详见 `spec/changes/{parent_spec_name}/verification-report.md` 的「真实产品 Bug」部分。\n\n"
            f"## What Changes\n\n"
            f"第一步必须复核失败场景的有效性（fix-fake-failure-first）："
            f"验证场景自身可能存在断言缺陷（如英文状态字面量 vs 产品中文渲染、"
            f"不存在的选择器、错误的前置数据），伪失败修复应改场景文件而非产品代码。"
            f"复核确认为真实产品 Bug 后，先阅读父 SPEC 的 `verification-report.md`，"
            f"定位每个真实产品 Bug 的根因并修复。\n\n"
            f"## Impact\n\n"
            f"- **代码**：按复核结论修复场景缺陷或真实产品缺陷\n"
            f"- **行为**：修复后，父 SPEC 验证报告中失败的场景应转为通过\n"
        )
        tasks = (
            f"# Tasks: 修复 {parent_spec_name} 验证发现的缺陷\n\n"
            f"## 1. 复核失败场景有效性（先于一切修复）\n\n"
            f"- [ ] 1.1 逐条核对 `spec/changes/{parent_spec_name}/verification-report.md` "
            f"中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为/DOM 是否相符；"
            f"断言与产品不符属场景缺陷——修场景文件，不改产品代码；"
            f"确属产品行为不符才进入第 2 步\n\n"
            f"## 2. 修复真实产品缺陷（仅当复核确认为真 Bug）\n\n"
            f"- [ ] 2.1 按 `verification-report.md` 的「真实产品 Bug」定位根因并修复；"
            f"场景缺陷则直接修正场景文件\n\n"
            f"## 3. 验证与打包\n\n"
            f"- [ ] 3.1 运行 `npm run build`（tsc + vite build）确认编译与构建通过\n"
            f"- [ ] 3.2 运行框架单元测试（`python3 -m pytest .fenix/tests/ -v`）确认无回归\n"
            f"- [ ] 3.3 执行 `bash scripts/package.sh` 生成最新扩展包\n"
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
            s = s[len("fix-") :]
        return depth

    @staticmethod
    def _fix_strip_all(name: str) -> str:
        """剥除全部连续 `fix-` 前缀，得到家族根名（fix-fix-x → x）。"""
        return (
            name[4 * FamilyGovernor._fix_prefix_depth(name) :] if name.startswith("fix-") else name
        )

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
        # 非法配置值回退默认（对齐 engine._ready_stall_threshold_minutes 的
        # 容错口径）：族谱门是 bug-found 主链路，配置写坏不得中断处置。
        try:
            max_depth = int(iw if iw is not None else 3)
        except (TypeError, ValueError):
            max_depth = 3
        try:
            max_width = int(ns if ns is not None else 2)
        except (TypeError, ValueError):
            max_width = 2
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
                        (e for e in self._pm._run_queue if e[1] == sib and e[2] == "implementer"),
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
            # 精确前缀归属守卫（对齐 queries.find_implementer_worktree 范式）：
            # 子串匹配会把同根后代 fix-fix-x 的 worktree 误记到 fix-x 头上
            for d in wt_root.iterdir():
                if not d.is_dir():
                    continue
                if d.name.startswith(f"impl-{spec_name}-") or d.name.startswith(
                    f"verify-{spec_name}-"
                ):
                    r = _sp.run(
                        ["pgrep", "-f", f"worktrees/{d.name}"],
                        capture_output=True,
                        text=True,
                        timeout=10,
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
            store.append(
                {
                    "kind": SIGNAL,
                    "signal_type": "family_explosion",
                    "spec": parent_name,
                    "severity": "major",
                    "description": (
                        f"fix 族谱爆炸：'{parent_name}' 派生 {child_name} 被"
                        f"深度/宽度上限拦截（{detail}），自动创建已中止"
                    ),
                    "evidence": f"candidate={child_name}; {detail}",
                    "recommended_action": (
                        "人工检修根因环境；若确认放行一次，对该父 SPEC "
                        "设置 _family_waiver=true（下轮允许再创建一个子 SPEC）"
                    ),
                }
            )
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

    # ── 失败历史分类与证据（fix-verdict-retry-misattribution D6）─────────
    @staticmethod
    def _classify_fail_history(history: list) -> list:
        """为失败历史每轮标注分型与相邻轮 failed_scenarios diff。

        - repeat：该轮 failed_scenarios 与上一轮完全相同（无进展信号）；
        - 否则按 cause_type：evidence-invalid / real-bugs；
        - 侧车缺失（history 为空）→ 全轮标注 unknown。
        """
        if not history:
            return []
        out = []
        prev_set = None
        for r in history:
            scenarios = [str(s) for s in (r.get("failed_scenarios") or [])]
            cur_set = set(scenarios)
            ftype = r.get("cause_type") or "unknown"
            if prev_set is not None and cur_set == prev_set:
                ftype = "repeat"
            if ftype not in ("evidence-invalid", "real-bugs", "repeat"):
                ftype = "unknown"
            if prev_set is None:
                diff = {"added": sorted(cur_set), "removed": [], "persisted": []}
            else:
                diff = {
                    "added": sorted(cur_set - prev_set),
                    "removed": sorted(prev_set - cur_set),
                    "persisted": sorted(cur_set & prev_set),
                }
            out.append(
                {
                    "round": r.get("round"),
                    "type": ftype,
                    "cause_type": r.get("cause_type"),
                    "scenarios": sorted(cur_set),
                    "diff_vs_prev": diff,
                }
            )
            prev_set = cur_set
        return out

    @staticmethod
    def _format_fail_history_evidence(classified: list, fail_rounds: int) -> str:
        """格式化升级闸门告警 evidence：分型摘要 + 相邻轮 diff 明细。"""
        if not classified:
            return (
                f"failure_profile=unknown（fail_history 缺失或首轮即触发冻结，"
                f"侧车无足够数据）; fail_rounds={fail_rounds}"
            )
        parts = [f"fail_rounds={fail_rounds}"]
        type_summary = [f"round{c.get('round')}:{c.get('type')}" for c in classified]
        parts.append(f"failure_profile={'; '.join(type_summary)}")
        for c in classified:
            d = c["diff_vs_prev"]
            round_num = c.get("round")
            parts.append(
                f"diff[round{round_num}]: "
                f"added={d['added']} removed={d['removed']} "
                f"persisted={d['persisted']}"
            )
        repeats = [c for c in classified if c.get("type") == "repeat"]
        if repeats:
            rounds = [c.get("round") for c in repeats]
            parts.append(
                f"repeat_rounds={rounds}"
                f"（与上一轮失败场景集完全相同，相邻轮 diff 为空——"
                f"可能属「根因已修复但闸门仍冻结」的误置情形，建议人工核对）"
            )
        return "; ".join(parts)

    def _do_spec_bug_found(self, spec_name: str, failure_class: str = "product", run_id: str = ""):
        """实际执行 bug-found 处理逻辑。

        分流依据（add-bug-repair-mode-config D2）：`admin.bug_repair_mode` 有效值
        取代 SPEC 名称前缀（`_is_fix_spec` 分流退役）。每次 bug-found 事件实时读取
        配置（经 get_admin_config 同源路径，不做实例级缓存）——与配置热更新（30s
        mtime）语义对齐，切换模式后下一次事件即按新值生效。
        - inplace（含未配置缺省）：对任何 SPEC（含 fix-* 名字）原地打回重修；
        - derive：派生 fix-* 子 SPEC（守卫一、族谱收敛 governor、_resolve_fix_spec_name
          逐级命名、done→父重验闭环全部保留生效）。

        evo-infra-failure-budget-exempt R3：``failure_class`` 三态归因——
        仅 product（unknown 按 product 保守处置）累加 ``_verify_fail_rounds``；
        infra 轮**不进本分支**（防御性守卫，正常由归因入口改走
        ``_record_infra_failure`` 记账，不递增闸门计数、不冻结、不派生 fix）。
        """
        # ── infra 防御性守卫（evo-infra-failure-budget-exempt R3）──
        # 调用方应在统一归因入口（enrich_failure_class 判定处）拦截 infra：
        # 记 _verify_infra_rounds + 预算退款 + 台账 failure_class=infra，
        # 不调用本函数。此处兜底：即使误入也绝不递增 _verify_fail_rounds
        # （infra 轮与 product 轮同计会虚增冻结计数，验收「闸门不累加」落空）。
        if failure_class == "infra":
            self._pm.logger.warning(
                "pm_engine",
                f"infra 归因误入 bug-found 分支 '{spec_name}' — 抑制闸门递增"
                f"（本分支仅 product/unknown 类）",
            )
            return

        from core.config import ConfigLoader

        mode = ConfigLoader.get_admin_config(self._pm.config).get("bug_repair_mode", "inplace")

        if mode == "derive":
            # ── derive 模式：派生 fix-* 子 SPEC（可配置保留的 legacy 派生闭环）──
            # 守卫一（fix-repair-lane-dedup）：fix spec 已有非终态子 fix 时抑制 reset
            carrier = self._has_non_terminal_child_fix(spec_name)
            if carrier:
                self._pm.logger.info(
                    "pm_engine",
                    f"守卫一：'{spec_name}' 为 fix spec 且已有非终态子 fix "
                    f"'{carrier}' 承载修复——抑制 reset，保持 bug-found",
                )
                self._pm.state_machine.update_spec(
                    spec_name,
                    {
                        "error": f"修复由子 fix '{carrier}' 承载，抑制重实现重置",
                    },
                )
                return
            # 派生闭环（守卫一 + 族谱 governor + _resolve_fix_spec_name 在函数内生效）
            self._do_legacy_fix_spec_bug_found(spec_name)
            return

        # ── inplace 模式（含未配置缺省）：原地打回（inplace-bug-repair D1-D3）──
        # 对任何 SPEC 生效，包括名称带 fix- 前缀的 SPEC（名称前缀分流已退役）。
        entry = self._pm.state_machine.read_one(spec_name) or {}
        # judge-rerun-stability R1：judge 重跑 hard cap 触发（_judge_cap_frozen）
        # 时 _verify_fail_rounds 一并冻结——不再递增（spec 已 blocked 等待人工，
        # 计数器保持冻结值，防止解冻后从旧值继续误累积）。
        if entry.get("_judge_cap_frozen"):
            self._pm.logger.warning(
                "pm_engine",
                f"judge hard cap 冻结期间 '{spec_name}' 的 _verify_fail_rounds "
                f"冻结递增（保持 {entry.get('_verify_fail_rounds', 0)}）",
            )
            return
        fail_rounds = 0
        try:
            fail_rounds = int(entry.get("_verify_fail_rounds", 0) or 0)
        except (TypeError, ValueError):
            fail_rounds = 0
        fail_rounds += 1

        # ── 失败历史侧车（fix-verdict-retry-misattribution D6 + R3）──
        # 本轮 bug-found 采纳 = 真缺陷失败轮（cause_type=real-bugs），记入侧车供
        # 升级闸门分型与轮间 diff。写盘失败静默降级（分型 unknown，不阻断闸门）。
        # failure_class=product（或 unknown）随 R3 回拨参考台账记入。
        self._pm._append_fail_history(
            spec_name,
            "real-bugs",
            self._pm._failed_scenario_ids(spec_name),
            failure_class=failure_class,
            run_id=run_id,
        )

        if fail_rounds >= MAX_VERIFY_FAIL_ROUNDS:
            # ── 升级闸门：冻结为 blocked + human-escalation-alerts 告警 ──
            history = self._pm._read_fail_history(spec_name)
            classified = self._classify_fail_history(history)
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "_verify_fail_rounds": fail_rounds,
                    "status": "blocked",
                    "error": (
                        f"升级闸门连续失败第 {fail_rounds} 轮，已冻结等待人工裁决。"
                        f"详见 `spec/changes/{spec_name}/verification-report.md`"
                    ),
                },
            )
            self._pm.logger.error(
                "pm_engine",
                f"升级闸门：'{spec_name}' 升级闸门连续失败第 {fail_rounds} 轮，"
                f"冻结为 blocked，等待人工裁决",
            )
            self._send_human_escalation_alert(
                spec_name=spec_name,
                signal_type="verify_fail_escalation",
                severity="major",
                description=(
                    f"'{spec_name}' 升级闸门连续失败第 {fail_rounds} 轮，" f"已冻结等待人工裁决"
                ),
                evidence=(
                    f"spec={spec_name}; "
                    + self._format_fail_history_evidence(classified, fail_rounds)
                    + f"; report=spec/changes/{spec_name}/verification-report.md"
                ),
                recommended_action=(
                    "检查验证报告定位根因，人工调整 SPEC 状态后重跑验证；"
                    "人工重置计数器即重新获得自动修复机会"
                ),
            )
            # 失败历史已被本次告警消费，清空侧车避免陈旧记录污染下一链条
            self._pm._clear_fail_history(spec_name)
            return

        # ── 正常打回：递增计数 + 重置 implementing + 注入修复任务 ──
        self._pm.state_machine.update_spec(
            spec_name,
            {
                "_verify_fail_rounds": fail_rounds,
                "status": "implementing",
                "error": (f"验证失败（原地打回第 {fail_rounds} 轮），重修中"),
            },
        )
        self._pm.logger.warning(
            "pm_engine",
            f"原地打回第 {fail_rounds} 轮：'{spec_name}' 验证失败，"
            f"重置为 implementing 并注入修复任务",
        )
        # 注入 tasks.md「验证修复」段
        self._inject_verify_fix_task(spec_name, fail_rounds)
        self._pm._append_project_log(
            f"🐛 Bug found in **{spec_name}** → 原地打回第 {fail_rounds} 轮"
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
                    detail = (
                        f"深度={self._fix_prefix_depth(fix_spec_name)}, "
                        f"宽度={self._family_width(fix_spec_name)}"
                    )
                    self._signal_family_explosion(spec_name, fix_spec_name, detail)
                    return
            elif self._family_waiver_set(spec_name):
                self._consume_family_waiver(spec_name)

        existing_fix = self._pm.state_machine.read_one(fix_spec_name)
        guard_status = (existing_fix or {}).get("status", "")
        # 模板写入守卫（与下方幂等守卫对齐）：仅当 fix SPEC 不存在或状态属
        # 待重置集时写入模板文件；implementing/implemented 等在途状态的
        # tasks.md 已含勾选进度与修复结论、proposal.md 可能经人工细化，
        # 重写空白模板会丢失这些内容。
        if existing_fix is None or guard_status not in (
            "implementing",
            "testing",
            "implemented",
            "verified",
            "done",
            "pushed",
            "blocked",
        ):
            self._ensure_fix_spec_files(fix_spec_name, spec_name)

        if existing_fix:
            if guard_status in (
                "implementing",
                "testing",
                "implemented",
                "verified",
                "done",
                "pushed",
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
            self._pm.state_machine.add_spec(
                fix_spec_name,
                {
                    "status": "ready",
                    "priority": min(parent_prio + 1, 10),
                    "branch": None,
                    "error": f"Auto-created from bug found in {spec_name}",
                },
            )
            self._pm.logger.info("pm_engine", f"Created fix SPEC: {fix_spec_name}")

        self._pm._append_project_log(
            f"🐛 Bug found in **{spec_name}** → scheduling legacy **{fix_spec_name}**"
        )
        self._pm._enqueue(fix_spec_name, "implementer")

    def _read_prev_impl_conclusions(self, spec_name: str) -> str:
        """读取上一轮 implementer 的收工结论，作为修复段的「上轮实现结论」小节。

        背景（fast-track 复盘，2026-09-02）：verify-repair 每轮的 implementer
        都要花 30+ 分钟从源码重新推导上轮已查明的结论（验证测的是哪个 dist、
        失败是场景缺陷还是产品 bug 等）——根目录 result 的 summary 是唯一载体，
        却从未传给下一轮。无记忆传递的重派是重复烧钱的固定根因
        （fix-startup-double-dispatch 处置：38% 纯重复）。

        主树 .fenix/.fenix-run-result.json 是跨 spec 共享文件：spec 字段不匹配
        （并发派发的其它 spec 的结果）时不注入，防跨 spec 污染。命中时同时
        持久化 per-spec 副本到 .fenix/verify-progress/<spec>/prev-impl-result.json
        （根文件会被后续 run 覆盖，副本供人工与后续轮次回溯）。
        """
        result_path = self._pm.project_root / ".fenix" / ".fenix-run-result.json"
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        if not isinstance(data, dict) or data.get("spec") != spec_name:
            return ""
        try:
            snap_dir = self._pm.project_root / ".fenix" / "verify-progress" / spec_name
            snap_dir.mkdir(parents=True, exist_ok=True)
            (snap_dir / "prev-impl-result.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
        summary = str(data.get("summary") or "").strip()[:800]
        findings = data.get("findings") or []
        if not summary and not findings:
            return ""
        lines = ["", "### 上轮实现结论（自动携带，来自上一轮 implementer 收工结论）", ""]
        if summary:
            lines += [summary, ""]
        if findings:
            lines.append("上轮登记的 findings：")
            for f in findings[:5]:
                if isinstance(f, dict):
                    lines.append(
                        f"- {f.get('type', '?')}: {f.get('element', '')}"
                        f" — {f.get('suggestion') or f.get('current', '')}"
                    )
                else:
                    lines.append(f"- {f}")
            lines.append("")
        return "\n".join(lines)

    def _inject_verify_fix_task(self, spec_name: str, fail_rounds: int):
        """在父 SPEC 的 tasks.md 末尾追加/更新「## 验证修复」任务段。

        - 首次失败：追加新段
        - 后续失败：更新段内轮数注记
        MUST NOT 改写既有任务与勾选状态（design D3）。
        """
        tasks_path = self._pm.project_root / "spec" / "changes" / spec_name / "tasks.md"
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

        report_path = f"spec/changes/{spec_name}/verification-report.md"
        # fix-fake-failure-first：第一步强制复核失败场景有效性——验证场景自身
        # 的断言缺陷（英文状态字面量 vs 产品中文渲染、不存在选择器等）曾被当作
        # 产品 Bug 触发整条修复链（3 轮实现 5.24h 修一个不存在的 bug）。
        prev = self._read_prev_impl_conclusions(spec_name)
        section = (
            f"\n\n## 验证修复（原地打回第 {fail_rounds} 轮）\n"
            f"{prev}"
            f"\n- [ ] 先复核失败有效性：逐条核对 `{report_path}` 中失败场景的期望断言"
            f"（状态字面量/选择器/前置数据）与产品实际行为是否相符——"
            f"断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码\n"
            f"- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码\n"
            f"- [ ] 修复后重跑验证确认通过\n"
        )

        m = self._pm._VERIFY_FIX_SECTION_RE.search(text)
        if m:
            # 已有验证修复段：替换为新轮数版本
            # 找到段的起始位置（含前一个 \n\n），到段尾
            start = m.start()
            # 向前找到段落分隔
            while start > 0 and text[start - 1] == "\n":
                start -= 1
            # 向后找到下一个二级标题或文件末尾。MUST NOT 排除「验」字（item
            # 255393413ec3）：本段内部不含二级标题，「## 验收标准」等以「验」
            # 开头的后续标题也是合法段界——排除会把整段误并入替换区间删掉。
            after = text[m.end() :]
            next_heading = re.search(r"\n## ", after)
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
            f"验证修复段已{'更新' if m else '注入'}：{spec_name}（原地打回第 {fail_rounds} 轮）",
        )

    def _send_human_escalation_alert(
        self,
        spec_name: str,
        signal_type: str,
        severity: str,
        description: str,
        evidence: str,
        recommended_action: str,
        trigger: Optional[dict] = None,
    ):
        """发送 human-escalation-alerts 告警（escalation 种类）写入 admin store。

        add-alert-auto-resolve D2：条目附带结构化触发条件（trigger 字段，含
        type/spec/condition），供闭环判定直接消费、无需解析自然语言 description。
        trigger 缺省时按 signal_type 从闭环枚举推导（接入点集中在此一处）；
        未接入枚举的 signal_type 不写 trigger、永不自动闭环（保守默认）。

        降噪分级（2026-09-01 用户决策）：仅 critical/major 进人工待处理队列；
        warning/minor 写入即标记 handled，只留历史记录不弹横幅。
        """
        from core.admin_store import AdminStore, ESCALATION, severity_needs_human
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
            # add-human-adjudication-choices 2.1-2.5：桶 2 发射点接线（D1「发射点
            # 只引用注册表」+ D2「写告警时快照」）——按 signal_type 从裁决选项
            # 注册表取 choices 并入告警记录。本单点是全部 ESCALATION 告警的
            # 共同写入口（预算耗尽/升级闸门/评审两族/judge 重跑上限/同因重派
            # 熔断/恢复期 human_alert_callback 均汇聚于此），注册表未覆盖的
            # 信号（桶 0 知情/自愈类等）返回空集、不写该字段——MUST NOT 携带。
            from core.dashboard.data.adjudication_choices import choices_for

            choices = choices_for(signal_type)
            if choices:
                entry["choices"] = list(choices)
            rec = store.append(entry)
            if not severity_needs_human(severity):
                store.mark_handled(rec["id"])
            self._pm.logger.warning(
                "pm_engine",
                f"human-escalation-alert: {signal_type} for '{spec_name}'",
            )
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"Failed to send escalation alert for '{spec_name}': {e}",
            )
