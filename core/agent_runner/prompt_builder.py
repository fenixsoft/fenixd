"""prompt_builder.py — PromptBuilder：Agent 提示词构建。

通用 prompt 主体文件化（add-agent-prompt-files D1）：六类 agent 的静态主体
存于框架根 agents/<agent-type>.md（唯一真相，无内置副本），加载时以
str.replace 填充路径类占位符（{spec_name}/{spec_dir}/{scenarios_path}/
{result_path}/{report_path}/{progress_path}，administrator 另有困境信号
字段占位符）；不用 str.format——prompt 正文含大量 {} JSON 示例。条件动态段
（REPLAN 反馈、断点续跑、上轮 error、遗产、场景冻结、交互契约、复核清单、
verdict 退回）仍由代码按状态追加。文件缺失派发显式报错。
跨域依赖（state_machine/worktree_manager/验证进度读取等）经门面回引
self._pm，不在本组件持有状态。
"""

import json
from pathlib import Path

# 框架根（与 core/spec_gen.py SCHEMA_DIR 同型推导）；agents/ 提示词目录
FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
AGENT_PROMPT_DIR = FRAMEWORK_ROOT / "agents"

# 六类 agent → 提示词文件名（agent-type 白名单的单一来源，Dashboard 端点复用）
AGENT_PROMPT_FILES = {
    "implementer": "implementer.md",
    "verifier": "verifier.md",
    "planner-plan": "planner-plan.md",
    "planner-judge": "planner-judge.md",
    "fast-track": "fast-track.md",
    "administrator": "administrator.md",
}


class PromptBuilder:
    """Agent 提示词构建器（门面 AgentRunner 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

    # ── 通用层文件加载与占位符（add-agent-prompt-files D1）────────────

    def agent_prompt_path(self, agent_type: str) -> Path:
        """agent-type → 提示词文件路径；未知类型抛 ValueError（fail-fast）。"""
        rel = AGENT_PROMPT_FILES.get(agent_type)
        if rel is None:
            raise ValueError(
                f"未知 agent 类型: {agent_type}（合法: {', '.join(sorted(AGENT_PROMPT_FILES))}）"
            )
        return AGENT_PROMPT_DIR / rel

    def _load_agent_template(self, agent_type: str) -> str:
        """加载 agents/<agent-type>.md；文件缺失显式报错，不回退内置副本。"""
        path = self.agent_prompt_path(agent_type)
        if not path.is_file():
            raise FileNotFoundError(
                f"agent 提示词文件缺失: {path} — agents/ 是 prompt 唯一真相，"
                "不回退内置副本（add-agent-prompt-files D1）"
            )
        return path.read_text(encoding="utf-8")

    def _fill_placeholders(self, template: str, agent_type: str,
                           spec_name: str, detail: dict | None) -> str:
        """占位符填充：逐键 str.replace（正文含大量 {} JSON 示例，禁用 str.format）。

        progress_path 语义按 agent 现行为保持：verifier 写
        verify-progress/<spec>.json；fast-track 写 verify-progress/<spec>/<spec>.json。
        administrator 困境信号字段由 detail 注入（其余 agent 文件不含这些占位符）。
        """
        root = self._pm.project_root
        vp_dir = root / ".fenix" / "verify-progress" / spec_name
        sig = detail or {}
        values = {
            "{spec_name}": spec_name,
            "{spec_dir}": f"openspec/changes/{spec_name}",
            "{scenarios_path}": str(vp_dir / "test_scenarios.json"),
            "{result_path}": str(vp_dir / ".fenix-run-result.json"),
            "{report_path}": str(vp_dir / "report.json"),
        }
        if agent_type == "verifier":
            values["{progress_path}"] = str(
                root / ".fenix" / "verify-progress" / f"{spec_name}.json")
        elif agent_type == "fast-track":
            values["{progress_path}"] = str(vp_dir / f"{spec_name}.json")
        values.update({
            "{sig_type}": sig.get("signal_type") or "unknown",
            "{sig_spec}": sig.get("spec") or spec_name,
            "{severity}": sig.get("severity") or "major",
            "{description}": sig.get("description") or "",
            "{evidence}": sig.get("evidence") or "",
            "{recommendation}": sig.get("recommended_action") or "",
            "{disp_path}": str(sig.get("disposition_path")
                               or (root / ".fenix" / "admin_disposition.json")),
            "{dash_script}": f"{root}/.fenix/bin/fenix_dashboard.py",
        })
        out = template
        for key, val in values.items():
            out = out.replace(key, val)
        return out

    def _build_prompt(self, spec_name: str, agent_type: str, detail: dict | None = None) -> str:
        """构建 claude CLI prompt：文件主体 + 占位符填充 + 动态段按状态追加。

        detail: 可选。administrator 分支接收困境信号 dict。
        """
        template = self._load_agent_template(agent_type)
        prompt = self._fill_placeholders(template, agent_type, spec_name, detail)

        if agent_type == "implementer":
            # 上轮 error 上下文注入（add-implementer-deliverable-gate D4）+
            # 恢复重派遗产上下文（add-recovery-legacy-check 2.1/2.2）。
            prompt += self._prev_error_section(spec_name)
            prompt += self._build_legacy_section(spec_name)
        elif agent_type == "verifier":
            prompt += self._verifier_breakpoint_section(spec_name)
        elif agent_type == "planner-plan":
            prompt += self._replan_feedback_section(spec_name)
            prompt += self._scenario_freeze_section(spec_name)
            prompt += self._interaction_contract_section(spec_name)
            prompt += self._triage_recheck_section(spec_name)
        elif agent_type == "planner-judge":
            prompt += self._scenario_freeze_section(spec_name)
            prompt += self._triage_recheck_section(spec_name)
            prompt += self._verdict_rejection_section(spec_name)
        elif agent_type == "fast-track":
            # 上轮 error + worktree 继承说明（fast-track 打回重派对齐）：
            # 之前只有 implementer 分支注入 prev_error，fast-track 打回后新 run
            # 完全不知道上次为何失败（fix-implementer-task-progress 三连打回）。
            prompt += self._scenario_freeze_section(spec_name)
            prompt += self._interaction_contract_section(spec_name)
            prompt += self._designed_ids_line(
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / "test_scenarios.json"
            )
            prompt += self._prev_error_section(spec_name)
            prompt += self._fast_track_reuse_note(spec_name)
        # administrator 无条件动态段：困境信号经占位符注入

        # 项目级附加提示词（D2）：附加在完整 prompt（通用主体 + 动态段）之后
        prompt += self._project_extra_section(agent_type)
        return prompt

    def _project_extra_section(self, agent_type: str) -> str:
        """项目级附加提示词段（add-agent-prompt-files D2 / 任务 2.1）。

        <项目根>/.fenix/agents/<agent-type>.md 存在则读入，以
        「## 项目附加提示词」标题附加在 prompt 完整内容（通用主体 + 动态段）
        之后；缺席零注入（prompt 与仅通用层时逐字节一致）。
        自引用项目跳过（D4/任务 2.3）——其项目级即通用层。
        """
        agents_dir = self._project_agents_dir()
        if agents_dir is None:
            return ""
        path = agents_dir / AGENT_PROMPT_FILES[agent_type]
        if not path.is_file():
            return ""
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        if not content:
            return ""
        return f"\n\n## 项目附加提示词\n\n{content}\n"

    def _project_agents_dir(self):
        """项目级 agents 目录；自引用项目返回 None（任务 2.3）。

        两重检测（add-agent-prompt-files D4）：
        - 项目根与框架根解析为同一路径（fenixd 自身项目）；
        - 项目 .fenix 符号链接解析为框架根（自引用——项目级 .fenix/agents/
          即通用层 agents/，读取注入等于自我重复，写入会覆盖不可改的通用文件）。
        """
        proot = Path(self._pm.project_root)
        try:
            if proot.resolve() == FRAMEWORK_ROOT.resolve():
                return None
            if (proot / ".fenix").resolve() == FRAMEWORK_ROOT.resolve():
                return None
        except OSError:
            pass
        return proot / ".fenix" / "agents"

    def _verifier_breakpoint_section(self, spec_name: str) -> str:
        """断点续跑段（verifier-checkpoint-resume spec）。

        读取上次 attempt 的进度文件，存在且 done>0 时把断点信息注入提示词，
        让新 agent 从 done+1 场景继续，不再从头重跑。文件缺失 / done==0 /
        JSON 损坏 → 不注入、全新开始，损坏文件移除以免污染后续 attempt。
        """
        progress = self._pm._read_verify_progress(spec_name)
        if progress is None:
            return ""
        total = progress.get("total")
        done = progress.get("done") or 0
        current = progress.get("current") or ""
        if not (isinstance(done, int) and done > 0):
            return ""
        initial_done = done
        start_scenario = done + 1
        return (
            f"\n⚠️ RESUME CHECKPOINT (断点续跑) — 你是从上次中断处续跑的验证 Agent。\n"
            f"上次验证进度：total={total}, done={done}, 上次进行中的场景: '{current}'\n"
            f"指令：\n"
            f"  1. 跳过已完成的 {done} 个场景，从第 {start_scenario} 个场景开始执行\n"
            f"     （场景总数保持 {total} 不变，不要重新数；已完成的场景视为已通过）。\n"
            f"  2. 首次写入进度时直接写 done={initial_done}（不要重置为 0），"
            f"之后每完成一个场景将 done 递增 1 并更新 current。\n"
            f"  3. 直至 done 达到 {total}，写入 done={total} 与最终结果。\n"
            f"  4. 不要重复执行已完成场景的截图/报告，但需确保本次从断点起的场景全部真实在\n"
            f"     浏览器中跑通（DOM snapshot 文本验证）。\n\n"
        )

    def _replan_feedback_section(self, spec_name: str) -> str:
        """REPLAN 反馈内联段（fix-replan-feedback-injection）。

        验收退回时把上一轮错误清单直接内联进 prompt——此前只写
        REPLAN_FEEDBACK.md 靠 agent 自觉去读，实测 planner 会无视。文件
        缺失 / 读取失败 → 返回空串（不注入）。
        """
        replan_fb_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "REPLAN_FEEDBACK.md"
        )
        if not replan_fb_path.exists():
            return ""
        try:
            fb_text = replan_fb_path.read_text(encoding="utf-8")[:3000]
        except OSError:
            return ""
        return (
            f"\n## ⚠️ 上一轮场景验收未通过（MANDATORY：逐条修复后再输出）\n\n"
            f"{fb_text}\n\n"
            f"上述错误清单来自验收器，必须在本轮输出中全部修正；"
            f"若沿用上一轮场景文件原样重写，验收将再次拒绝并消耗重排预算。\n"
        )

    def _prev_error_section(self, spec_name: str) -> str:
        """上轮 error 上下文注入段（add-implementer-deliverable-gate D4）。

        implementer 与 fast-track 共用：打回重派 run 携带上次失败原因，agent
        无需重新考古即知补什么。无 error 时返回空串（prompt 与现状逐字节一致）。
        """
        prev_error = ""
        try:
            entry = self._pm.state_machine.read_one(spec_name) or {}
            prev_error = (entry.get("error") or "") if isinstance(entry, dict) else ""
        except Exception:
            prev_error = ""
        if not prev_error:
            return ""
        return (
            f"\n\n## Previous run error (context for this attempt)\n"
            f"The previous implementation attempt failed and was re-dispatched. "
            f"Use this to focus your work — do NOT repeat the same gap:\n"
            f"\n{prev_error}\n"
        )

    def _designed_ids_line(self, scenarios_path) -> str:
        """当前设计集场景 ID 清单行（硬校验比对基准的 prompt 侧可见性）。"""
        designed_ids: list = []
        try:
            if scenarios_path.exists():
                data = json.loads(scenarios_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    designed_ids = [
                        str(s.get("id")) for s in data
                        if isinstance(s, dict) and s.get("id")
                    ]
        except Exception:
            designed_ids = []
        if not designed_ids:
            return ""
        return (
            f"- 当前设计集（上一轮遗留；若与本轮 Phase 2 规划不一致，"
            f"以本轮 Phase 2 重写后的设计集为准）:\n"
            f"  {', '.join(designed_ids)}\n"
        )

    def _fast_track_reuse_note(self, spec_name: str) -> str:
        """worktree 继承说明：本轮在上一轮打回保留的 worktree 中继续（仅复用时注入）。"""
        wm = getattr(self._pm, "worktree_manager", None)
        if wm is None or not hasattr(wm, "get_reuse_record"):
            return ""
        rec = wm.get_reuse_record(spec_name)
        if not rec:
            return ""
        return (
            f"\n## Worktree 继承（worktree-reuse）\n"
            f"本轮 worktree 复用自上一轮未通过框架校验的同 spec run：上一轮已实现的"
            f"代码提交在当前分支上，tasks.md 可能已有勾选。从 tasks.md 第一个未勾选"
            f"项继续，不要重做已完成的工作，不要重置或回滚已有改动。\n"
        )

    def _build_legacy_section(self, spec_name: str) -> str:
        """构建 implementer prompt 的「遗产检查」段（add-recovery-legacy-check 2.1）。

        无在册遗产返回空串（2.2：prompt 与现状逐字节一致）。有遗产时追加：
        - 遗产 worktree 绝对路径、分支名（worktree 模式），或仅分支名（仅分支模式）；
        - 现场快照：worktree 模式为 ``git status --short`` 脏文件（截断 50 行）；
          仅分支模式为 ``git log --oneline main..branch`` 提交快照；
        - 只读约束（不得在遗产内工作，已物理隔离为新 worktree）；
        - 收编 / 弃用自主决策要求与响应格式（含 ``salvaged from <branch>`` 标注）。

        仅分支模式（守卫拒绝重派接入）：守卫拒绝发生在成功收工清理之后，worktree
        已物理删除、仅分支留存完整已提交成果——告知后继 run 让其自主判断收编
        （cherry-pick / checkout 路径）或弃用，而非从零重做无感知。

        worktree_manager 缺失（测试/未初始化）时安全返回空串。快照采集失败时
        降级为「（无法读取快照）」，不阻断注入。
        """
        wm = getattr(self._pm, "worktree_manager", None)
        if wm is None or not hasattr(wm, "get_legacy"):
            return ""
        legacy = wm.get_legacy(spec_name)
        if not legacy:
            return ""
        path = legacy.get("path", "")
        branch = legacy.get("branch", "")
        if path:
            location = (
                f"### 遗产位置\n"
                f"- 路径（只读参考，绝对路径）: `{path}`\n"
                f"- 分支名: `{branch}`\n\n"
                f"### 脏文件快照（git status --short，继承自上轮未完成的工作）\n"
                f"```\n{self._legacy_dirty_snapshot(path)}\n```\n\n"
            )
            context = (
                f"上一次实现 run 在死亡前留下了未提交的半成品 worktree，被保留为「遗产」"
                f"供你参考与收编（框架不担保其内容正确性，决策权在你）。\n\n"
            )
        else:
            location = (
                f"### 遗产位置\n"
                f"- 分支名: `{branch}`（worktree 已按成功收工清理，仅分支留存完整"
                f"已提交成果）\n\n"
                f"### 分支提交快照（相对 main 的新增提交，git log --oneline）\n"
                f"```\n{self._legacy_branch_snapshot(branch)}\n```\n\n"
            )
            context = (
                f"上一次实现 run 自称完成但被收工守卫拒绝合并（缺件/异议见上文 "
                f"Previous run error），worktree 已清理，**完整的已提交成果仍保留在"
                f"分支上**，被登记为「遗产」供你参考与收编（框架不担保其内容满足"
                f"守卫要求，决策权在你）。\n\n"
            )
        return (
            f"\n\n## ⚠️ RECOVERY LEGACY (遗产检查 — 你是从守卫拒绝/死亡 run 的重派)\n"
            f"\n"
            f"{context}"
            f"{location}"
            f"### 边界约束（务必遵守）\n"
            f"- 遗产为**只读参考**：你只能在其中 inspect（cat / git log / git diff），"
            f"**不得**在其中执行任何写操作（不要 Edit/Write/commit；worktree 模式下"
            f"不要把遗产 worktree 作为你的工作目录，也不要在其中继续开发）。\n"
            f"- 你当前的工作目录是**全新的** worktree（与现状一致，物理隔离），所有新工作"
            f"都必须在你自己的 worktree 内进行。\n\n"
            f"### 你的决策权（二选一，框架不强加）\n"
            f"inspect 遗产后，自行决定：\n"
            f"1. **收编 (salvage)**：若遗产中的成果有价值，把对应内容引入你自己的"
            f" worktree（worktree 模式：复制文件内容并适配后提交；仅分支模式："
            f"`git cherry-pick <commit>` 或 `git checkout {branch} -- <path>`）、"
            f"适配后提交，并在提交信息中注明来源分支，格式：\n"
            f"   `[fenix] {spec_name}: <改动> (salvaged from {branch})`\n"
            f"   ——便于事后溯源，且验证链会照常全量验收你的产出（收编不豁免测试）。\n"
            f"2. **弃用 (discard)**：若遗产为破碎半成品或不值收编，从你自己的干净状态重做，"
            f"并在最终产出说明中注明弃用理由（无强制格式，一句话即可）。\n\n"
            f"### 响应格式要求\n"
            f"在你的任务书响应中明确声明本次选择了哪条路径：\n"
            f"- 收编：列出你从遗产移植的文件与其来源分支 `{branch}`；\n"
            f"- 弃用：简述弃用理由。\n"
            f"若未使用遗产（首次实现 / 遗产已被兜底回收），本段不会出现，正常实现即可。\n"
        )

    def _legacy_branch_snapshot(self, branch: str) -> str:
        """现场采集仅分支遗产的提交快照（git log --oneline main..branch）。

        采集失败（分支不存在等）返回降级提示串，不抛出异常。
        """
        import subprocess as _sp
        try:
            res = _sp.run(
                ["git", "-C", str(self._pm.project_root),
                 "log", "--oneline", "-10", f"main..{branch}"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception as e:
            return f"（快照采集失败: {e}）"
        out = (res.stdout or "").strip()
        if res.returncode != 0:
            return f"（快照采集失败: {(res.stderr or '').strip()[:120]}）"
        if not out:
            return "（分支相对 main 无独立提交）"
        return out[:2000]


    def _legacy_dirty_snapshot(self, wt_path: str) -> str:
        """现场采集遗产 worktree 的 ``git status --short`` 脏文件清单，截断 50 行。

        采集失败（worktree 已不存在等）返回降级提示串，不抛出异常。
        """
        import subprocess as _sp
        try:
            res = _sp.run(
                ["git", "-C", str(wt_path), "status", "--short"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return "（无法读取遗产快照）"
        if res.returncode != 0:
            return "（无法读取遗产快照）"
        lines = res.stdout.splitlines()
        if not lines:
            return "（无脏文件，遗产已干净提交）"
        if len(lines) > 50:
            lines = lines[:50] + [f"... 其余 {len(lines) - 50} 个文件省略"]
        return "\n".join(lines)


    def _scenario_freeze_section(self, spec_name: str) -> str:
        """构建场景集冻结约束段（add-verify-scenario-freeze / design D1-D2）。

        修复轮（``_verify_fail_rounds > 0`` 或 tasks.md 含「## 验证修复」）时注入
        持久化集与「仅新增范围可追加、删减须理由」约束；首轮验证返回空串（不约束）。

        纯本地确定性读取（core.verify_scenarios），不触发 LLM。
        """
        try:
            from core.verify_scenarios import (
                load_scenario_set, is_repair_round,
                read_verify_fix_section, declares_new_delivery,
            )
        except Exception:
            return ""
        entry = None
        try:
            entry = self._pm.state_machine.read_one(spec_name)
        except Exception:
            entry = None
        if not is_repair_round(self._pm.project_root, spec_name, entry):
            return ""
        persisted = load_scenario_set(self._pm.project_root, spec_name)
        if persisted is None or not persisted.scenarios:
            return ""
        fix_section = read_verify_fix_section(self._pm.project_root, spec_name)
        extended = declares_new_delivery(fix_section)
        ids = "、".join(s.id for s in persisted.scenarios)
        lines = [
            "",
            "## 验证场景集冻结（修复轮约束，add-verify-scenario-freeze）",
            "",
            f"- 你处于**修复轮**：必须复用持久化场景集，不得重新膨胀场景面。",
            f"- 持久化集共 {len(persisted.scenarios)} 个既有场景（第 "
            f"{persisted.round} 轮稳定），MUST 全部覆盖：{ids}",
        ]
        if extended:
            lines.append(
                "- 修复段声明了**新增交付范围**：仅允许为该新增范围追加场景，"
                "新增场景在 JSON 顶层用 ``added_in_round`` 标注本轮轮次；"
                "非该范围的场景不得新增。"
            )
        else:
            lines.append(
                "- 修复段**未声明新增交付范围**：MUST NOT 新增任何场景"
                "（修复轮不扩容，design D2）。"
            )
        lines.append(
            "- 移除既有场景 MUST 在场景对象上用 ``remove_reason`` 字段给出理由"
            "（如对应功能已按任务书移除）；无理由的缺场景将被确定性校验器以"
            "持久化集补齐（等效于忽略你的删减），验证报告标注。"
        )
        lines.append("")
        return "\n".join(lines)


    def _interaction_contract_section(self, spec_name: str) -> str:
        """构建交互契约约束段（add-interaction-contract-and-per-assert-triage 1.2）。

        从 SPEC 文档声明式提取可交互候选（design D1 首版模式）；检出候选时注入
        覆盖要求与 ``covers`` / ``declared_display`` 元数据登记规范。未检出候选
        返回空串（prompt 与现状逐字节一致，与 legacy-section 同型）。
        """
        try:
            from core.interaction_contract import collect_spec_candidates
            candidates = collect_spec_candidates(self._pm.project_root, spec_name)
        except Exception:
            return ""
        if not candidates:
            return ""
        lines = [
            "",
            "## 交互契约（interaction-contract，强制，add-interaction-contract-and-per-assert-triage）",
            "",
            "- 页面中渲染为**可交互形态**的元素（按钮/按钮组/链接样式卡片/可点击行/"
            "表单控件）MUST 至少对应一个交互场景（点击/操作后的可观察结果断言），"
            "或在元素定义处声明「纯展示、不可交互」。",
            "- 本 SPEC 检出的可交互候选（声明式首版模式）：",
        ]
        for c in candidates:
            note = "（SPEC 已标注纯展示）" if c.declared_display else ""
            lines.append(f"  - `{c.raw}`（{c.source}:{c.line}）{note}")
        lines += [
            "- 产出场景时，在场景对象上用 ``covers`` 字段登记该场景覆盖的元素标识"
            "（如 \"covers\": [\"card-link\"]）。",
            "- 无法生成交互场景的元素（纯展示），在任一场景对象上用 "
            "``declared_display`` 登记（如 \"declared_display\": [\"btn-x\"]）。",
            "- 契约校验器会确定性 diff 候选集与场景集：既无覆盖又无声明的元素会"
            "导致场景验收失败并退回重排（含链接样式卡片——v2-overview-page 事故的"
            "复发点）。",
            "",
        ]
        return "\n".join(lines)


    def _triage_recheck_section(self, spec_name: str) -> str:
        """构建优先复核注入段（add-verdict-evidence-taxonomy D5）。

        读取 pm_engine 落盘的 ``.fenix/verify-progress/<spec>/triage_recheck.json``
        （连续 2 轮 warning 的场景清单），注入 planner prompt 的「优先复核」清单，
        与 scenario-freeze 的基准集注入同一接入点（纯本地确定性读取，不触发 LLM）。
        文件缺失 / 为空 → 返回空串（不约束）。
        """
        recheck_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "triage_recheck.json"
        )
        if not recheck_path.exists():
            return ""
        try:
            data = json.loads(recheck_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        if not isinstance(data, list) or not data:
            return ""
        ids = "、".join(str(s) for s in data if s)
        if not ids:
            return ""
        return (
            "\n\n## 优先复核清单（warning 收敛升级，add-verdict-evidence-taxonomy）\n"
            f"- 以下场景连续 2 轮验证均为 warning，被标记为「优先复核」：{ids}\n"
            "- 你必须优先重新执行这些场景，甄别其根因究竟是真实产品缺陷（应改判 "
            "classificatio=product-bug 并 failed）还是确属 flaky/env（可维持 warning）。\n"
            "- 切勿继续无限悬置为 warning；若确为产品缺陷，必须在本次裁决中如实分类并 failed。\n"
        )


    def _verdict_rejection_section(self, spec_name: str) -> str:
        """构建裁决驳回注入段（verdict-rejection-retry：重试幂等陷阱修复）。

        读取 pm_engine 落盘的 ``.fenix/verify-progress/<spec>/verdict_violations.json``
        （上一轮裁决被确定性校验驳回的违规明细），注入 judge prompt，告知重试
        judge 具体缺口。文件缺失/为空 → 返回空串（首轮裁决不注入）。
        """
        rejection_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "verdict_violations.json"
        )
        if not rejection_path.exists():
            return ""
        try:
            data = json.loads(rejection_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        if not isinstance(data, list) or not data:
            return ""
        lines = [
            "\n\n## ⚠️ 上一轮裁决已被校验驳回（强制修复，verdict-rejection-retry）\n"
            "- 你现在看到的是重试裁决：上一轮写回的 report.json 未通过框架确定性校验，"
            "违规明细如下：\n"
        ]
        for v in data:
            if isinstance(v, dict):
                lines.append(
                    f"  - 场景 `{v.get('scenario_id')}`（status={v.get('status')}）："
                    f"{v.get('reason')}\n"
                )
        lines.append(
            "- ⚠️ report.json 中已存在的 classification/evidence（上一轮残留）"
            "不代表裁决合规——缺失的 `assertion_triage` 逐断言归因同样是强制字段。\n"
            "- 你 MUST 对全部非 PASS 场景补齐缺口（含逐断言 assertion_triage）后"
            "覆盖写回 report.json，不得因部分字段已存在而判定「无需改写」。\n"
        )
        return "".join(lines)
