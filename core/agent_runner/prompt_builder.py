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

# 九类 agent → 提示词文件名（agent-type 白名单的单一来源，Dashboard 端点复用）
# add-daily-self-review：新增 self-review（每日自省）类型。
# add-deliverable-declaration-triage：新增 dispute-judge（交付物缺件 LLM 终审）类型。
# add-framework-self-evolution：新增 evolution（框架自进化复核）类型。
# add-spec-review-gate：新增 spec-review（SPEC 方案评审）类型。
AGENT_PROMPT_FILES = {
    "implementer": "implementer.md",
    "verifier": "verifier.md",
    "planner-plan": "planner-plan.md",
    "planner-judge": "planner-judge.md",
    "fast-track": "fast-track.md",
    "administrator": "administrator.md",
    "self-review": "self-review.md",
    "dispute-judge": "dispute-judge.md",
    "evolution": "evolution.md",
    "spec-review": "spec-review.md",
}


def planner_result_path(project_root, spec_name: str, agent_type: str) -> Path:
    """planner 阶段产物结果文件路径（add-judge-artifact-gate D1，注入/校验同源）。

    - planner-judge 结果文件 = ``<vp_dir>/.fenix-run-result.json``
    - planner-plan  场景集   = ``<vp_dir>/test_scenarios.json``

    prompt_builder 注入侧（{result_path}/{scenarios_path} 占位符）与 runner 产物
    硬门校验侧共用同一计算，避免双实现漂移；其余 agent 类型无 planner 产物契约，
    调用即 ValueError（fail-fast，防误用）。
    """
    vp_dir = Path(project_root) / ".fenix" / "verify-progress" / spec_name
    if agent_type == "planner-judge":
        return vp_dir / ".fenix-run-result.json"
    if agent_type == "planner-plan":
        return vp_dir / "test_scenarios.json"
    raise ValueError(
        f"planner_result_path 仅支持 planner-judge/planner-plan，收到 '{agent_type}'"
    )


# planner 裁决结果文件顶层 status 白名单（fix-verdict-read-failclosed D3）。
# runner 产物硬门（_check_agent_result_artifact）与 pm_engine 读侧
# （_read_verifier_result）共用此单一来源——白名单外取值（如 implementer 共享
# 文件残留的 "success"/"error"）一律不得视作合法裁决。语义错位 status 若被
# 读侧当作 verified 放行即历史 fail-open 事故（add-verify-contract-autodraft）。
planner_result_status_whitelist = (
    "verified",
    "bug-found",
    "plan-ready",
    "scenario-repaired",
)

# 评审结果 status 白名单（add-spec-review-gate）
spec_review_result_status_whitelist = (
    "approved",
    "repaired",
    "rejected",
)

def spec_review_result_path(project_root, spec_name: str) -> Path:
    """评审结果文件路径（add-spec-review-gate）。

    返回 <项目根>/.fenix/spec-review/<spec_name>/.fenix-run-result.json
    """
    return Path(project_root) / ".fenix" / "spec-review" / spec_name / ".fenix-run-result.json"


def project_agents_dir(proot) -> Path | None:
    """项目级 agents 目录 <项目根>/.fenix/agents；解析为通用层时返回 None。

    项目通道永不触碰通用层：仅当 <项目根>/.fenix/agents 经符号链接解析为
    通用层 AGENT_PROMPT_DIR 本身（废弃 .fenix 自引用软链布局）时，读取会
    把通用文件当项目附加叠加、写入会覆盖通用文件——读取返回 None（零注入）、
    写入端点拒绝。普通项目（.fenix 为真实目录，含 fenixd 自身：项目级即
    <root>/.fenix/agents/，与通用层 agents/ 互不相干）不受任何特殊处理。
    模块级函数供 PromptBuilder 与 Dashboard 端点共用同一判定。
    """
    d = Path(proot) / ".fenix" / "agents"
    try:
        if d.resolve() == AGENT_PROMPT_DIR.resolve():
            return None
    except OSError:
        return None
    return d


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
        # add-judge-artifact-gate D1：planner 产物路径经 planner_result_path 统一
        # 计算（注入侧与 runner 硬门校验侧同源，防双实现漂移）。{result_path}/
        # {scenarios_path} 值按两类型产物文件名恒定——fast-track/judge/plan 共用
        # 的 .fenix-run-result.json 与 test_scenarios.json 同此路径。
        values = {
            "{spec_name}": spec_name,
            "{spec_dir}": f"spec/changes/{spec_name}",
            "{scenarios_path}": str(planner_result_path(root, spec_name, "planner-plan")),
            "{result_path}": str(planner_result_path(root, spec_name, "planner-judge")),
            "{report_path}": str(vp_dir / "report.json"),
            # add-judge-incremental-attribution：judge 归因产物逐场景条目文件。
            # 与 core/verify_engine/judge_files.py 的 JUDGE_ATTRIBUTION_FILENAME
            # 同源（注入侧路径 = 读侧路径，防双实现漂移）。
            "{judge_attribution_path}": str(
                vp_dir / "judge_attribution.json"),
        }
        if agent_type == "verifier":
            values["{progress_path}"] = str(
                root / ".fenix" / "verify-progress" / f"{spec_name}.json")
        elif agent_type == "fast-track":
            values["{progress_path}"] = str(vp_dir / f"{spec_name}.json")
        elif agent_type == "dispute-judge":
            # 交付物缺件 LLM 终审（add-deliverable-declaration-triage D3）：
            # 输入（缺件清单 + spec 语境 + findings + basename 候选）由 dispatch
            # 层落盘，结果契约由 judge 写回（与 planner 结果文件并置、独立命名）。
            values["{dispute_input_path}"] = str(vp_dir / "dispute_judge_input.json")
            values["{dispute_result_path}"] = str(
                vp_dir / "dispute_judge_result.json")
        elif agent_type == "spec-review":
            # SPEC 方案评审（add-spec-review-gate）
            values["{result_path}"] = str(spec_review_result_path(root, spec_name))
            values["{state_path}"] = str(root / ".fenix" / "STATE.md")
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

    def _build_prompt(self, spec_name: str, agent_type: str, detail: dict | None = None,
                      wt_path: Path | None = None) -> str:
        """构建 claude CLI prompt：文件主体 + 占位符填充 + 动态段按状态追加。

        detail: 可选。administrator 分支接收困境信号 dict；
            repair 分支接收冲突分类信息（conflict_summary 结构，见
            _build_repair_prompt）。
        wt_path: 可选。本次 run 的 impl worktree 路径（add-planner-efficiency：
            路由地图注入用；planner 阶段在 prompt 组装前已把地图生成到
            <wt_path>/.fenix/route-map.md，此处按 生成>静态>无 的优先级注入）。
        """
        # repair prompt 完全独立构建（不走 agents/ 模板）：须先于模板加载判断，
        # 否则 _load_agent_template("repair") 因类型不在白名单而 fail-fast
        # （add-agent-prompt-files 重构引入的顺序问题，repair-lane 测试暴露）。
        if agent_type == "repair":
            return self._build_repair_prompt(spec_name, detail or {})

        # add-daily-self-review：自省 prompt 独立构建（无 spec 维度占位符，
        # 注入近 24 小时数据摘要与可选 todo.md 全文）。
        if agent_type == "self-review":
            return self._build_self_review_prompt(spec_name, detail or {})

        # add-framework-self-evolution：分析 run prompt 独立构建（无 spec
        # 维度占位符，注入就绪项目 todo.md 全文与待分析条目清单）。
        if agent_type == "evolution":
            return self._build_evolution_prompt(spec_name, detail or {})

        template = self._load_agent_template(agent_type)
        prompt = self._fill_placeholders(template, agent_type, spec_name, detail)

        if agent_type == "implementer":
            # 上轮 error 上下文注入（add-implementer-deliverable-gate D4）+
            # 恢复重派遗产上下文（add-recovery-legacy-check 2.1/2.2）。
            prompt += self._prev_error_section(spec_name)
            prompt += self._build_legacy_section(spec_name)
            # 中断恢复保留续做注记（interrupt-recovery-preserve 2.3）：本轮 dispatch
            # 在保留分支的 worktree 内 resume 续做时注入继承说明。
            prompt += self._recovery_resume_note(spec_name)
            # 任务进度契约段（fix-implementer-task-progress D1）：full/fast-track
            # 两个 implementer 分支共用同一文本，保证 harness TaskCreate/TaskUpdate
            # 行为与 tasks.md 编号对齐（进度可见性断链的根治点）。
            prompt += self._task_progress_contract_section()
            # 派发前声明现实处方（add-deliverable-declaration-triage D2）：有声明段
            # SPEC 把「声明清单 × 仓库现实」快照注入，实现者开工前即知候选矛盾。
            prompt += self._declared_reality_section(spec_name)
        elif agent_type == "verifier":
            prompt += self._verifier_breakpoint_section(spec_name)
        elif agent_type == "planner-plan":
            prompt += self._replan_feedback_section(spec_name)
            prompt += self._scenario_freeze_section(spec_name)
            prompt += self._interaction_contract_section(spec_name)
            prompt += self._triage_recheck_section(spec_name)
            # add-judge-artifact-gate D2：产物硬门契约注入（结果文件缺失=run失败）
            prompt += self._result_gate_section(spec_name)
        elif agent_type == "planner-judge":
            prompt += self._scenario_freeze_section(spec_name)
            prompt += self._triage_recheck_section(spec_name)
            # 跨轮已裁决场景注入（judge 效率治理 E）：先于驳回段——正向复用
            # 清单在前，强制修复清单殿后保持紧迫性
            prompt += self._verdict_cache_section(spec_name)
            prompt += self._verdict_rejection_section(spec_name)
            # 批量归因查重重合成指令段（fix-verdict-dedup-resynthesis）：查重
            # 拒绝时框架写 dedup_resynthesis_directive.json——注入被拒场景清单 +
            # 差异化素材 + 归因文本契约；非拒绝轮文件缺失零注入。
            prompt += self._resynthesis_directive_section(spec_name)
            # 回炉清单注入（add-judge-incremental-attribution 2.2）：requeue
            # 子集驱动下轮 judge 只重做该子集，文件缺失零注入。
            prompt += self._requeue_manifest_section(spec_name)
            # 场景静态缺陷情报段（add-scenario-defect-triage-gate D5）：在
            # verdict 缓存之后、硬门契约之前——先给情报（修复属 judge 职责、
            # 先修已知缺陷再裁决）后给结果文件硬门，情报不改变硬门契约语义。
            prompt += self._scenario_static_findings_section(spec_name)
            # 场景缺陷改道指令段（add-scenario-defect-triage-gate D2）：改道
            # 触发时由框架写 scenario_reroute_directive.json 注入——上轮清单
            # 全场景缺陷统计 + MUST 申报 scenario-repaired 禁止 bug-found +
            # 已裁决场景修复合法与冻结记账保护声明。非改道轮文件缺失零注入。
            prompt += self._scenario_reroute_directive_section(spec_name)
            # add-judge-artifact-gate D3：截断恢复注入（上一轮 checkpoint 残留
            # 已归因场景直接沿用、只补缺失）——先于硬门契约段注入
            prompt += self._checkpoint_recovery_section(spec_name)
            # add-judge-artifact-gate D2：产物硬门契约注入（结果文件缺失=run失败）
            prompt += self._result_gate_section(spec_name)
        elif agent_type == "fast-track":
            # 任务进度契约段（fix-implementer-task-progress D1，与 full 分支共用
            # 同一文本；fast-track 的 PHASE 1 主体已迁移 agents/fast-track.md）。
            prompt += self._task_progress_contract_section()
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
        if agent_type == "administrator":
            # fix-frozen-scenario-orphan-reservoir D6：admin 处置场景文件时的
            # 约束指令——修复写回必须过结构校验门（validate_scenario_dicts），
            # 被门拒绝时须按逐条错误清单重修；test_scenarios.json 与 scenarios.json
            # 同源坏条目须同步清理（双文件一致性），处置结果须报告两文件状态。
            prompt += self._admin_scenario_fix_constraints()
            # 契约静态检查情报段（planner-contract-findings，design D4）：admin
            # 职责含修正验证契约（judge 不修契约故不注入 judge）——serve 入口
            # 路径/端口注入类偏差在处置时可直接定位修正。findings 缺失零注入。
            prompt += self._contract_findings_section(spec_name)

        # 项目级附加提示词（D2）：附加在完整 prompt（通用主体 + 动态段）之后
        prompt += self._project_extra_section(agent_type, spec_name, wt_path)
        return prompt

    def _admin_scenario_fix_constraints(self) -> str:
        """admin 处置场景文件的约束指令段（fix-frozen-scenario-orphan-reservoir D6）。

        追加在 administrator prompt 末尾，约束 admin 修复场景文件时的行为：
          1. 修复写回必须通过结构校验门（与读端 load_scenarios 同源，
             validate_scenario_dicts）——被门拒绝时按逐条错误清单重修；
          2. test_scenarios.json 与 scenarios.json（持久化集）同源坏条目必须
             同步清理（双文件一致性），防储库复活；
          3. 处置结果须报告两文件状态（清理/修复情况）。
        """
        return (
            "\n\n## 场景文件修复约束（写端结构校验门 + 双文件一致性）\n"
            "当你修复/清理验证场景文件（test_scenarios.json 或 scenarios.json）时：\n"
            "1. **修复写回必须通过结构校验**：所有写回的内容会经过与读端同源的"
            "结构校验门（validate_scenario_dicts，逐条检查 id/kind/steps 等）。"
            "若你的写入被门拒绝，框架会反馈逐条错误清单——请按错误清单逐条重修后"
            "再次写回，不要绕过门或整文件乱写。\n"
            "2. **双文件一致性**：test_scenarios.json 与 scenarios.json 是同一场景"
            "集的两种形态，同源坏条目（如缺 kind 的孤儿条目）必须在两文件中同步清理"
            "——只清一个文件会让孤儿在另一个文件中存活、跨轮复活。\n"
            "3. **处置结果报告两文件状态**：在处置记录中写明 test_scenarios.json 与 "
            "scenarios.json 的清理/修复情况（各清了几条、剩几条）。\n"
        )

    def _contract_findings_section(self, spec_name: str) -> str:
        """契约静态检查情报段（planner-contract-findings，design D4）。

        读取 ``contract_findings.json``（scan_contract 落盘：serve 入口存在性 /
        与 package.json start 一致性 / 端口注入缺失等只读检查）渲染定向情报
        段——逐条 rule_id + severity + message + evidence，并声明「本情报为
        机械检出，处置前请以源码/执行证据核实」。findings 缺失/为空/损坏 →
        返回空串（零注入，prompt 与现状逐字节一致）。
        """
        path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "contract_findings.json"
        )
        if not path.exists():
            return ""
        try:
            findings = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return ""
        if not isinstance(findings, list) or not findings:
            return ""
        lines = [
            "",
            "## 契约静态检查情报（定向情报，供处置参考）",
            "",
            "框架对验证契约做了机械可查的只读一致性检查，下列偏差已检出：",
            "",
        ]
        for f in findings:
            if not isinstance(f, dict):
                continue
            rid = f.get("rule_id") or "?"
            sev = f.get("severity") or "?"
            msg = f.get("message") or ""
            ev = f.get("evidence") or ""
            lines.append(
                f"- `{rid}` [{sev}]: {msg}"
                + (f"\n  evidence: {ev}" if ev else "")
            )
        lines += [
            "",
            "处置要求：",
            "- **修正契约是你的职责**：入口路径/端口注入类偏差可在处置时直接修正 "
            "（.fenix/verify.yaml serve 段），修正后 git 提交并复位 spec 触发重验证；",
            "- **本情报为机械检出，处置前请以源码/执行证据核实**——两类偏差可能是"
            "合法设计（如 start 为 dev 形态、serve 为构建产物形态），核实后再动。",
            "",
        ]
        return "\n".join(lines)

    def _project_extra_section(self, agent_type: str, spec_name: str = "",
                               wt_path: Path | None = None) -> str:
        """项目级附加提示词段（add-agent-prompt-files D2 / 任务 2.1）。

        <项目根>/.fenix/agents/<agent-type>.md 存在则读入，以
        「## 项目附加提示词」标题附加在 prompt 完整内容（通用主体 + 动态段）
        之后；缺席零注入（prompt 与仅通用层时逐字节一致）。
        通用层重合布局跳过（project_agents_dir 返回 None，见其 docstring）。

        路由地图段（add-planner-efficiency：planner-route-map 1.3）：
        planner 阶段附加已知入口索引（生成地图 > 主树静态 > 无），
        措辞固定为「已知入口索引、非穷尽清单；spec 涉及但地图未覆盖的
        入口仍须自行源码取证」——防线在措辞（生成器覆盖不全时 planner
        不放弃取证）。
        """
        base = ""
        agents_dir = self._project_agents_dir()
        if agents_dir is not None:
            path = agents_dir / AGENT_PROMPT_FILES[agent_type]
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8").strip()
                except OSError:
                    content = ""
                if content:
                    base = f"\n\n## 项目附加提示词\n\n{content}\n"
        # ── 路由地图段（planner-plan 专属，planner-judge 不出题无需注入）──
        if agent_type == "planner-plan" and spec_name:
            rm = self._route_map_section(spec_name, wt_path)
            if rm:
                base += rm
        return base

    def _route_map_section(self, spec_name: str, wt_path: Path | None = None) -> str:
        """路由地图注入段（add-planner-efficiency：planner-route-map 1.3）。

        优先级：worktree 生成地图 > 主树静态 `.fenix/route-map.md` > 无。
        措辞固定为「已知入口索引、非穷尽清单」+ 取证义务提醒。

        Returns:
            prompt 段字符串（含导航信息时）或空串（fail-open / 无地图）。
        """
        from core.agent_runner.runner import ROUTE_MAP_REL
        project_root = self._pm.project_root
        map_path: Path | None = None
        # 1. worktree 生成地图（planner 阶段在 prompt 组装前已生成）
        if wt_path is not None:
            candidate = Path(wt_path) / ROUTE_MAP_REL
            if candidate.is_file():
                map_path = candidate
        # 2. 主树静态地图（人工提交 / 无生成器项目）
        if map_path is None:
            candidate = Path(project_root) / ROUTE_MAP_REL
            if candidate.is_file():
                map_path = candidate
        if map_path is None:
            return ""
        try:
            content = map_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return ""
        if not content:
            return ""
        return (
            f"\n\n## 路由地图（已知入口索引、非穷尽清单）\n\n"
            f"{content}\n\n"
            f"> **注意**：以上为项目已知入口索引，**非穷尽清单**。spec 涉及但"
            f"地图未覆盖的入口，你仍须自行源码取证（grep/阅读源码，导航出处须"
            f"包含 `文件:行号`）。不可仅凭此地图断言无新入口。\n"
        )

    def _project_agents_dir(self):
        """项目级 agents 目录；解析为通用层时返回 None（见 project_agents_dir）。"""
        return project_agents_dir(self._pm.project_root)

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

    def _declared_reality_snapshot(self, spec_name: str) -> "dict | None":
        """「声明清单 × 仓库现实」快照（add-deliverable-declaration-triage PR2 2.1）。

        仅对有 ``## Deliverables`` 声明段的 SPEC 干跑：以
        ``extract_declared_entries`` 取原始条目（path+kind），对每个
        new/modify 路径做主树存在性检查与 basename 匹配，产出快照：

        ``{"entries": [{"path", "kind", "exists", "candidates"}]}``

        reference 条目仅保留 kind/exists（软校验，不做候选匹配）。无声明段、
        spec 目录读取失败或任何干跑异常 → ``None``（fail-open，跳过注入，
        派发照常——2.3）。

        Returns:
            快照 dict 或 None。
        """
        from core.deliverables import extract_declared_entries, \
            match_basename_in_tree

        spec_dir = self._pm.project_root / "spec" / "changes" / spec_name
        if not spec_dir.is_dir():
            return None
        try:
            entries = extract_declared_entries(spec_dir)
        except Exception:
            return None
        if not entries:
            return None

        snap: list = []
        for e in entries:
            path = e["path"]
            kind = e["kind"]
            item = {
                "path": path,
                "kind": kind,
                "exists": bool((self._pm.project_root / path).exists()),
                "candidates": [],
            }
            if kind in ("new", "modify") and not item["exists"]:
                try:
                    item["candidates"] = match_basename_in_tree(
                        self._pm.project_root, path)
                except Exception:
                    item["candidates"] = []
            snap.append(item)
        return {"entries": snap}

    def _declared_reality_section(self, spec_name: str) -> str:
        """派发前声明现实处方注入段（add-deliverable-declaration-triage D2/PR2 2.2）。

        快照存在（有声明段 SPEC）时把「声明清单 × 仓库现实」注入 implementer
        提示词：存在的 modify 路径标注为修改目标；不存在的 new/modify 路径标注
        并列出全部 basename 命中候选（若有）。文案约定：判断声明路径系笔误时
        以实际正确路径实现，并在 ``.fenix-run-result.json`` 的 ``findings`` 登记
        ``deliverable-dispute``（element/current/suggestion），MUST NOT 静默改变
        交付落点。无声明段或干跑异常（快照为 None）→ 返回空串（fail-open，
        prompt 与现状逐字节一致——2.3）。
        """
        snapshot = self._declared_reality_snapshot(spec_name)
        if snapshot is None or not snapshot.get("entries"):
            return ""
        lines = [
            "",
            "## 声明清单 × 仓库现实（deliverable-declaration-triage 处方）",
            "",
            "以下为本 SPEC 交付物声明的仓库现实快照（主树存在性 × basename 候选）：",
            "",
            "**重要**：下文的「主树」状态仅供声明对账参考。你的全部实现读写都必须"
            "发生在**当前工作目录（run 专属 worktree）**内——一律使用相对路径，"
            "禁止按绝对路径写主树（上下文里出现的主树绝对路径如 skill 基路径"
            "只是部署位置参考，不是交付落点）。",
            "",
        ]
        for item in snapshot["entries"]:
            path = item["path"]
            kind = item["kind"]
            cands = item.get("candidates") or []
            if item["exists"]:
                lines.append(f"- `{path}`（kind: {kind}）——主树存在，修改/引用目标确认。")
            else:
                note = ""
                if cands:
                    note = f"；basename 命中候选：{'、'.join(cands)}"
                lines.append(
                    f"- `{path}`（kind: {kind}）——主树不存在，疑似声明笔误"
                    f"{note}。")
        lines += [
            "",
            "**处方**：若你判断声明路径系笔误（候选命中与 spec 语境等价），"
            "以实际正确路径实现，并在 `.fenix-run-result.json` 的 `findings` "
            "登记 `deliverable-dispute` 条目（`element`=声明路径，`current`=现状，"
            "`suggestion`=应归的实际路径/依据）——不得静默改变交付落点；"
            "非笔误时按声明路径实现（收工守卫会按声明对账缺件）。",
            "",
        ]
        return "\n".join(lines)

    def _task_progress_contract_section(self) -> str:
        """任务进度契约段（fix-implementer-task-progress D1）。

        full 与 fast-track 两个 implementer 分支共用同一文本：TaskCreate subject
        带 tasks.md 编号、一任务一 TaskCreate、完成即 TaskUpdate、收尾逐项勾选，
        使侧写叠加 / 写侧回写 / run 层展示三端全部对齐。
        """
        return (
            f"\n## 任务进度契约（task-progress-contract，强制，fix-implementer-task-progress）\n"
            f"- 每一条 tasks.md 任务（如 \"1.3 配置解析签名缓存\"）只能由一个 TaskCreate 对应，"
            f"TaskCreate 的 subject MUST 以 \"Task <id>: <标题>\" 开头，id 直取 tasks.md 的"
            f"\"分组号.任务号\"（如 \"Task 1.3: 配置解析签名缓存\"），禁止把多条任务归并为一条"
            f"TaskCreate，也禁止把分组（## 标题）当任务创建。\n"
            f"- 开始实现某任务时创建其 TaskCreate；该任务完成的瞬间立刻对同一 taskId 发"
            f"TaskUpdate status=completed，不得攒批到收尾。TaskUpdate 的 taskId 取"
            f"TaskCreate 结果返回的任务编号（1 基创建序，形如 \"Task #1 created\"）。\n"
            f"- 收尾时逐项 Edit tasks.md，把每条已完成任务 `- [ ]` 改为 `- [x]`，"
            f"与全部 TaskCreate/TaskUpdate 记录一一对应，不留半勾。\n"
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

    def _build_repair_prompt(self, spec_name: str, conflict_summary: dict) -> str:
        """构建 repair agent 提示词（add-merge-back-repair-lane D5）。

        prompt 形态（spec 要求）：
        - spec 身份与实现目标简述
        - 冲突文件清单摘要（来自 merge 失败输出）
        - 修复方向说明：把 main 合入分支、解决语义冲突、运行测试、commit
        - 显式失败出口
        - **不含**原 worktree 地址类间接情报（agent 即在现场，冲突状态自查）

        Args:
            spec_name: SPEC 名称
            conflict_summary: 调度层传入的冲突分类摘要 dict，字段：
                - merge_error: merge 原始错误文本
                - conflict_paths: 冲突路径列表
                - has_semantic_conflict: 是否含语义冲突
                - repair_round: 当前是第几轮 repair
        """
        spec_dir = f"spec/changes/{spec_name}"
        merge_error = conflict_summary.get("merge_error", "（未提供原始错误）")
        conflict_paths = conflict_summary.get("conflict_paths", [])
        repair_round = conflict_summary.get("repair_round", 1)

        conflict_section = ""
        if conflict_paths:
            path_list = "\n".join(f"  - {p}" for p in conflict_paths)
            conflict_section = (
                f"\n## 冲突文件清单\n"
                f"以下文件在 merge main → 当前分支 时发生冲突：\n{path_list}\n"
            )
        else:
            conflict_section = (
                f"\n## 冲突文件清单\n"
                f"请自行通过 `git status --porcelain` 检查当前冲突文件。\n"
            )

        prompt = (
            f"You are the Fenix Repair Agent. You are in repair round {repair_round} "
            f"for the SPEC at {spec_dir}/.\n\n"
            f"## 身份与目标\n"
            f"你正在修复 SPEC `{spec_name}` 的 merge-back 冲突。上一次 merge main 分支到实现"
            f"分支时失败。你的任务是在当前实现分支一侧，把 main 合进分支并解决所有语义冲突，"
            f"确保测试通过后提交。\n\n"
            f"## 原始 merge 错误\n"
            f"```\n{merge_error[:2000]}\n```\n"
            f"{conflict_section}"
            f"## 修复方向（MUST 按顺序执行）\n"
            f"1. 检查当前状态：`git status --porcelain` 和 `git log --oneline -3`\n"
            f"2. 把 main 合进当前分支：`git merge main`（此时会遇到冲突）\n"
            f"3. 解决冲突：对每个冲突文件，读取两边版本，保留正确的实现内容\n"
            f"4. 运行项目测试，确认改动不破坏现有功能\n"
            f"5. commit 冲突解决：`git commit -m \"[fenix] {spec_name}: resolve merge conflicts\"`\n\n"
            f"## 完成后\n"
            f"成功：写 .fenix-run-result.json:\n"
            f'{{"status": "success", "spec": "{spec_name}", '
            f'"summary": "<简述解决的冲突>"}}\n\n'
            f"失败：如果无法解决冲突，写 .fenix-run-result.json:\n"
            f'{{"status": "error", "spec": "{spec_name}", '
            f'"error": "<说明为何无法解决>"}}\n\n'
            f"重要限制：\n"
            f"- 不要修改任务书（tasks.md）中的勾选状态\n"
            f"- 不要重新实现功能，只解决 merge 冲突\n"
            f"- 无法解决时必须显式报告失败（写 .fenix-run-result.json error status），"
            f"框架会据此回退到 fallback 重派\n"
            f"IMPORTANT: Do NOT modify STATE.md."
        )
        return prompt

    def _build_self_review_prompt(self, date_str: str, detail: dict) -> str:
        """构建每日自省 prompt（add-daily-self-review design D2/D3）。

        加载 agents/self-review.md（文件化体系，缺失 fail-fast），以
        str.replace 填充占位符（不用 str.format——正文含大量 {} JSON 示例）：
        - {review_date}: 自省归属执行日
        - {daily_summary}: 框架聚合的近 24 小时数据摘要（五源：STATE 终态 /
          runs 统计 / admin 告警与处置 / 日志 ERROR / 近 3 日 git 提交）
        - {todo_md_content}: read_todo=true 时的既有 todo.md 全文；
          关闭或不存在时为占位提示（Agent 无需区分）
        - {todo_entries}: read_todo=true 时 ID 标注的近 3 日条目清单
          （闭环判定对象）；关闭或无条目时为占位提示
        - {out_path}: 回顾 JSON 写入路径（.fenix/self_review_out-<run_id>.json）
        """
        template = self._load_agent_template("self-review")
        prompt = template
        prompt = prompt.replace("{review_date}", date_str)
        prompt = prompt.replace(
            "{daily_summary}", (detail.get("daily_summary") or "（无数据）"))
        prompt = prompt.replace(
            "{todo_md_content}",
            (detail.get("todo_md") or "（read_todo 关闭或 todo.md 不存在，不注入）"))
        prompt = prompt.replace(
            "{todo_entries}",
            (detail.get("todo_entries") or "（近3日窗口内无既有条目）"))
        prompt = prompt.replace(
            "{out_path}",
            str(detail.get("out_path") or (self._pm.project_root / ".fenix"
                                           / "self_review_out.json")))
        return prompt

    def _build_evolution_prompt(self, spec_name: str, detail: dict) -> str:
        """构建框架自进化分析 run 的 prompt（add-framework-self-evolution D6）。

        加载 agents/evolution.md（文件化体系，缺失 fail-fast），以 str.replace
        填充占位符（不用 str.format——正文含大量 {} JSON 示例）：
        - {todo_sections}: 就绪项目清单，每项目含项目名、项目根与 todo.md 全文
        - {pending_entries}: 待分析条目清单（含 id、日期节、小节、标题）
        - {out_path}: 契约产物路径（.fenix/evolution/out-<run_id>.json）
        - {project_root}: 框架主树（项目根）
        """
        template = self._load_agent_template("evolution")
        prompt = template
        projects: list = detail.get("ready_projects") or []
        pending: list = detail.get("pending_entries") or []

        secs = []
        for proj in projects:
            if not isinstance(proj, dict):
                continue
            name = proj.get("name") or "?"
            root = proj.get("path") or self._pm.project_root
            todo = proj.get("todo_md") or "（无 todo.md 内容）"
            secs.append(
                f"### 项目：{name}（项目根：{root}）\n"
                f"```\n{todo}\n```\n"
            )
        todo_sections = "\n".join(secs) or "（无就绪项目）"

        lines = []
        for idx, entry in enumerate(pending, start=1):
            if not isinstance(entry, dict):
                continue
            lines.append(
                f"- #{idx} [id={entry.get('id') or '?'}] "
                f"{entry.get('date_section') or '?'} / "
                f"{entry.get('section') or '?'}：{entry.get('title') or '?'}"
            )
        entries_txt = "\n".join(lines) or "（无待分析条目）"

        out_path = detail.get("out_path")
        if not out_path:
            out_path = self._pm.project_root / ".fenix" / "evolution" / "out.json"
        prompt = prompt.replace("{todo_sections}", todo_sections)
        prompt = prompt.replace("{pending_entries}", entries_txt)
        prompt = prompt.replace("{out_path}", str(out_path))
        prompt = prompt.replace(
            "{project_root}", str(self._pm.project_root))
        return prompt

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

    def _recovery_resume_note(self, spec_name: str) -> str:
        """恢复续做说明：中断恢复保留分支的 resume 派发时注入（interrupt-recovery-preserve）。

        dispatch 层在保留分支的 worktree 内续做（``mark_reused`` 登记继承痕迹，
        prompt 构建据此注入）。语义与 worktree-reuse 继承一致：延续已有成果、
        从 tasks.md 第一个未勾选项继续，不重做、不回滚。未登记复用痕迹时返回空串
        （prompt 与现状逐字节一致）。
        """
        wm = getattr(self._pm, "worktree_manager", None)
        if wm is None or not hasattr(wm, "get_reuse_record"):
            return ""
        rec = wm.get_reuse_record(spec_name)
        if not rec:
            return ""
        branch = rec.get("branch") or ""
        return (
            f"\n## 中断恢复续做（recovery resume）\n"
            f"本 spec 的实现 run 曾因 daemon 重启/停机被中断，框架保留了你在分支"
            f"上的已提交成果，本轮在原 worktree 内继续实现（当前分支："
            f"`{branch}`）。检查当前分支上已有的提交与 tasks.md 勾选进度，从第一个"
            f"未勾选项继续，不要重做已完成的工作，不要重置或回滚已有改动；中断前"
            f"未提交的现场（如有）同样在你的工作目录中，可审阅后继续使用。\n"
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

        fix-verdict-dedup-resynthesis：兼容批量归因查重违规形态（条目
        ``{"scenario_ids": [...], "reason": ...}``，无单场景 scenario_id），
        并扩展定向纪律——查重拒绝的重试是**轻量重合成**：只重写清单内场景的
        ``first_failed_step`` 与断言 triage evidence 归因文本字段，其余字段
        原样保留，禁止复现/调查/改判定。
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
        is_dedup = False
        for v in data:
            if not isinstance(v, dict):
                continue
            if v.get("scenario_ids"):
                # 批量归因查重违规（fix-verdict-dedup-resynthesis）：无单场景
                # scenario_id，场景集在 scenario_ids 列表
                is_dedup = True
                sids = "、".join(str(s) for s in v["scenario_ids"] if s)
                lines.append(
                    f"  - 批量归因查重违规（场景：{sids}）：{v.get('reason')}\n"
                )
            else:
                lines.append(
                    f"  - 场景 `{v.get('scenario_id')}`（status={v.get('status')}）："
                    f"{v.get('reason')}\n"
                )
        lines.append(
            "- ⚠️ report.json 中已存在的 classification/evidence（上一轮残留）"
            "不代表裁决合规——缺失的 `assertion_triage` 逐断言归因同样是强制字段。\n"
            "- **重试定向纪律（judge 效率治理 2026-09-06）**：只对上述违规清单中的"
            "场景重新裁决/取证；其余非 PASS 场景已写入 report.json 的 "
            "classification/evidence/assertion_triage 视为受理——**原样保留、"
            "禁止重新复现或改写**，覆盖写回时不得改动清单外场景的任何字段"
            "（整轮重跑式重试是 15-25 分钟×N 的确定性浪费）。\n"
        )
        if is_dedup:
            lines.append(
                "- **查重拒绝 = 轻量重合成（fix-verdict-dedup-resynthesis）**："
                "对上述查重违规场景，MUST 只重写其归因**文本字段**（`first_failed_step` "
                "与断言 triage 的 `evidence`），MUST NOT 重新调查/复现/改写判定、"
                "MUST NOT 改动任何未拒绝场景的字段；归因文本 MUST 引用本场景自己的"
                "步骤序号/断言 label/完整 error（见下方重合成指令段逐场景素材），"
                "MUST NOT 套用共享模板串——连步骤引用都复制的同文仍会被查重门再拒。\n"
            )
        return "".join(lines)

    def _resynthesis_directive_section(self, spec_name: str) -> str:
        """重合成指令注入段（fix-verdict-dedup-resynthesis 3.2）。

        批量归因查重拒绝时框架写 ``dedup_resynthesis_directive.json``；存在时
        注入：被拒场景清单 + 逐场景现有归因文本与失败步骤序号/断言 label 差异化
        素材 + 归因文本契约（MUST 引用本场景局部数据、MUST NOT 套用共享模板串）。
        文件缺失/损坏 → 返回空串（普通裁决轮零注入，prompt 与现状逐字节一致）。
        """
        directive_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "dedup_resynthesis_directive.json"
        )
        if not directive_path.exists():
            return ""
        try:
            data = json.loads(directive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return ""
        if not isinstance(data, dict):
            return ""
        violations = data.get("violations") or []
        scenarios = data.get("scenarios") or []
        if not violations or not scenarios:
            return ""
        lines = [
            "\n\n## ♻️ 批量归因查重重合成指令（fix-verdict-dedup-resynthesis，强制）\n"
            "- 本轮是**轻量重合成**：只重写下列被拒场景的归因文本字段"
            "（`first_failed_step` 与断言 triage 的 `evidence`），MUST NOT "
            "调查/复现/改写判定、MUST NOT 改动未拒绝场景的任何字段。\n"
            "- 被拒场景清单：\n"
        ]
        for v in violations:
            if not isinstance(v, dict):
                continue
            sids = "、".join(str(s) for s in (v.get("scenario_ids") or []) if s)
            lines.append(f"  - {sids}: {v.get('reason')}\n")
        lines.append(
            "- 各被拒场景的差异化素材（框架已掌握的场景局部数据，归因改写 MUST "
            "逐场景引用，MUST NOT 套用共享模板串）：\n"
        )
        for sc in scenarios:
            if not isinstance(sc, dict):
                continue
            sid = sc.get("scenario_id") or "?"
            ffs = sc.get("first_failed_step") or ""
            step_no = sc.get("failed_step_number") or ""
            labels = "、".join(str(s) for s in (sc.get("assertion_labels") or [])) or "（无）"
            lines.append(
                f"  - `{sid}`（classification={sc.get('classification') or '?'}，"
                f"status={sc.get('status') or '?'}）:\n"
                f"      first_failed_step 现状: {ffs}\n"
                f"      失败步骤序号: {step_no or '（未提取）'}；"
                f"断言 label: {labels}\n"
                f"      → 改写后 first_failed_step/断言 evidence MUST 引用上述"
                f"本场景步骤序号与断言 label（完整 error 优先取自 assertion_results），"
                f"禁止与其它场景共享逐字相同的归因文本\n"
            )
        return "".join(lines)

    def _requeue_manifest_section(self, spec_name: str) -> str:
        """回炉清单注入段（add-judge-incremental-attribution 2.2 / design D2）。

        场景级查重拒绝时框架写 ``requeue_manifest.json``（requeue 子集清单）；
        存在时注入：本轮 judge MUST 只重做 requeue 子集场景的归因文本字段，
        其余（accept）场景归因原样保留复用——MUST NOT 重写非回炉场景。
        文件缺失/损坏 → 返回空串（普通裁决轮零注入，prompt 与现状逐字节一致）。
        """
        manifest_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "requeue_manifest.json"
        )
        if not manifest_path.exists():
            return ""
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return ""
        if not isinstance(data, dict):
            return ""
        requeue_ids = [str(s) for s in (data.get("requeue_scenario_ids") or [])]
        if not requeue_ids:
            return ""
        return (
            "\n\n## 🔄 场景级回炉清单（add-judge-incremental-attribution，强制）\n"
            "- 本轮是 **requeue 子集回炉**：只重做下列被拒场景的归因文本字段"
            "（`first_failed_step` 与断言 triage 的 `evidence`），MUST NOT "
            "调查/复现/改写判定。\n"
            f"- 回炉场景清单：{'、'.join(requeue_ids)}\n"
            "- 清单外场景归因已通过查重（accept）——**原样保留复用，MUST NOT "
            "重写/复现/改动任何字段**；回炉完成后框架会对整轮再做一次查重校验。\n"
            "- 归因文本契约同「批量归因查重重合成指令」：MUST 逐场景引用本场景"
            "局部数据（步骤序号/断言 label/完整 error），MUST NOT 套用共享模板串。\n"
        )

    def _result_gate_section(self, spec_name: str) -> str:
        """planner 产物硬门契约注入段（add-judge-artifact-gate D2）。

        告知 planner-judge/planner-plan：run 成功判定 = 进程正常退出 **且** 结果
        文件落盘且为可解析非空 JSON；收工不写/写空/非法 JSON → 判失败并自动原地
        退避重试（不进裁决重试预算）。路径经 planner_result_path 与 runner 硬门
        同源计算。纯静态文本，零 IO、零状态条件。
        """
        result_path = planner_result_path(
            self._pm.project_root, spec_name, "planner-judge")
        scenarios_path = planner_result_path(
            self._pm.project_root, spec_name, "planner-plan")
        return (
            "\n\n## 结果文件硬门（add-judge-artifact-gate，强制）\n"
            "- 框架对本次 run 的成功判定 = 进程正常退出 **且** 结果文件已落盘"
            "且为可解析的非空 JSON。\n"
            f"  - planner-judge 结果文件：{result_path}\n"
            f"  - planner-plan 结果文件：{scenarios_path}\n"
            "- 收工前未写 / 文件为空 / 非法 JSON → 本次 run 判**失败**并自动原地"
            "退避重试（不消耗裁决重试预算）；产物缺失的运行结果不会被当作成功采纳"
            "（fail-closed）。\n"
            "- 结果文件 MUST 为合法 JSON——字符串内换行/引号/控制字符必须转义，"
            "建议以代码 `json.dump` 生成而非手工拼接文本（fix-verdict-read-failclosed"
            " D7；不可解析的裁决读侧按 fail-closed 阻断，不视为 verified）。\n"
            "- **先落盘再深入**：先完成最小必要产物落盘，再做深入调查/复现——"
            "深入调查不会为产物缺失兜底。\n"
        )

    # ── 截断恢复（add-judge-artifact-gate D3：逐场景 checkpoint 的恢复语义）────
    # 判据与跨轮裁决缓存（指纹匹配）不同：checkpoint 恢复只看**字段在位性**——
    # classification/evidence 已合法落盘的非 PASS 场景视为已归档，重试 judge
    # 直接沿用、只补缺失/非法场景；不要求断言指纹跨轮一致（其实是同一轮失败后的
    # 原地重试，复现结果天然一致）。

    _CLASSIFICATION_VALUES = ("product-bug", "test-defect", "flaky", "env")

    @staticmethod
    def _scenario_classified(scenario: dict) -> bool:
        """非 PASS 场景是否已归因存档：classification 合法且 evidence 非空。"""
        if not isinstance(scenario, dict):
            return False
        cls = scenario.get("classification")
        if not isinstance(cls, str) or cls not in PromptBuilder._CLASSIFICATION_VALUES:
            return False
        ev = scenario.get("evidence")
        return isinstance(ev, dict) and bool(ev)

    def _checkpoint_recovery_section(self, spec_name: str) -> str:
        """截断恢复注入段（add-judge-artifact-gate D3，checkpoint 恢复语义）。

        上一轮 run 可能已把对 report.json 的增强以逐场景 checkpoint 形式落盘
        （流截断后产物硬门判失败 → 原地重试）。读取现 report.json，把已带合法
        classification/evidence 的非 PASS 场景注入「直接沿用、只补缺失」清单——
        与跨轮已裁决场景注入段（judge 效率治理 E，断言指纹判据）正交：本段判据为
        **字段在位性**，是同一轮失败后原地重试的恢复语义。

        报告文件缺失/损坏/无遗留 → 返回空串（零注入，首轮 judge 不注入）。
        """
        report_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "report.json"
        )
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return ""
        if not isinstance(data, dict):
            return ""
        kept = []
        for sc in data.get("scenarios") or []:
            if not isinstance(sc, dict):
                continue
            if sc.get("status") in ("pass", "passed"):
                continue
            if self._scenario_classified(sc):
                kept.append(sc)
        if not kept:
            return ""
        ids = "、".join(str(sc.get("scenario_id")) for sc in kept)
        return (
            "\n\n## ♻️ 截断恢复：已归因场景直接沿用（add-judge-artifact-gate）\n"
            "- 上一次以失败收场的 run（网关流截断等瞬态）已对下列场景完成逐场景"
            "checkpoint 写盘，其 classification/evidence 已合法落盘——"
            "**直接沿用，MUST NOT 二次裁决/复现/改写**，覆盖写回时对仍在位的字段"
            "原样保留：\n"
            f"  - {ids}\n"
            "- 已归档场景仍需逐场景核对 `assertion_triage` 是否齐全：缺则只补断言"
            "归因后覆盖写回，不重新取证。\n"
            "- 仅对**缺失或非法**（无 classification / 非法 classification / "
            "空 evidence）的场景做完整裁决，并逐一写回 checkpoint。\n"
        )

    def _verdict_cache_section(self, spec_name: str) -> str:
        """跨轮已裁决场景注入段（judge 效率治理 E，2026-09-06）。

        当前轮 report.json 的非 PASS 场景按断言指纹（``scenario_fingerprint``，
        引擎侧失败断言内容 hash）比对上轮采纳缓存（verdict_cache.json），命中
        者注入「结论可直接沿用」清单——judge 对命中场景免复现/免重取证，仅把
        既有结论原样写回 report.json（确定性校验器仍要求全量字段在位，写回
        不可省）。无缓存/零命中/读取异常 → 返回空串（零注入，prompt 回退）。
        """
        from core.verdict_check import load_verdict_cache, scenario_fingerprint
        report_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "report.json"
        )
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return ""
        if not isinstance(report, dict):
            return ""
        cache = load_verdict_cache(self._pm.project_root, spec_name)
        if not cache:
            return ""
        hits = []
        for sc in report.get("scenarios") or []:
            if not isinstance(sc, dict) or sc.get("status") in ("pass", "passed"):
                continue
            entry = cache.get(str(sc.get("scenario_id")))
            if not isinstance(entry, dict):
                continue
            if entry.get("fingerprint") != scenario_fingerprint(sc):
                continue
            hits.append((str(sc.get("scenario_id")), entry))
        if not hits:
            return ""
        lines = [
            "\n\n## ♻️ 跨轮已裁决场景（断言指纹一致，免复现）\n"
            "- 下列场景的失败断言内容与上一轮已采纳裁决完全一致（框架指纹比对），"
            "其下述 classification/evidence/assertion_triage **直接原样写回 "
            "report.json**，MUST NOT 重新复现/重取证/改写（重验轮的确定性浪费）。\n"
            "- 仅对本清单之外的场景做完整裁决。\n"
        ]
        for sid, entry in hits:
            lines.append(
                f"  - `{sid}`: classification={entry.get('classification')}, "
                f"evidence={json.dumps(entry.get('evidence'), ensure_ascii=False)}, "
                f"assertion_triage={json.dumps(entry.get('assertion_triage'), ensure_ascii=False)}\n"
            )
        return "".join(lines)


    def _scenario_static_findings_section(self, spec_name: str) -> str:
        """场景静态缺陷情报段（add-scenario-defect-triage-gate D5）。

        读取 ``scenario_static_findings.json``（扫描器落盘，pattern 表驱动：
        跨轮端口残留 / 双汉字文本选择器等机械可查模式）渲染定向情报段——
        逐条 scenario_id + 缺陷说明，声明「修复属 judge 职责、先修已知缺陷
        再裁决」。findings 缺失/为空/损坏 → 返回空串（零注入，prompt 与现状
        逐字节一致）。
        """
        from core.verify_engine.scenario_static_check import load_findings
        findings = load_findings(self._pm.project_root, spec_name)
        if not findings:
            return ""
        lines = [
            "",
            "## 场景静态缺陷情报（定向情报，修复属 judge 职责）",
            "",
            "框架对当前场景集做了机械可查的静态缺陷扫描，下列场景存在已知缺陷模式：",
            "",
        ]
        for f in findings:
            lines.append(
                f"- `{f.get('scenario_id')}` [{f.get('rule_id')} "
                f"{f.get('location')}]: {f.get('message')}"
            )
        lines += [
            "",
            "处理要求：",
            "- **修复属 judge 职责**：对上述已检出场景，必须先修复已知缺陷再裁决"
            "（属场景文件缺陷 → 按文末「原地修复协议」申报 scenario-repaired）；",
            "- 修复已裁决场景（含跨轮写回场景）合法，受冻结 diff 记账保护"
            "（无理由移除才确定性补齐），不视为冻结违规；",
            "- 本情报为静态机械检出（只收确定性模式），可能误报——修复前请以源码/"
            "执行证据核实，非缺陷项在 evidence 中说明即可。",
            "",
        ]
        return "\n".join(lines)


    def _scenario_reroute_directive_section(self, spec_name: str) -> str:
        """场景缺陷改道指令段（add-scenario-defect-triage-gate D2）。

        改道门把 bug-found 清单判为全场景缺陷时，框架写
        ``scenario_reroute_directive.json`` 并重派 judge——本段读取渲染定向指令：
          1. 上轮清单全场景缺陷统计（失败场景全部 test-defect/flaky，
             product-bug=0，未显式分类保守不改道）；
          2. MUST 申报 ``scenario-repaired`` 按原地修复协议修场景，禁止申报
             bug-found（真产品缺陷才允许 bug-found）；
          3. 已裁决场景修复合法 + 冻结 diff 记账保护声明（无理由移除才确定性
             补齐，不视为冻结违规）。
        文件缺失/损坏 → 返回空串（零注入，非改道轮 prompt 与现状逐字节一致）。
        """
        directive_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "scenario_reroute_directive.json"
        )
        if not directive_path.exists():
            return ""
        try:
            data = json.loads(directive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return ""
        if not isinstance(data, dict):
            return ""
        counts = data.get("counts") or {}
        failed_ids = data.get("failed_ids") or []
        if not failed_ids:
            return ""
        id_line = "、".join(str(s) for s in failed_ids)
        counts_txt = "、".join(
            f"{k}={v}" for k, v in counts.items()) if counts else "全 test-defect"
        return (
            "\n\n## ⚠️ 场景缺陷改道（MANDATORY：按原地修复协议申报 scenario-repaired）\n"
            "\n"
            "- 框架已判定：上一轮失败清单全部为**场景文件缺陷**（classification "
            "分布 {counts_txt}，product-bug=0）——打回 implementer 修场景是错误路由，"
            "**修场景是你的职责**（与出题同源知识 + 本轮执行证据）。\n"
            "- **MUST 按文末「原地修复协议」直接修场景文件并在 {result_path} "
            "申报 ``scenario-repaired``**；禁止申报 ``bug-found``（仅当你在修复过程"
            "中发现真产品缺陷——选择器/场景与源码对证为产品 bug——才允许改判 "
            "product-bug 并申报 bug-found）。\n"
            "- 本上轮清单场景：{id_line}——修复前先核对场景文件现状，确认缺陷"
            "根因后逐条修复（补自建夹具/seed、修正客观错误步骤与断言、补 "
            "depends_on 串接）。\n"
            "- **修复已裁决场景（含跨轮写回场景）合法**：受冻结 diff 记账保护，"
            "无理由的移除才会被确定性补齐——有理由的修复/移除不会被回补，"
            "不视为冻结违规。\n"
            "- 修完逐场景以 checkpoint 写回 report.json（test-defect + evidence 写明"
            "「场景文件缺陷：<改了什么、为什么>」），最后申报 scenario-repaired。\n"
        )
