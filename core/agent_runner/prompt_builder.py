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

import datetime
import json
import logging
import re
from pathlib import Path

# 框架根（与 core/spec_gen.py SCHEMA_DIR 同型推导）；agents/ 提示词目录
FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
AGENT_PROMPT_DIR = FRAMEWORK_ROOT / "agents"

# 可传播到 fenixd 已挂载 handler 的结构化日志器（与 pm_engine.spec_integrity 同型）
_logger = logging.getLogger("fenixd.agent_runner.prompt_builder")

# 未解析占位符扫描（add-code-review-auto-fix）：填充后残留的 {snake_case} 记
# warning——模板笔误/重命名占位符、条件键未注入（如非 verifier/fast-track 的
# progress_path）原样留在派发提示词属 fail-open，静默丢失预期注入。
_PLACEHOLDER_RE = re.compile(r"\{[a-z_]+\}")

# 全部 agent 类型 → 提示词文件名（agent-type 白名单的单一来源，Dashboard 端点复用）
# add-daily-self-review：新增 self-review（每日自省）类型。
# add-deliverable-declaration-triage：新增 dispute-judge（交付物缺件 LLM 终审）类型。
# add-framework-self-evolution：新增 evolution（框架自进化复核）类型。
# add-spec-review-gate：新增 spec-review（SPEC 方案评审）类型。
# add-code-review-agent-and-quality-tab：新增 code-review（周期性仓库级代码审查）类型。
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
    "code-review": "code-review.md",
    # add-code-review-auto-fix：新增 code-fix（自动修复车道 agent，可改码）。
    "code-fix": "code-fix.md",
}

# code-fix prompt {items} 注入字段白名单（09-23 提速）：台账原始行的框架
# 字段（project/review_id/review_kind/reviewed_at/spec/status/spec_name/
# fingerprint 等）对修复 agent 无用，注入只会稀释注意力与放大 prompt——
# 只保留定位与判定所需字段；None/缺失字段整键剔除。
_CODE_FIX_ITEM_FIELDS = (
    "item_id", "file", "line", "severity", "category",
    "title", "description", "suggestion",
)


def _str_field(value) -> str:
    """占位符填充前的字符串归一：dict/list 序列化为 JSON 串。

    占位符填充走 ``str.replace``，非字符串值会抛
    ``TypeError: replace() argument 2 must be str, not dict``。信号字段
    （尤其 ``evidence``）来自多条路径，历史/直发记录可能是结构化值。
    """
    if value is None or isinstance(value, str):
        return value or ""
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _single_pass_replace(template: str, values: dict[str, str]) -> str:
    """单趟多模式占位符填充：dict→compiled alternation，一次 re.sub 扫完。

    逐键 str.replace 是缺陷模式（code-review item 7975ab14dbe7）：会把上一键
    的替换结果作为下一键的替换对象——先注入的值（来自用户数据或 LLM 产物，
    常嵌入 {result_path}/{out_path} 等占位符字面量）被后续键二次替换、污染
    注入内容。re.sub 单趟扫描永不重扫替换文本，杜绝二次替换；不用
    str.format——prompt 正文含大量 {} JSON 示例。统一填充入口：主路径
    _fill_placeholders 与四条独立构建路径共用同一实现，防多份漂移。
    """
    if not values:
        return template
    return re.compile("|".join(re.escape(k) for k in values)).sub(
        lambda m: values[m.group(0)], template
    )


def _fill_and_scan_placeholders(
    template: str,
    values: dict[str, str],
    agent_type: str,
    context_id: str,
    label: str = "run_id",
) -> str:
    """独立构建路径与主路径共用收尾：单趟填充 + 未解析占位符残留扫描告警。

    code-review item ebd39ad068f3：self-review/evolution/code-review/code-fix
    四条独立构建路径（不走 _fill_placeholders）原先各自 _single_pass_replace
    后直接返回，仅 code-review 有残留扫描——模板漂移导致的注入静默丢失在
    其余三条车道不可见，与 add-code-review-auto-fix 的 fail-open 可观测口径
    不齐。统一收尾：扫描扣除 values 已知键（正文含合法 {snake_case} 字面量
    时不误报），残留记 warning 不阻断派发；日志消息结构沿用
    _build_code_review_prompt 既有实现（agent=<车道> <label>=<context_id>
    leftover=<残留键>）。独立路径用默认 label="run_id"（context_id 传 run
    token），主路径 _fill_placeholders 传 label="spec"（context_id 传
    spec_name）——同一收尾不再维护两份手写扫描拷贝。
    """
    out = _single_pass_replace(template, values)
    leftover = sorted(set(_PLACEHOLDER_RE.findall(out)) - set(values))
    if leftover:
        _logger.warning(
            "提示词占位符未解析（模板漂移，注入内容可能静默丢失）: "
            "agent=%s %s=%s leftover=%s",
            agent_type,
            label,
            context_id,
            leftover,
        )
    return out


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
    raise ValueError(f"planner_result_path 仅支持 planner-judge/planner-plan，收到 '{agent_type}'")


# planner 裁决结果文件顶层 status 白名单（fix-verdict-read-failclosed D3）。
# runner 产物硬门（_check_agent_result_artifact）与 pm_engine 读侧
# （_read_verifier_result）共用此单一来源——白名单外取值（如 implementer 共享
# 文件残留的 "success"/"error"）一律不得视作合法裁决。语义错位 status 若被
# 读侧当作 verified 放行即历史 fail-open 事故（add-verify-contract-autodraft）。
PLANNER_RESULT_STATUS_WHITELIST = (
    "verified",
    "bug-found",
    "plan-ready",
    "scenario-repaired",
)

# 评审结果 status 白名单（add-spec-review-gate）
SPEC_REVIEW_RESULT_STATUS_WHITELIST = (
    "approved",
    "repaired",
    "rejected",
)


def spec_review_result_path(project_root, spec_name: str) -> Path:
    """评审结果文件路径（add-spec-review-gate）。

    返回 <项目根>/.fenix/spec-review/<spec_name>/.fenix-run-result.json
    """
    return Path(project_root) / ".fenix" / "spec-review" / spec_name / ".fenix-run-result.json"


def impl_result_path(wt_path) -> Path:
    """实现者车道（implementer / fast-track）结果文件路径（fix-impl-resultfile-contract-gap D1）。

    返回 ``<worktree>/.fenix-run-result.json``；产物硬门（result_gate）与契约段
    （_result_gate_section）共用——注入/校验同源，与 planner_result_path /
    spec_review_result_path 同款约定。依赖方向 result_gate → prompt_builder 不可反
    （反向必成循环 import，使 test_agent_runner_modules_contract:71 红）。
    """
    return Path(wt_path) / ".fenix-run-result.json"


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

    def _fill_placeholders(
        self, template: str, agent_type: str, spec_name: str, detail: dict | None,
        wt_path: Path | None = None,
    ) -> str:
        """占位符填充：单趟多模式替换（正文含大量 {} JSON 示例，禁用 str.format）。

        progress_path 语义按 agent 现行为保持：verifier 写
        verify-progress/<spec>.json；fast-track 写 verify-progress/<spec>/<spec>.json。
        administrator 困境信号字段由 detail 注入（其余 agent 文件不含这些占位符）。
        wt_path: fast-track 的 {result_path} 落点（impl_result_path，与收工硬门
            _result_gate_section 同源）；不可得时降级相对路径表述。
        """
        root = self._pm.project_root
        vp_dir = root / ".fenix" / "verify-progress" / spec_name
        sig = detail or {}
        # add-judge-artifact-gate D1：planner 产物路径经 planner_result_path 统一
        # 计算（注入侧与 runner 硬门校验侧同源，防双实现漂移）。{result_path}/
        # {scenarios_path} 值按两类型产物文件名恒定——judge/plan 共用的
        # .fenix-run-result.json 与 test_scenarios.json 同此路径；fast-track 的
        # {result_path} 例外（下方分支改填 worktree 根——收工硬门唯一落点）。
        values = {
            "{spec_name}": spec_name,
            "{spec_dir}": f"spec/changes/{spec_name}",
            "{scenarios_path}": str(planner_result_path(root, spec_name, "planner-plan")),
            "{result_path}": str(planner_result_path(root, spec_name, "planner-judge")),
            "{report_path}": str(vp_dir / "report.json"),
            # add-judge-incremental-attribution：judge 归因产物逐场景条目文件。
            # 与 core/verify_engine/judge_files.py 的 JUDGE_ATTRIBUTION_FILENAME
            # 同源（注入侧路径 = 读侧路径，防双实现漂移）。
            "{judge_attribution_path}": str(vp_dir / "judge_attribution.json"),
        }
        if agent_type == "verifier":
            values["{progress_path}"] = str(
                root / ".fenix" / "verify-progress" / f"{spec_name}.json"
            )
        elif agent_type == "fast-track":
            values["{progress_path}"] = str(vp_dir / f"{spec_name}.json")
            # fast-track 结果文件唯一交付落点是 worktree 根（fix-impl-resultfile-
            # contract-gap D1：impl_result_path，收工硬门同源检查）——不得沿用上方
            # 主树 planner-judge 产物路径，agent 据此写主树会被硬门判产物缺失
            # 整轮重烧。wt_path 不可得时降级相对路径表述（同 _result_gate_section）。
            values["{result_path}"] = (
                str(impl_result_path(wt_path))
                if wt_path is not None
                else ".fenix-run-result.json（worktree 根目录）"
            )
        elif agent_type == "dispute-judge":
            # 交付物缺件 LLM 终审（add-deliverable-declaration-triage D3）：
            # 输入（缺件清单 + spec 语境 + findings + basename 候选）由 dispatch
            # 层落盘，结果契约由 judge 写回（与 planner 结果文件并置、独立命名）。
            values["{dispute_input_path}"] = str(vp_dir / "dispute_judge_input.json")
            values["{dispute_result_path}"] = str(vp_dir / "dispute_judge_result.json")
        elif agent_type == "spec-review":
            # SPEC 方案评审（add-spec-review-gate）
            values["{result_path}"] = str(spec_review_result_path(root, spec_name))
            values["{state_path}"] = str(root / ".fenix" / "STATE.md")
            # 自动复评上下文（2026-09-15 评审误判事故）：上一轮被否决时 STATE 的
            # error 内携带 blocking 摘要，注入复评 prompt 的「上轮否决结论」段。
            # 复评者据此逐条回答「是前提被证伪（判 blocking）还是文档内部不一致
            # （判 repairable 并就地修）」——把误判自愈在体系内的关键输入。
            # 非复评场景（首次评审）该键为空串，prompt 段指示「首次评审」。
            _prev_rej = ""
            try:
                _err = (self._pm.state_machine.read_one(spec_name) or {}).get("error") or ""
                if _err.startswith("spec-review-rejected:"):
                    _prev_rej = _err[len("spec-review-rejected:") :].strip()
            except Exception:  # noqa: BLE001 — 注入失败不得阻断派发
                _prev_rej = ""
            values["{prev_review_rejection}"] = _prev_rej
        values.update(
            {
                # 信号字段统一走 _str_field（历史/直发记录可能是结构化值，非字符串
                # 到达 str.replace 抛 TypeError 中止整个提示词构建——归一不对称防回归）。
                "{sig_type}": _str_field(sig.get("signal_type")) or "unknown",
                "{sig_spec}": _str_field(sig.get("spec")) or spec_name,
                "{severity}": _str_field(sig.get("severity")) or "major",
                "{description}": _str_field(sig.get("description")),
                "{evidence}": _str_field(sig.get("evidence")),
                "{recommendation}": _str_field(sig.get("recommended_action")),
                # 旧全局路径 .fenix/admin_disposition.json 已废弃不再读写
                # （maintenance_runs.py），无 disposition_path 时留空——兜底指向
                # 废弃位置会把管理员导向永不被告知读取的写入点。
                "{disp_path}": _str_field(sig.get("disposition_path")),
                "{dash_script}": f"{root}/.fenix/bin/fenix_dashboard.py",
            }
        )
        # 一次性多模式替换（code-review item 7975ab14dbe7）：逐键 str.replace 会把
        # 上一轮结果作为下一键的替换对象——注入值（信号 evidence 常嵌入 run 产物
        # 路径与提示词片段）本身含 {result_path} 等占位符字面量时被后续键二次
        # 替换、污染注入内容。re.sub 单趟扫描永不重扫替换文本，杜绝二次替换。
        # 廉价后置检查（add-code-review-auto-fix）：存在未解析占位符记 warning，
        # 不阻断派发（fail-open），但让模板漂移导致的注入静默丢失在日志可见。
        # 与四条独立构建路径共用同一收尾 _fill_and_scan_placeholders（原手写拷贝
        # 仅日志字段不同，已参数化），日志按本路径维度记 spec=<spec_name>。
        return _fill_and_scan_placeholders(
            template, values, agent_type, spec_name, label="spec"
        )

    def _build_prompt(
        self,
        spec_name: str,
        agent_type: str,
        detail: dict | None = None,
        wt_path: Path | None = None,
    ) -> str:
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

        # add-code-review-agent-and-quality-tab：周期/手动代码审查 run prompt
        # 独立构建（无 spec 维度占位符，注入 manifest 文件清单、审查窗口与
        # 增量落盘路径）。
        if agent_type == "code-review":
            return self._build_code_review_prompt(spec_name, detail or {})

        # add-code-review-auto-fix：code-fix（自动修复车道）run prompt 独立
        # 构建（无 spec 维度占位符，注入本批条目 JSON、产物路径与 worktree）。
        if agent_type == "code-fix":
            return self._build_code_fix_prompt(spec_name, detail or {})

        template = self._load_agent_template(agent_type)
        prompt = self._fill_placeholders(
            template, agent_type, spec_name, detail, wt_path=wt_path)

        if agent_type == "implementer":
            # 上轮 error 上下文注入（add-implementer-deliverable-gate D4）+
            # 恢复重派遗产上下文（add-recovery-legacy-check 2.1/2.2）。
            prompt += self._prev_error_section(spec_name)
            # 上轮结构化诊断注入（fix-run-hang-amplification 2.4）：重派 attempt
            # 继承终态类型/归因/结论/进度，无诊断时零注入。
            prompt += self._impl_diagnosis_section(spec_name)
            prompt += self._build_legacy_section(spec_name)
            # 中断恢复保留续做注记（interrupt-recovery-preserve 2.3）：本轮 dispatch
            # 在保留分支的 worktree 内 resume 续做时注入继承说明。
            prompt += self._recovery_resume_note(spec_name)
            # 任务进度契约段（fix-implementer-task-progress D1）：full/fast-track
            # 两个 implementer 分支共用同一文本，保证 harness TaskCreate/TaskUpdate
            # 行为与 tasks.md 编号对齐（进度可见性断链的根治点）。
            prompt += self._task_progress_contract_section(spec_name)
            # 结果文件硬门契约段（fix-impl-resultfile-contract-gap D1/D2）：
            # 告知实现者「不写结果文件 = run 失败 + 原地重派」，闭合「硬门在拦、
            # 提示词不说」的反馈断链。注入点与 fast-track 共用同一函数（路径按
            # agent_type 分派），置于任务进度契约段之后、声明现实处方之前。
            prompt += self._result_gate_section(
                spec_name, "implementer", wt_path=wt_path)
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
            # evo-planner-scenario-schema-alignment 2.1：断言/操作 schema 单源注入
            # （planner-plan 是第一条会重写 test_scenarios.json 断言/操作结构的车道）
            prompt += self._scenario_schema_section()
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
            # evo-planner-scenario-schema-alignment 2.4：第三条写入车道——judge
            # 原地修复协议要求其直接改写 {scenarios_path} 的步骤与断言
            # （agents/planner-judge.md 原地修复协议），同样注入 schema 单源段。
            prompt += self._scenario_schema_section()
        elif agent_type == "fast-track":
            # 任务进度契约段（fix-implementer-task-progress D1，与 full 分支共用
            # 同一文本；fast-track 的 PHASE 1 主体已迁移 agents/fast-track.md）。
            prompt += self._task_progress_contract_section(spec_name)
            # 结果文件硬门契约段（fix-impl-resultfile-contract-gap D1/D2）：
            # 与 implementer 共用同一函数，路径按 agent_type 分派（fast-track 在
            # worktree 根写 .fenix-run-result.json，含 verification 段）。
            prompt += self._result_gate_section(
                spec_name, "fast-track", wt_path=wt_path)
            # 之前只有 implementer 分支注入 prev_error，fast-track 打回后新 run
            # 完全不知道上次为何失败（fix-implementer-task-progress 三连打回）。
            prompt += self._scenario_freeze_section(spec_name)
            prompt += self._interaction_contract_section(spec_name)
            prompt += self._designed_ids_line(
                self._pm.project_root
                / ".fenix"
                / "verify-progress"
                / spec_name
                / "test_scenarios.json"
            )
            prompt += self._prev_error_section(spec_name)
            # 上轮结构化诊断注入（fix-run-hang-amplification 2.4，与 implementer 分支共用）。
            prompt += self._impl_diagnosis_section(spec_name)
            # 恢复来源择一注入（fix-fasttrack-recovery-resume D6）：恢复续做命中
            # （mark_reused 带 recovery=True，经 require_recovery=True 判据命中）时
            # 注入「中断恢复续做」注记；普通打回重派/瞬断重试轮（复用痕迹存在但
            # 无恢复来源标记）MUST 退回既有 Worktree 继承注记——不得让普通重派轮
            # 丢失继承说明，也不得向普通重派轮注入「曾因 daemon 重启被中断」的
            # 错误归因文案（design D6）。两条语义重叠，MUST NOT 同时注入。
            note = (
                self._recovery_resume_note(spec_name, require_recovery=True)
                or self._fast_track_reuse_note(spec_name)
            )
            prompt += note
            # evo-planner-scenario-schema-alignment 2.1/2.3：fast-track 的 PHASE 2
            # 自行生成并写入 test_scenarios.json（第二条写入车道），注入同一 schema
            # 单源段；agents/fast-track.md 内联的第二份枚举已收敛到本段。
            prompt += self._scenario_schema_section()
        elif agent_type == "spec-review":
            # 结果文件硬门契约段（2026-09-15 事故修复）：此前评审车道缺本段，
            # 模型把结果 JSON 当正文输出、结果文件从未落盘 → 整轮白烧重试。
            prompt += self._result_gate_section(spec_name, "spec-review")
            # 重试上下文：上轮失败死因注入（同 implementer/fast-track 的
            # _prev_error_section）。缺本段时评审重试是盲重试，不知道为什么被重派。
            prompt += self._prev_error_section(spec_name)
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
            # evo-planner-scenario-schema-alignment 2.4 边界（显式保持）：admin
            # 修复通道**不注入** schema 段——其约束段已机械告知「写回必过
            # validate_scenario_dicts 门 + 按框架回传的逐条错误清单重修」，走
            # 门+错误清单自纠闭环，不依赖先验 schema 知识；此边界为有意选择，
            # 不得顺手给 admin 也加注入段。

        # 非交互契约段（fix-agent-noninteractive-contract D1）：统一收尾处
        # 无条件注入——所有模板型 agent（implementer/verifier/fast-track/
        # planner-plan/planner-judge/spec-review/administrator/dispute-judge）
        # 自动继承，新增 agent 类型进白名单即生效。位置固定：agent_type 特异
        # 动态段与 administrator 段之后、项目级附加段之前（保护「项目级附加段
        # 位于 prompt 末尾」约定，不得插到 _project_extra_section 之后）。
        prompt += self._noninteractive_contract_section()

        # fix-agent-lane-efficiency D2/D4：长车道效率/取证深度/长任务三段动态
        # 契约段，按 agent_type 注入（implementer / fast-track / spec-review 三
        # 车道；其它类型零注入返回空串）。位置：非交互契约段之后、项目级附加段
        # 之前（遵守「项目级附加段在 prompt 末尾」约定，不得插到其之后）。
        prompt += self._tool_call_efficiency_section(agent_type)
        prompt += self._forensic_depth_section(agent_type)
        prompt += self._long_task_wait_section(agent_type)

        # add-impl-ocr-parallel-lane（任务 5.1）：ocr 修复轮 findings 注入——
        # 统一收尾处注入（非交互契约段之后、项目级附加段之前），只覆盖两条实现
        # 车道；框架侧 join 打回时写 ocr_findings_directive.json，非打回轮文件
        # 缺失零注入（prompt += "" 逐字节不变）。收尾 ocr 审查本身已由实现者
        # 内联义务退役为框架侧异步车道（impl-ocr-parallel-lane），实现者不再
        # 在收工前自跑 ocr。
        if agent_type in ("implementer", "fast-track"):
            prompt += self._ocr_findings_section(spec_name)

        # add-quality-gates-visibility（任务 3.1）：质量门禁落盘契约注入——
        # 独立段，与收尾审查段无耦合；同样只覆盖两条实现车道（fast-track 收尾
        # 同样落盘门禁数据），统一收尾处、项目级附加段之前。
        if agent_type in ("implementer", "fast-track"):
            prompt += self._quality_gates_section(spec_name)

        # add-impl-selfcheck-model-probe（1.2/3.1）：收工自证契约段——自检
        # CLI 完整命令 + dispositions 正反例 + status/必填键固化说明。统一
        # 收尾处注入（项目级附加段之前），只覆盖两条实现车道（fast-track
        # 收尾同样写结果文件，同等受自检义务约束）。
        if agent_type in ("implementer", "fast-track"):
            prompt += self._selfcheck_section(spec_name, wt_path)

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
            self._pm.project_root
            / ".fenix"
            / "verify-progress"
            / spec_name
            / "contract_findings.json"
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
            lines.append(f"- `{rid}` [{sev}]: {msg}" + (f"\n  evidence: {ev}" if ev else ""))
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

    def _noninteractive_contract_section(self) -> str:
        """中央「非交互契约」段（fix-agent-noninteractive-contract D1/D3）。

        声明本 agent 以 headless、无人值守方式运行、**无法与人类交互**。单一
        真相：在 ``_build_prompt`` 统一收尾处注入（agent 类型白名单
        ``AGENT_PROMPT_FILES`` 新增类型自动继承，无需逐个改 ``agents/*.md``）；
        repair / self-review / evolution / code-review / code-fix 五条独立构建
        路径在各自 ``return`` 前就地追加（D2）。纯静态文本、零 IO、零状态条件，
        幂等可重复注入（D4）。

        四组规范性语义（spec requirement「非交互契约段的关键语义」）：
        1. 无人类可交互/无人值守——不存在能回复本 agent 的人；
        2. 遇计划或分叉直接执行、不请求批准，难以撤销的操作按 SPEC/tasks
           授权推进并在结果文件/处置记录留痕；
        3. 禁止为等待人类回复而结束回合（end_turn），无法继续时按本车道
           契约的失败出口（partial/error/相应终态）收工；
        4. 显式覆盖 Claude Code 系统提示词默认框架（interactive agent /
           「难以撤销的操作先确认」/ plan mode / brainstorming 等交互式
           工作流）在 Fenix run 中不适用。
        """
        return (
            "\n\n## 非交互契约（non-interactive contract，强制，"
            "fix-agent-noninteractive-contract）\n"
            "- 你是**无人值守的 headless agent**（`claude -p`）："
            "**没有能回答你的人**。任何「是否继续 / 请确认 / 等待回复」都会"
            "整轮空转、被判失败并重烧预算。\n"
            "- 遇到计划或分叉：**直接执行**，不请求批准；难以撤销的操作按 "
            "SPEC/tasks 授权推进，事后在结果文件/处置记录中留痕。\n"
            "- 禁止为「等人回复」而结束回合（`end_turn`）；要么继续推进，"
            "要么按各自契约的失败出口（`partial` / `error` / 相应终态）收工。\n"
            "- Claude Code 系统提示词中的默认框架（`interactive agent`、"
            "「难以撤销的操作先确认」，以及 `plan mode` / `brainstorming` "
            "等交互式工作流）在 Fenix run 中**不适用**。\n"
        )

    # ── fix-agent-lane-efficiency D2：长车道效率/取证深度/长任务三段动态契约 ──
    # 规范性提示词文本（不设框架侧工具拦截，见 design D2/D4）。按 agent_type
    # 注入 implementer / fast-track / spec-review 三车道；条件不满足返回空串
    #（prompt += "" 逐字节不变）。位置固定：非交互契约段之后、项目级附加段
    # 之前（test_prompt_lane_efficiency_sections 断言顺序不变式）。

    _EFFICIENCY_LANES = ("implementer", "fast-track", "spec-review")

    def _tool_call_efficiency_section(self, agent_type: str) -> str:
        """工具调用效率契约段（spec agent-tool-call-efficiency）。

        三条 MUST：批量并行、定向读取（Grep / 带范围 Read）、同 run 去重。
        仅注入 _EFFICIENCY_LANES；其它 agent_type 返回空串。
        """
        if agent_type not in self._EFFICIENCY_LANES:
            return ""
        return (
            "\n\n## 工具调用效率（fix-agent-lane-efficiency，强制）\n"
            "- **批量并行**：同一轮内相互独立、无数据依赖的工具调用（多个读取/"
            "检索）MUST 合并为一次批次一次性提交，MUST NOT 逐个串行提交。\n"
            "- **定向读取**：定位代码或内容 MUST 优先用 `Grep` / 带范围参数的"
            " `Read`，MUST NOT 对未发生变更的大文件反复整文件读取。\n"
            "- **同 run 去重**：同一 run 内已读取且未变更的文件 MUST NOT 重复"
            "整文件读取（需复核时用范围读或检索）。\n"
        )

    def _forensic_depth_section(self, agent_type: str) -> str:
        """取证深度上限与输出裁剪段（spec agent-tool-call-efficiency）。

        取证以「最小可判反证」为限（评审判 blocking vs repairable、实现不重复
        重跑）；大块输出 MUST 裁剪后入对话。仅注入 _EFFICIENCY_LANES。
        """
        if agent_type not in self._EFFICIENCY_LANES:
            return ""
        return (
            "\n\n## 取证深度上限与输出裁剪（fix-agent-lane-efficiency，强制）\n"
            "- **取证深度上限**：取证 MUST 以**足以判定结论的最小可判反证**为限"
            "。评审车道判定 `blocking`（前提被证伪）vs `repairable`（文档内可修）"
            "所必需的最小证据之外，MUST NOT 为完整复现 SPEC 的每条断言而穷尽探测"
            "/重跑；实现车道不得为「完整复现」而重复重跑全量套件。\n"
            "- **输出裁剪**：可能产生大块输出的命令（探针/日志/构建）MUST 裁剪"
            "输出——用 `head -c` / 只取关键行 / 落临时文件后只回读关键片段——"
            "MUST NOT 将数十 KB 原始输出整块投入对话上下文。\n"
        )

    def _long_task_wait_section(self, agent_type: str) -> str:
        """长任务前台等待段（fix-agent-lane-efficiency，D4）。

        一次后台启动 + 显式轮询输出文件；MUST NOT 用 sleep / 周期性 ps 自旋；
        有界入口（超时内必返回）优先前台直接跑。

        **能力事实（2026-09-21 更正）**：非交互派发（`claude -p`）下既无
        `ScheduleWakeup` 定时唤醒，后台 Bash 任务的**完成通知也不会送达**——
        run 结束当前 turn 即进程终止，后台子进程随之被杀。「后台启动 + 等通知」
        在本模式下与「启动即忘」等价（writepath 冻结事故：模型依旧文案起后台
        回归等通知 → 每轮 partial 占位 → 同因熔断）。旧文案「完成通知真实可用」
        已废弃。

        仅注入实现者两条车道（implementer / fast-track）。
        """
        if agent_type not in ("implementer", "fast-track"):
            return ""
        return (
            "\n\n## 长任务前台等待（fix-agent-lane-efficiency，强制）\n"
            "- **两类后台能力均不可用于等待**：非交互派发（`claude -p`）下"
            "既无 `ScheduleWakeup` 定时唤醒，后台 Bash 任务的**完成通知也不会"
            "送达**——run 结束当前 turn 即进程终止，后台子进程随之被杀。"
            "「后台启动 + 等通知」在本模式下与「启动即忘」是同一件事。\n"
            "- **有界入口优先前台直跑**：可能超过 600s 工具上限的长任务（全量"
            "回归、大范围构建、超时探针等），若存在受硬超时约束、必在返回前给"
            "出完整结果的有界入口（如 `bin/run_full_suite.py --timeout <t>`），"
            "MUST 直接前台跑该入口。\n"
            "- **无有界入口才用后台**：确无有界入口且任务可能无限期运行时，"
            "才用**一次**后台调用（`run_in_background: true`）启动；启动后"
            "MUST NOT 在等待期间收工——必须显式 `Read` 该后台任务的**输出"
            "文件**（`output-file` 路径）确认完成或失败，MUST NOT 依赖任何"
            "「完成通知」。\n"
            "- **禁止空转**：MUST NOT 用 `sleep` / 周期性 `ps` 空转模拟等待。\n"
        )

    def _ocr_findings_section(self, spec_name: str) -> str:
        """ocr 修复轮 findings 注入段（add-impl-ocr-parallel-lane，任务 5.1）。

        文件驱动（对齐 `_scenario_reroute_directive_section` 手法）：框架侧 join
        裁决在 gate 档打回时把 findings 清单写入主树
        ``.fenix/verify-progress/<spec>/ocr_findings_directive.json``，本段读同
        一文件生成注入；非打回轮文件缺失/不可读 → 零注入（空串）。

        覆盖三块义务：findings 清单（逐条 path/line/category/severity/content）；
        disposition 处置契约（fixed/rejected/deferred 三值，rejected/deferred
        MUST 附非空 reason——复用既有 disposition 语义）；修码后重验要求（定向
        测试 + 全量回归走有界入口 `bin/run_full_suite.py` 前台直跑）。

        路径语义（沿用 fix-impl-code-review-writepath 教训）：给实现者的处置
        登记路径一律是 **worktree 相对路径**（实现者在自己的 worktree 内写
        ``.fenix/verify-progress/<spec>/code-review.json`` 的逐条 disposition，
        经既有拷回通道单向 worktree→主树）；本段 MUST NOT 出现主树绝对路径字样。
        本段自身读框架写的 directive 文件走主树路径（框架侧读，与实现者写侧
        分离），该主树路径不出现在注入文本中。
        """
        directive_path = (
            self._pm.project_root
            / ".fenix"
            / "verify-progress"
            / spec_name
            / "ocr_findings_directive.json"
        )
        try:
            raw = directive_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError):
            return ""
        if not isinstance(data, dict):
            return ""
        findings = data.get("findings")
        if not isinstance(findings, list) or not findings:
            return ""
        try:
            round_no = int(data.get("round", 1) or 1)
        except (TypeError, ValueError):
            round_no = 1
        max_rounds = data.get("max_rounds", 1)
        lines = [
            "\n\n## ocr 代码审查 findings 修复义务（impl-ocr-join-gate，强制）\n"
            f"你本轮是被框架侧 ocr 代码审查车道打回的**修复轮**"
            f"（第 {round_no} 轮，修复轮上限 {max_rounds} 次——达上限后仍出现的 "
            "findings 将全部转入 code-review 台账、不再打回）。以下是逐条 findings，"
            "它们是你的**修复义务**：\n"
        ]
        for i, f in enumerate(findings, start=1):
            if not isinstance(f, dict):
                continue
            loc = str(f.get("path") or f.get("file") or "?")
            start_line = f.get("start_line", f.get("line", "?"))
            category = str(f.get("category") or "general")
            severity = str(f.get("severity") or "info")
            content = str(f.get("content") or f.get("description") or "").strip()
            if len(content) > 600:
                content = content[:600] + "…"
            lines.append(
                f"{i}. `{loc}:{start_line}` [{severity}/{category}] {content}\n"
            )
        artifact_rel = f".fenix/verify-progress/{spec_name}/code-review.json"
        lines.append(
            "### disposition 处置契约（机械对账）\n"
            "对上面每条 finding 逐条评估「真实问题 vs 误报」，**修正真实问题的"
            "裁量权归你**（发现的真实问题应修正）；并把处置登记到 "
            f"`{artifact_rel}`（**相对当前工作目录（worktree）的相对路径**，"
            "MUST NOT 用主树绝对路径）：文件不存在则按该路径新建，结构为 "
            '`{"status": "completed", "findings": [...]}`；在对应 finding 对象上'
            "增写两个字段：\n"
            '- `"disposition"`：`"fixed"`（已修码）/ `"rejected"`（误报驳回）/'
            ' `"deferred"`（本轮不修）；\n'
            '- `"reason"`：`rejected`/`deferred` MUST 附**非空**理由'
            "（fixed 可附验证方式）。\n"
            "逐条都须有处置——缺处置的 finding 视为未裁决，下轮 join 仍按"
            "「非 rejected findings」计数。\n"
            "### 修码后重验（强制）\n"
            "修码完成后 MUST 重验，MUST NOT 跳过：\n"
            "1. **定向测试**：先跑与本轮改动直接相关的测试文件/用例，全绿；\n"
            "2. **全量回归**：走有界入口 `python3 bin/run_full_suite.py "
            "--timeout 3600` **前台直跑**（它自身受硬超时约束必在返回前给出完整"
            "结果），MUST NOT 裸调 `pytest tests/` 无限等待；与基线对比零引入失败。\n"
            "3. 完成后照常逐项勾选 tasks.md、提交、写 `.fenix-run-result.json` "
            "收工。merge-back 成功后框架侧车道会对增量自动重审，你 **MUST NOT** "
            "自己跑 ocr。\n"
        )
        return "".join(lines)

    def _quality_gates_section(self, spec_name: str) -> str:
        """质量门禁落盘契约段（add-quality-gates-visibility，任务 3.1）。

        对 implementer / fast-track 无条件注入（落盘是 prompt 软约束，读侧
        fail-open，无配置开关）。内容按 spec 逐字固化：路径、顶层 schema、
        gate-id 全集（run 内自查 3 项，**无 code-review 键**——ocr 由框架侧
        异步车道执行，add-impl-ocr-parallel-lane）、status 四值枚举、渐进更新
        要求、frontend-build 条件执行语义、父目录创建指示、读侧双位置兜底。

        与 `_impl_code_review_section` 无耦合：本段不含 ocr 命令与
        code-review.json 字样，两段可独立增删。
        """
        path = f".fenix/verify-progress/{spec_name}/quality-gates.json"
        return (
            "\n\n## 质量门禁落盘（quality-gates.json，强制）\n"
            "收尾检查阶段（全部 tasks.md 任务完成并提交之后、写 `.fenix-run-result.json`"
            "之前）逐项完成 run 内自查（`frontend-build` / `interaction-contract` "
            "两项常规执行；`full-suite` 仅降级路径执行，见下），并把结果**渐进**写入 "
            "worktree 内相对路径：\n"
            f"`{path}`\n"
            "- **写入前先创建父目录**：`.fenix/verify-progress/<spec>/` 子目录在新建 "
            "worktree 中不保证存在（`.fenix/` 运行时目录经 .gitignore 不入库），须先以 "
            "mkdir -p 语义创建再写。\n"
            "- **顶层 schema 固定**：`{\"gates\": {<gate-id>: {\"status\": <枚举>, "
            "...详情键}}, \"updated_at\": \"<UTC ISO8601>\"}`。键名 MUST 与本段逐字"
            "一致，禁止同义改写（历史键名漂移事故教训）。\n"
            "- **gate-id 全集（仅 3 项，无第 4 项）**：`full-suite`（全量回归测试）/ "
            "`frontend-build`（前端构建与类型检查）/ `interaction-contract`（交互契约"
            "自查）。**没有 `code-review` 一项**——ocr 代码审查与处置由框架侧异步车道"
            "执行，不在 run 内自查之列，你 MUST NOT 向本文件写 `code-review` 键（写了"
            "也被读侧忽略）。\n"
            "- **full-suite 降级路径（add-impl-selfcheck-model-probe 3.1）**：全量"
            "回归由验证链执行，收尾**默认不跑回归、也不写 `full-suite` 键**（读侧"
            "按数据源优先级呈现，缺项零打回）；仅当确认框架侧回归产物不可用"
            "（如验证链被冻结/跳过）时才在 run 内执行并落盘该键。\n"
            "- **status 四值枚举**：`passed` / `failed` / `running` / `skipped`；"
            "未写入的 gate-id 由读侧视为 pending。\n"
            "- **渐进更新**：每完成一项检查即**全量重写**该文件（小文件原子重写，"
            "无并发写者），让 Dashboard 在 run 进行中即可见进展——不得等收工一次性写。\n"
            "- **frontend-build 条件执行**：仅当本次改动涉及前端"
            "（`core/dashboard/static/`）时执行构建与类型检查；无前端改动时写 "
            "`{\"status\": \"skipped\", \"reason\": \"<非空中文说明>\"}`（skipped "
            "MUST 附非空 reason）。\n"
            "- **full-suite 详情键**：可附 `passed` / `failed` 计数，如 `{\"status\": "
            "\"passed\", \"passed\": 128, \"failed\": 0}`；failed 时建议附 "
            "`reason`。\n"
            "- **双位置兜底**：读侧对 worktree/主树双位置 fail-open 兜底——本 run "
            "正常写 worktree 相对路径即可；fast-track 车道持主树 verify-progress "
            "写授权，允许直落主树同名目录，两种落点读侧均可见。\n"
        )

    def _selfcheck_section(self, spec_name: str, wt_path: Path | None = None) -> str:
        """收工自证契约段（add-impl-selfcheck-model-probe 1.2）。

        把 daemon 侧收工硬门的自检 CLI（``python3 -m core.agent_runner.result_gate
        --selfcheck``）与结果文件形状契约注入实现者收尾检查：agent 在退出前即可
        发现 dispositions 字符串数组等形状陷阱并修复，不再依赖 daemon 侧打回整轮
        重派（add-impl-ocr-parallel-lane r2/r3 连烧实证）。

        单源纪律：status 枚举取自 ``AgentRunner._IMPL_RESULT_STATUSES``、
        disposition 白名单取自 ``result_gate.DISPOSITION_WHITELIST``（均惰性
        导入，prompt_builder 模块层 MUST NOT import result_gate——result_gate
        反向依赖本模块，模块层互 import 会成环），MUST NOT 在本段另写一份
        可能与校验体漂移的字面量。正反例 JSON 片段逐字固化（spec 契约措辞）。
        """
        if wt_path is not None:
            result_path = str(impl_result_path(wt_path))
        else:
            result_path = ".fenix-run-result.json（worktree 根目录）"
        from core.agent_runner.runner import AgentRunner
        from core.agent_runner.result_gate import DISPOSITION_WHITELIST

        statuses = " / ".join(f'`"{s}"`' for s in AgentRunner._IMPL_RESULT_STATUSES)
        dispositions = " / ".join(f'`"{d}"`' for d in DISPOSITION_WHITELIST)
        return (
            "\n\n## 结果文件收工自证（result-gate selfcheck，强制，"
            "add-impl-selfcheck-model-probe）\n"
            "- **结果文件写完必跑自检、非零退出不得收工**：`.fenix-run-result.json` "
            "写完（含每次修复改写后）MUST 立即运行：\n"
            f"  `python3 -m core.agent_runner.result_gate --selfcheck {result_path}`\n"
            "  它与 daemon 侧收工硬门同源（同一校验函数对象，零网络零 daemon 依赖，"
            "只读不写）。退出码 0=PASS；**非零退出不得收工**——按 stderr 逐条违规"
            "明细（含字段路径与期望形态）修复后重跑自检，直至退出码 0 再继续收尾。\n"
            "- **status 必填键固化**（以校验体为单源）：顶层 `status` 枚举仅 "
            f"{statuses}；`spec`/`summary` 必填；`status=\"success\"` 时 "
            "`completed_tasks` 数组必填且与 tasks.md 勾选集合逐条一致；"
            "`status=\"partial\"` 时 `completed_tasks` + `unfinished` "
            "（+ 可选 `unattainable`）申报必须能对上全部数字任务。\n"
            "- **dispositions 形状正反例**（逐字对照，字符串数组是历史连烧两轮的"
            "实锢单点）：若结果文件含 `code_review` 段，`dispositions` MUST 为"
            "**对象数组**——\n"
            "  - 合法正例：`[{\"disposition\": \"fixed\"}, {\"disposition\": "
            "\"deferred\", \"reason\": \"<非空理由>\"}]`\n"
            "  - 非法反例：`[\"fixed\", \"fixed\"]`（字符串数组必被硬门拒绝）\n"
            f"  - 每项 `disposition` 枚举仅 {dispositions}；`rejected`/`deferred` "
            "MUST 附非空 `reason`。\n"
        )

    def _project_extra_section(
        self, agent_type: str, spec_name: str = "", wt_path: Path | None = None
    ) -> str:
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
            self._pm.project_root / ".fenix" / "verify-progress" / spec_name / "REPLAN_FEEDBACK.md"
        )
        if not replan_fb_path.exists():
            return ""
        try:
            fb_text = replan_fb_path.read_text(encoding="utf-8")[:3000]
        except (OSError, UnicodeDecodeError):
            return ""
        return (
            f"\n## ⚠️ 上一轮场景验收未通过（MANDATORY：逐条修复后再输出）\n\n"
            f"{fb_text}\n\n"
            f"上述错误清单来自验收器，必须在本轮输出中全部修正；"
            f"若沿用上一轮场景文件原样重写，验收将再次拒绝并消耗重排预算。\n"
        )

    def _impl_diagnosis_section(self, spec_name: str) -> str:
        """上轮结构化诊断注入段（fix-run-hang-amplification 2.4）。

        implementer 与 fast-track 共用：重派 attempt 注入上轮 run 的结构化诊断摘要
        （终态类型 + 归因 + 已定性结论 + 已提交进度），新 run 据此直接调整策略而非
        从零重复探测同一阻塞（run-budget-continuity 要求）。无诊断时返回空串
        （prompt 与现状逐字节一致）。

        fix-impl-resultfile-contract-gap 2.2：诊断以 JSON 字符串存储，解析失败
        （非法 JSON）降级为原文截断呈现而非抛错；attribution / conclusion 渲染
        各自截断（500 / 800 字）避免重试轮提示词膨胀。`error` 原文内含 attribution
        子串系两字段同源（均取自 final_error，dispatch.py:1319-1333/1538-1603），
        不计为重复渲染（字段级判据，D3）。
        """
        diag_raw = ""
        try:
            entry = self._pm.state_machine.read_one(spec_name) or {}
            diag_raw = entry.get("_impl_diagnosis") or "" if isinstance(entry, dict) else ""
        except Exception:
            return ""
        if not isinstance(diag_raw, str) or not diag_raw.strip():
            return ""
        try:
            diag = json.loads(diag_raw)
        except (ValueError, TypeError):
            # 解析失败：降级为原文截断呈现（2.2），MUST NOT 抛错——重派轮仍
            # 携带上轮死因文本（哪怕结构损坏），不静默丢弃。
            return (
                f"\n\n## Previous run diagnosis (raw, inherited by this attempt)\n"
                f"Use this raw diagnosis text to adjust your strategy — do NOT "
                f"repeat the same detection:\n\n{diag_raw.strip()[:500]}\n"
            )
        if not isinstance(diag, dict) or not diag.get("terminal"):
            return ""
        # progress 守卫（code-review item 4fb225d924c3）：存储诊断可含
        # "progress": null 或非 dict（与上文 json.loads / 非 dict 守卫同源
        # 的脏数据面），.get 默认值仅在键缺席时生效——链式 .get 会抛
        # AttributeError 中断重派 attempt 的提示词构建，与 fail-safe 姿态
        # 不符。非 dict 一律按空 dict 缺省呈现。
        progress = diag.get("progress")
        if not isinstance(progress, dict):
            progress = {}
        branch = progress.get("branch") or "unknown"
        tasks = progress.get("tasks_checked")
        # 截断守卫（2.2）：attribution / conclusion 各自截断防提示词膨胀。
        attr = str(diag.get("attribution") or "")[:500]
        conc = str(diag.get("conclusion") or "")[:800]
        return (
            f"\n\n## Previous run diagnosis (structured, inherited by this attempt)\n"
            f"Use this diagnosis to adjust your strategy — do NOT repeat the same detection:\n\n"
            f"- terminal: {diag.get('terminal')}\n"
            f"- attribution: {attr}\n"
            f"- conclusion: {conc}\n"
            f"- progress: branch={branch}, tasks_checked={tasks}\n"
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

        仅对有 ``## Deliverables`` 声明段的 SPEC 干跑：以统一解析入口
        （add-declaration-relocation-protocol D1，分支/worktree 优先、主树回退，
        与收工守卫同源）取原始条目（path+kind），对每个 new/modify/delete
        路径做主树存在性检查与 basename 匹配，产出快照：

        ``{"entries": [{"path", "kind", "exists", "candidates"}]}``

        reference 条目仅保留 kind/exists（软校验，不做候选匹配）；delete 条目
        保留 kind 与 exists（其主树存在性语义不同——存在即删除目标确认、不存在
        即无可删疑似笔误，见 ``_declared_reality_section``），主树不存在时同样
        纳入 basename 候选匹配（add-deliverable-delete-kind 5.1：候选条件与
        new/modify 同源，供「无可删+候选」处方出词）。无声明段、
        spec 目录读取失败或任何干跑异常 → ``None``（fail-open，跳过注入，
        派发照常——2.3）。

        Returns:
            快照 dict 或 None。
        """
        from core.deliverables import match_basename_in_tree, resolve_effective_declaration

        # 分支/worktree 上下文：派发时从 spec 状态与 worktree_manager 解析
        branch = None
        worktree_path = None
        try:
            entry = self._pm.state_machine.read_one(spec_name) or {}
            branch = entry.get("branch") or None
            if branch:
                wm = getattr(self._pm, "worktree_manager", None)
                if wm is not None:
                    worktree_path = wm.find_worktree_path(branch)
        except Exception:
            pass
        try:
            resolved = resolve_effective_declaration(
                spec_name,
                branch=branch,
                worktree_path=worktree_path,
                project_root=self._pm.project_root,
            )
            entries = resolved["entries"]
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
            if kind in ("new", "modify", "delete") and not item["exists"]:
                try:
                    item["candidates"] = match_basename_in_tree(self._pm.project_root, path)
                except Exception:
                    item["candidates"] = []
            snap.append(item)
        return {"entries": snap}

    def _declared_reality_section(self, spec_name: str) -> str:
        """派发前声明现实处方注入段（add-deliverable-declaration-triage D2/PR2 2.2）。

        快照存在（有声明段 SPEC）时把「声明清单 × 仓库现实」注入 implementer
        提示词：存在的 modify 路径标注为修改目标；不存在的 new/modify 路径标注
        并列出全部 basename 命中候选（若有）。delete 条目按其特有语义出词
        （add-deliverable-delete-kind 5.2）：主树存在 → 「删除目标确认」；
        主树不存在 → 「无可删，疑似声明笔误」+ 候选；MUST NOT 复用 modify 的
        「修改目标确认」表述。文案约定：判断声明路径系笔误时
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
                if kind == "delete":
                    lines.append(f"- `{path}`（kind: {kind}）——主树存在，删除目标确认。")
                else:
                    lines.append(f"- `{path}`（kind: {kind}）——主树存在，修改/引用目标确认。")
            else:
                note = ""
                if cands:
                    note = f"；basename 命中候选：{'、'.join(cands)}"
                if kind == "delete":
                    lines.append(
                        f"- `{path}`（kind: {kind}）——主树不存在，无可删，" f"疑似声明笔误{note}。"
                    )
                else:
                    lines.append(
                        f"- `{path}`（kind: {kind}）——主树不存在，疑似声明笔误" f"{note}。"
                    )
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

    def _task_progress_contract_section(self, spec_name: str) -> str:
        """任务进度契约段（fix-impl-tasks-completion-gate D5/6.3）。

        full 与 fast-track 两个 implementer 分支共用同一文本（同源生成，内容
        逐字一致）。契约载体：

        - **必选（无条件生效）**：``.fenix-run-result.json`` 顶层 MUST 携带
          ``completed_tasks`` 数组（已完成任务的 tasks.md id），可选 ``unfinished``
          数组（未完成 id）；清单与 tasks.md 勾选状态一一对应（每个 ``- [x]``
          数字任务在 completed_tasks 恰出现一次，每个 ``- [ ]`` 数字任务在
          partial 收工时于 unfinished 恰出现一次）。禁止把多条任务归并、禁止把
          分组标题当任务登记。
        - **任务粒度映射（无条件生效）**：每条任务一个 TaskCreate、subject 以
          ``Task <tasks.md id>: <标题>`` 开头、完成瞬间对同一 taskId 发
          ``TaskUpdate status=completed`` 不得攒批。

        工具可用性**恒为可用**——不再按历史 run 的 ``init.tools`` 探测。
        根因（2026-09-17 定案）：``_run_claude`` 已无条件注入
        ``CLAUDE_CODE_ENABLE_TODO_TOOLS=1``（见 runner.py，工具族恒可用），
        而旧探测读的是**派发前最新一个历史 run**——新 run 的 ``init`` 事件要等
        run 启动后才产生，故新 spec（无历史 run）/ 修复轮（历史 run 是修复前跑的）
        必然误判「工具不可用」→ 注入禁止段 → agent 不用工具 → 下一轮更读不到
        工具，自我延续（fix-impl-resultfile-contract-gap 事故实证：init.tools
        26 个含 TaskCreate，转录里 TaskCreate 调用 0 次）。工具可用性是派发路由
        的**静态属性**，与 runner 的单点注入对齐，不再靠历史 run 猜。

        ``spec_name`` 保留在签名中（两处调用点仍按位置传参）——契约段内容
        已与 spec 无关，留着以备将来需要按 spec 差异化时不再改调用点。
        """
        task_lines = (
            f'- 每一条 tasks.md 任务（如 "1.3 配置解析签名缓存"）只能由一个 '
            f'TaskCreate 对应，TaskCreate 的 subject MUST 以 "Task <id>: '
            f'<标题>" 开头，id **逐字照抄 tasks.md 的"分组号.任务号"**（含'
            f'小写字母后缀，如 "Task 1.2b: ..."、"Task 4.6b: ..."；后缀'
            f"不是笔误），禁止把多条任务归并为一条 TaskCreate，也禁止把分组"
            f"（## 标题）当任务创建。\n"
            f"- 开始实现某任务时创建其 TaskCreate；该任务完成的瞬间立刻对同一"
            f"taskId 发 TaskUpdate status=completed，不得攒批到收尾。TaskUpdate "
            f"的 taskId 取 TaskCreate 结果返回的任务编号（1 基创建序，形如 "
            f'"Task #1 created"）。\n'
        )
        return (
            f"\n## 任务进度契约（task-progress-contract，强制，fix-impl-tasks-completion-gate）\n"
            f'- 每条 tasks.md 任务（如 "1.3 配置解析签名缓存"）完成时逐项把 '
            f"`- [ ]` 改为 `- [x]`；收尾时逐项勾选所有已完成任务。\n"
            f"- .fenix-run-result.json 顶层 MUST 携带 `completed_tasks` 数组（已完成"
            f'任务的 tasks.md id，如 ["1.1", "2.3"]，**含字母后缀的 id 逐字照抄**'
            f'如 ["1.2b", "4.6b"]），与 tasks.md 勾选状态一一'
            f"对应——每个 `- [x]` 数字任务在 completed_tasks 中恰出现一次；做不完时"
            f'MUST 以 `status: "partial"` 收工并如实登记 `unfinished` 数组（未完成'
            f"任务 id，每个 `- [ ]` 数字任务恰出现一次），MUST NOT 用 success 掩盖"
            f"未完成项，禁止「先勾后做」。禁止把多条任务归并为一个条目，禁止把分组"
            f"（## 标题）当任务登记。\n"
            f"- **诚实退出（unattainable）**：若某未完成任务客观上无法由你完成（例如"
            f"人工运维门控——需用户亲手重启 daemon、需人工审批、需外部资源），"
            f"MUST 在 .fenix-run-result.json 顶层增设 `unattainable` 数组诚实申报，"
            f"**不得**为过门而把它勾成完成（禁止先勾后做）："
            f"`\"unattainable\": [{{\"task\": \"7.3\", \"reason\": \"<为何 agent 无法完成>\", "
            f"\"evidence\": \"<依据>\"}}]`。申报后以 `status: \"partial\"` 收工——门禁会"
            f"从缺口里扣除已申报任务并放行，且**不会**因此判失败重派"
            f"（人工无法代做的任务重派再多轮也是同一终局）；未申报的未完成任务"
            f"仍按缺口拦截。申报 id MUST 确有未勾任务与之对应（伪造豁免会被判失败）。"
            f"**unattainable 以外的缺失申报会被拒回**，故若确有此类任务，收工前"
            f"务必确认它已进入 unattainable 数组（不得改勾选、不得写 success）。\n"
            f"{task_lines}"
            f"- 收尾时逐项 Edit tasks.md，把每条已完成任务 `- [ ]` 改为 `- [x]`，"
            f"与 completed_tasks 清单一一对应，不留半勾。\n"
            f"\n## 有界全量套件入口（fix-run-hang-amplification 3.3，强制）\n"
            f"全量回归由验证链执行，run 内**默认不跑**（add-impl-selfcheck-model-probe "
            f"3.1：仅当确认框架侧回归产物不可用时才在 run 内执行并落盘）。一旦在 "
            f"run 内执行，全量回归（``pytest tests/ -q``）**必须**通过 "
            f"``python3 bin/run_full_suite.py --timeout 3600`` 执行，"
            f"MUST NOT 裸调 ``pytest`` 无限等待。"
            f"有界入口以硬超时运行套件并启用 faulthandler，挂起时中止并输出挂起测试标识"
            f"（栈顶用例）；超时/挂起时的失败可按 ``--baseline <ref>`` 归类存量/引入"
            f"（见设计文档）。裸调 ``pytest`` 无限等待在存量挂起时可烧穿全部预算（14.5h 事故实证）。\n"
        )

    def _designed_ids_line(self, scenarios_path) -> str:
        """当前设计集场景 ID 清单行（硬校验比对基准的 prompt 侧可见性）。"""
        designed_ids: list = []
        try:
            if scenarios_path.exists():
                data = json.loads(scenarios_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    designed_ids = [
                        str(s.get("id"))
                        for s in data
                        if isinstance(s, dict) and s.get("id") is not None
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
        # _str_field 归一：键缺失、显式 None 或结构化值都安全（None 切片 [:2000] 抛
        # TypeError——历史修复防回归）。
        merge_error = _str_field(conflict_summary.get("merge_error")) or "（未提供原始错误）"
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
                f"\n## 冲突文件清单\n" f"请自行通过 `git status --porcelain` 检查当前冲突文件。\n"
            )

        prompt = (
            f"You are the Fenix Repair Agent. You are in repair round {repair_round} "
            f"for the SPEC at {spec_dir}/.\n\n"
            f"## 身份与目标\n"
            f"你正在修复 SPEC `{spec_name}` 的 merge-back 冲突。上一次 merge main 分支到实现"
            f"分支时失败。你的任务是在当前实现分支一侧，把 main 合进分支、解决所有语义冲突"
            f"并提交——提交是本轮 repair 的强制终点，先于测试；测试仅用于提交后的定向回归"
            f"验证。\n\n"
            f"## 原始 merge 错误\n"
            f"```\n{merge_error[:2000]}\n```\n"
            f"{conflict_section}"
            f"## 修复方向（MUST 按顺序执行）\n"
            f"1. 开场清理残留 merge：检测当前 worktree 是否残留上一轮未完成 merge——"
            f"`git rev-parse -q --verify MERGE_HEAD`；若存在（上一轮 merge 未收尾），"
            f"先 `git merge --abort` 复位到干净 tip，禁止把上一轮半成品现场当作本轮起点\n"
            f"2. 检查当前状态：`git status --porcelain` 和 `git log --oneline -3`\n"
            f"3. 把 main 合进当前分支：`git merge main`（此时会遇到冲突）\n"
            f"4. 解决冲突：对每个冲突文件，读取两边版本，保留正确的实现内容\n"
            f"5. **提交冲突解决（强制终点，先于测试）**：\n"
            f'   `git commit -m "[fenix] {spec_name}: resolve merge conflicts"`\n'
            f"   提交是本轮 repair 的强制终点，必须在运行任何测试之前完成；禁止"
            f"「跑完测试再决定是否提交」，禁止因测试未跑完而不提交\n"
            f"6. 定向回归（提交之后）：对本次合并触及文件的定向回归 + 有界超时，例如\n"
            f"   `timeout 600 python3 -m pytest <touched_test_files> -q`\n"
            f"   不要以全量套件作为提交前置；无法在窗口内跑完测试时，提交已解决的合并"
            f"并在 .fenix-run-result.json 的 summary 中如实标注未跑完的验证边界\n\n"
            f"## 完成后\n"
            f"成功：写 .fenix-run-result.json:\n"
            f'{{"status": "success", "spec": "{spec_name}", '
            f'"summary": "<简述解决的冲突；若测试未跑完，如实标注未验证的边界>"}}\n\n'
            f"失败：如果无法解决冲突，写 .fenix-run-result.json:\n"
            f'{{"status": "error", "spec": "{spec_name}", '
            f'"error": "<说明为何无法解决>"}}\n\n'
            f"重要限制：\n"
            f"- 不要修改任务书（tasks.md）中的勾选状态\n"
            f"- 不要重新实现功能，只解决 merge 冲突\n"
            f"- 提交先于测试且为强制终点：测试无法在窗口内跑完时，MUST 提交已解决的"
            f"合并并以 summary 标注未跑完的验证边界，禁止因测试未完而不提交\n"
            f"- 无法解决时必须显式报告失败（写 .fenix-run-result.json error status），"
            f"框架会据此回退到 fallback 重派\n"
            f"IMPORTANT: Do NOT modify STATE.md."
        )
        # 非交互契约段（fix-agent-noninteractive-contract D2）：独立构建路径
        # 不走统一收尾处注入，就地追加（return 之前）。
        prompt += self._noninteractive_contract_section()
        return prompt

    def _build_self_review_prompt(self, token: str, detail: dict) -> str:
        """构建每日自省 prompt（add-daily-self-review design D2/D3）。

        首参 token 即统一入口 _build_prompt 的 spec_name 槽位（按位置传入）；
        self-review 车道无 spec 维度，复用该槽位传入自省归属日期字符串。
        加载 agents/self-review.md（文件化体系，缺失 fail-fast），经
        _single_pass_replace 单趟填充占位符（不用 str.format——正文含大量
        {} JSON 示例）：
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
        # 单趟填充（code-review item 7975ab14dbe7 同款语义）：daily_summary/
        # todo_md 等注入值来自用户数据/LLM 产物，可能本身含占位符字面量，
        # 逐键 str.replace 会被后续键二次替换污染。
        # 注入值统一经 _str_field 归一（与 _fill_placeholders 同口径，归一
        # 不对称防回归）：结构化值序列化为 JSON 串，非字符串直达 re.sub 的
        # 替换回调会抛 TypeError 中断整条 self-review run 的提示词构建；
        # None/缺失归一为空串后仍落到原默认占位提示，正常字符串值原样通过。
        # out_path 兜底不参与读侧契约：生产链路 run_self_review 恒传由 run_id
        # 派生的 out_path（读侧只读该路径），本兜底仅测试/异常构建路径触达。
        # token 是自省归属日期而非 run_id，仅日期命名同日多 run 仍互覆——加
        # 秒级时间戳把碰撞窗口缩到同秒（前缀形态对齐 REVIEW_OUT_PREFIX）。
        out_path = detail.get("out_path") or (
            self._pm.project_root
            / ".fenix"
            / f"self_review_out-{token}-{datetime.datetime.now():%Y%m%d%H%M%S}.json"
        )
        prompt = _fill_and_scan_placeholders(
            template,
            {
                "{review_date}": token,
                "{daily_summary}": _str_field(detail.get("daily_summary"))
                or "（无数据）",
                "{todo_md_content}": _str_field(detail.get("todo_md"))
                or "（read_todo 关闭或 todo.md 不存在，不注入）",
                "{todo_entries}": _str_field(detail.get("todo_entries"))
                or "（近3日窗口内无既有条目）",
                "{out_path}": str(out_path),
            },
            "self-review",
            token,
        )
        # 非交互契约段（fix-agent-noninteractive-contract D2）：独立构建路径
        # 不走统一收尾处注入，就地追加（return 之前）。
        prompt += self._noninteractive_contract_section()
        return prompt

    def _build_evolution_prompt(self, spec_name: str, detail: dict) -> str:
        """构建框架自进化分析 run 的 prompt（add-framework-self-evolution D6）。

        加载 agents/evolution.md（文件化体系，缺失 fail-fast），经
        _single_pass_replace 单趟填充占位符（不用 str.format——正文含大量
        {} JSON 示例）：
        - {run_id}: run 标识（首参 spec_name 槽位传入 run_evolution 生成的
          真实 run_id，契约 run_id 字段照抄该值——与 code-review 车道
          2026-09-24 事故后口径一致，标识符禁由 LLM 自行推导）
        - {todo_sections}: 就绪项目清单，每项目含项目名、项目根与 todo.md 全文
        - {pending_entries}: 待分析条目清单（含 id、日期节、小节、标题）
        - {out_path}: 契约产物路径（.fenix/evolution/out-<run_id>.json）
        - {project_root}: 框架主树（项目根）
        """
        template = self._load_agent_template("evolution")
        projects: list = detail.get("ready_projects") or []
        pending: list = detail.get("pending_entries") or []

        secs = []
        for proj in projects:
            if not isinstance(proj, dict):
                continue
            name = proj.get("name") or "?"
            root = proj.get("path") or self._pm.project_root
            todo = proj.get("todo_md") or "（无 todo.md 内容）"
            secs.append(f"### 项目：{name}（项目根：{root}）\n" f"```\n{todo}\n```\n")
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
            # 兜底不参与读侧契约（生产链路 run_evolution 恒传 out-<run_id>.json，
            # 读侧只读该路径）：固定 out.json 多 run 必互覆——加秒级时间戳把
            # 碰撞窗口缩到同秒。
            out_path = (
                self._pm.project_root
                / ".fenix"
                / "evolution"
                / f"out-{datetime.datetime.now():%Y%m%d%H%M%S}.json"
            )
        # 单趟填充（code-review item 7975ab14dbe7 同款语义）：todo.md 全文/
        # 条目清单来自用户数据，可能本身含占位符字面量，逐键 str.replace
        # 会被后续键二次替换污染。
        prompt = _fill_and_scan_placeholders(
            template,
            {
                # {run_id} 注入（code-review 车道 2026-09-24 事故后同款口径）：
                # 首参 spec_name 槽位即 run_evolution 生成的真实 run_id，契约
                # run_id 字段照抄注入值。此前模板示例是字面 {epoch} 且无任何
                # 填充点，每次派发触发模板漂移 WARNING 并让 LLM 自行推导。
                "{run_id}": str(spec_name),
                "{todo_sections}": todo_sections,
                "{pending_entries}": entries_txt,
                "{out_path}": str(out_path),
                "{project_root}": str(self._pm.project_root),
            },
            "evolution",
            spec_name,
        )
        # 非交互契约段（fix-agent-noninteractive-contract D2）：独立构建路径
        # 不走统一收尾处注入，就地追加（return 之前）。
        prompt += self._noninteractive_contract_section()
        return prompt

    def _build_code_review_prompt(self, token: str, detail: dict) -> str:
        """构建 code-review（周期/手动代码审查）run 的 prompt。

        首参 token 即统一入口 _build_prompt 的 spec_name 槽位（按位置传入）；
        code-review 车道无 spec 维度，复用该槽位传入 run 标识（run_id）。
        加载 agents/code-review.md（文件化体系，缺失 fail-fast），经
        _single_pass_replace 单趟填充占位符（不用 str.format——正文含大量
        {} JSON 示例）：
        - {run_id}: run 标识（分片名 out-{run_id}-b<N>.jsonl 的注入源，2026-09-24
          事故根治：禁止 agent 自行推导分片名）
        - {manifest}: 待审文件清单（框架侧先行算出，进度 total 权威来源）
        - {total_files}: manifest 长度（agent 据此核对是否覆盖完全）
        - {review_window}: 审查窗口描述（scheduled/manual_window 为
          [window_start, now]，manual_full 为全仓）
        - {out_path}: 逐文件增量落盘路径（.fenix/code-review/out-<run_id>.jsonl）
        - {repo_concurrency}: 全仓审查并发（verify.repo_code_review_concurrency，
          缺省 4）——子代理并行扇出上限（波内并行）与 ``ocr scan --concurrency``
          双通道共用同键（add-code-review-concurrency-and-429-resilience）
        """
        template = self._load_agent_template("code-review")
        files: list = detail.get("manifest") or []
        total = len(files)
        manifest_txt = "\n".join(f"- {f}" for f in files) or "（manifest 为空——本 run 不应派发，见调用方）"
        window = detail.get("review_window") or "（全仓）"
        # 全仓审查并发注入（add-code-review-concurrency-and-429-resilience）：
        # detail 缺失/脏值时回退读取器缺省 4，与 get_repo_code_review_concurrency
        # 单点缺省一致。
        from core.config import ConfigLoader

        repo_concurrency = detail.get("repo_concurrency")
        if (
            not isinstance(repo_concurrency, int)
            or isinstance(repo_concurrency, bool)
            or repo_concurrency <= 0
        ):
            repo_concurrency = ConfigLoader.get_repo_code_review_concurrency(
                getattr(self._pm, "config", {}) or {}
            )
        out_path = detail.get("out_path")
        if not out_path:
            out_path = self._pm.project_root / ".fenix" / "code-review" / f"out-{token}.jsonl"
        # 单趟填充（code-review item 7975ab14dbe7 同款语义）：manifest 文件清单
        # 来自仓库实际路径，可能本身含占位符字面量，逐键 str.replace 会被后续键
        # 二次替换污染。
        # {run_id} 分片名注入（2026-09-24 事故根治）：分片名 out-{run_id}-b<N>.jsonl
        # 由框架填具体值，提示词不再让 agent 从 {out_path} 推导——LLM 做字符串
        # 推导曾把 run_id 截成纯 epoch，6 个分片读侧全盲。
        values = {
            "{run_id}": str(token),
            "{manifest}": manifest_txt,
            "{total_files}": str(total),
            "{review_window}": str(window),
            "{repo_concurrency}": str(repo_concurrency),
            "{out_path}": str(out_path),
        }
        # 填充 + 残留占位符扫描告警走共用收尾（code-review item ebd39ad068f3）；
        # 日志参数用 token（本函数无 run_id 名，误引用曾致 NameError 使派发失败）。
        prompt = _fill_and_scan_placeholders(template, values, "code-review", str(token))
        # 非交互契约段（fix-agent-noninteractive-contract D2）：独立构建路径
        # 不走统一收尾处注入，就地追加（return 之前）。
        prompt += self._noninteractive_contract_section()
        return prompt

    def _build_code_fix_prompt(self, run_id: str, detail: dict) -> str:
        """构建 code-fix（自动修复车道）run 的 prompt。

        加载 agents/code-fix.md（文件化体系，缺失 fail-fast），经
        _single_pass_replace 单趟填充占位符（不用 str.format——正文含大量
        {} JSON 示例）：
        - {items}: 本批条目 JSON（按 ``_CODE_FIX_ITEM_FIELDS`` 白名单序列化——
          台账原始行的框架字段（project/review_id/review_kind/reviewed_at/
          spec/status/spec_name/fingerprint 等）不注入 prompt，缺省值字段
          同样剔除；多行缩进渲染）
        - {out_path}: 逐条增量落盘路径（缺省 worktree 内
          .fenix/code-review/fix-out-<run_id>.jsonl）
        - {worktree}: 本批 worktree 根路径（agent 工作目录）
        """
        template = self._load_agent_template("code-fix")
        items: list = detail.get("items") or []
        slim_items = [
            {k: it[k] for k in _CODE_FIX_ITEM_FIELDS if it.get(k) is not None}
            for it in items if isinstance(it, dict)
        ]
        # json.dumps 对空列表即返回 "[]"，无需兜底（code-review e6a36e939590）
        items_txt = json.dumps(slim_items, ensure_ascii=False, indent=2)
        out_path = detail.get("out_path")
        if not out_path:
            wt = detail.get("worktree") or self._pm.project_root
            out_path = Path(wt) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
        worktree = detail.get("worktree") or self._pm.project_root
        # 批内波次上限自适应（add-codefix-affinity-batching 2.2）：按本批
        # items 的文件组数 G 分档（≤4→4；5–8→6；≥9→8），经 {wave_cap} 注入
        # 模板。懒加载规避装载环（code_fix 属编排侧，不反向依赖本模块——同
        # code_fix.py:241 先例）。模板缺占位符时旧文案「固定上限 4」原样保留
        # （回退缺省 4 的旧模板兼容，无需注入侧分支）。
        try:
            from core.code_fix import wave_cap_for_groups

            group_files = {
                str(it.get("file") or "")
                for it in items
                if isinstance(it, dict) and it.get("file")
            }
            wave_cap = wave_cap_for_groups(len(group_files))
        except Exception:  # noqa: BLE001 — 分档失败回退缺省下限（fail-open）
            wave_cap = 4
        # 单趟填充（code-review item 7975ab14dbe7 同款语义）：条目 JSON 来自
        # LLM 审查产物，description/evidence 可能含占位符字面量，逐键
        # str.replace 会被后续键二次替换污染。
        prompt = _fill_and_scan_placeholders(
            template,
            {
                "{items}": items_txt,
                "{out_path}": str(out_path),
                "{worktree}": str(worktree),
                "{wave_cap}": str(wave_cap),
            },
            "code-fix",
            run_id,
        )
        # 回归失败重试轮注入（task 5.6）：上一轮全量回归的失败用例摘要——
        # 令 agent 优先修复其上轮修复引入的回归，再继续处置清单剩余条目。
        failure_summary = detail.get("failure_summary")
        if failure_summary:
            prompt += (
                "\n\n## 上一轮回归失败用例（重试轮注入）\n\n"
                "上一轮全量回归未通过（你的修复可能引入了回归）。请**优先**修复"
                "下列失败用例对应的回归，再继续处置清单中的剩余条目：\n\n"
                f"{failure_summary}\n"
            )
        # 非交互契约段（fix-agent-noninteractive-contract D2）：独立构建路径
        # 不走统一收尾处注入，就地追加（return 之前）。
        prompt += self._noninteractive_contract_section()
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

    def _recovery_resume_note(self, spec_name: str, require_recovery: bool = False) -> str:
        """恢复续做说明：中断恢复保留分支的 resume 派发时注入（interrupt-recovery-preserve）。

        dispatch 层在保留分支的 worktree 内续做（``mark_reused`` 登记继承痕迹，
        prompt 构建据此注入）。语义与 worktree-reuse 继承一致：延续已有成果、
        从 tasks.md 第一个未勾选项继续，不重做、不回滚。未登记复用痕迹时返回空串
        （prompt 与现状逐字节一致）。

        Args:
            require_recovery: 为真时，除 ``get_reuse_record`` 非空外还 MUST 要求
                该记录携带恢复来源标记（``rec.get("recovery")``），否则返回空串。
                缺省 False 时行为与文案逐字节不变——implementer 分支既有调用
                （不传该形参）与 fast-track 分支（``require_recovery=True`` 择一
                注入，见 3.1）共用同一函数。

        判定源说明（fix-fasttrack-recovery-resume 3.4）：
        ① 本函数与 ``_fast_track_reuse_note`` 共享同一 ``_active_reuse`` 判定源
        （``wm.get_reuse_record``），fast-track 分支以 ``require_recovery=True``
        择一注入（恢复续做注记优先，未命中退回 Worktree 继承注记）；
        ② ``_active_reuse`` 亦由 ``_take_reusable_worktree`` / 跨 attempt 复用
        （``runner.py`` 补记）写入，故 ``require_recovery`` 判据不可省略——否则
        普通打回重派轮会被注入「曾因 daemon 重启被中断」的错误归因文案。
        """
        wm = getattr(self._pm, "worktree_manager", None)
        if wm is None or not hasattr(wm, "get_reuse_record"):
            return ""
        rec = wm.get_reuse_record(spec_name)
        if not rec:
            return ""
        if require_recovery and not rec.get("recovery"):
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
                [
                    "git",
                    "-C",
                    str(self._pm.project_root),
                    "log",
                    "--oneline",
                    "-10",
                    f"main..{branch}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
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
                capture_output=True,
                text=True,
                timeout=10,
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
                load_scenario_set,
                is_repair_round,
                read_verify_fix_section,
                declares_new_delivery,
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
            '（如 "covers": ["card-link"]）。',
            "- 无法生成交互场景的元素（纯展示），在任一场景对象上用 "
            '``declared_display`` 登记（如 "declared_display": ["btn-x"]）。',
            "- 契约校验器会确定性 diff 候选集与场景集：既无覆盖又无声明的元素会"
            "导致场景验收失败并退回重排（含链接样式卡片——v2-overview-page 事故的"
            "复发点）。",
            "",
        ]
        return "\n".join(lines)

    def _scenario_schema_section(self) -> str:
        """断言/操作必填字段 schema 注入段（evo-planner-scenario-schema-alignment 2.1）。

        三条会重写 ``test_scenarios.json`` 断言/操作结构的 agent 分支共用：
        planner-plan（出题）、fast-track（PHASE 2 自行写入场景集）、planner-judge
        （原地修复协议直接改写步骤与断言）。**administrator 修复通道不注入**——
        其约束段（``_admin_scenario_fix_constraints``）已机械告知「写回必过
        validate_scenario_dicts 门 + 按框架回传的逐条错误清单重修」，走
        「门 + 错误清单」自纠闭环而非生成侧盲写（2.4 边界，显式保持）。

        内容由 ``core/verify_engine/scenarios.py`` 的 ASSERTION_REQUIRED_FIELDS /
        ACTION_REQUIRED_FIELDS 单源表运行时渲染（每类型必填字段说明 + 合法 JSON
        样例）——与写端校验天然同源，改单源表即在此处生效，MUST NOT 手改任何
        prompt 文件（4.1/4.4 一致性回归锁定：改常量 → 注入文本随之变化）。
        """
        from core.verify_engine.scenarios import (
            ASSERTION_REQUIRED_FIELDS,
            ACTION_REQUIRED_FIELDS,
            CLI_ASSERTIONS,
            API_ASSERTIONS,
        )

        lines = [
            "",
            "## 场景断言/操作必填字段（schema 单源，运行时渲染，强制）",
            "",
            "以下必填字段规则由 `core/verify_engine/scenarios.py` 的单源表"
            "（ASSERTION_REQUIRED_FIELDS / ACTION_REQUIRED_FIELDS）运行时渲染，"
            "与写端结构校验（validate_scenario_dicts）天然同源——缺必填字段的"
            "断言/操作会被写端校验剔除并触发退回重排（2026-09-13 两批 100% 剔除"
            "事故根因：生成侧只列类型名、未说明必填字段）。生成或修复场景时"
            "MUST 按下列字段填写完整，MUST NOT 仅写断言/操作类型名。",
            "",
            "### cli 断言必填字段",
            "",
        ]
        for atype in sorted(CLI_ASSERTIONS):
            lines.append(self._render_schema_type_line(atype, ASSERTION_REQUIRED_FIELDS, "type"))
        lines += ["", "### api 断言必填字段", ""]
        for atype in sorted(API_ASSERTIONS):
            lines.append(self._render_schema_type_line(atype, ASSERTION_REQUIRED_FIELDS, "type"))
        lines += ["", "### 操作必填字段（cli/api）", ""]
        for (kind, action), _specs in sorted(ACTION_REQUIRED_FIELDS.items()):
            lines.append(
                self._render_schema_type_line(action, {action: _specs}, "action", kind=kind)
            )
        lines.append("")
        return "\n".join(lines)

    def _render_schema_type_line(
        self, name: str, table: dict, type_key: str, kind: str = ""
    ) -> str:
        """渲染单源表条目为 prompt 行：必填字段说明 + 合法 JSON 样例。

        ``type_key``：样例的首键名（断言为 ``"type"``、操作为 ``"action"``）。
        样例的 JSON 形态 = 字段键放顶层（extra 键在 dict 形态即为顶层键，
        Assertion.from_dict 将其吸收进 extra）——样例即合法可复制结构。
        """
        specs = table.get(name) or ()
        field_bits = []
        for spec in specs:
            short = spec.get("short") or spec.get("key", "?")
            if spec.get("help"):
                field_bits.append(f"`{short}`（{spec['help']}）")
            else:
                field_bits.append(f"`{short}`")
        head = f"- `{name}`"
        if kind:
            head += f"（kind: {kind}）"
        if not specs:
            return f"{head}：无必填字段"
        sample_parts = [f'{{"{type_key}": "{name}"']
        for spec in specs:
            key = (spec.get("key") or "").replace("extra.", "")
            sample_parts.append(f', "{key}": {spec.get("example", "...")}')
        sample_parts.append("}")
        return f"{head}：必填 {'、'.join(field_bits)}。" f"样例：`{''.join(sample_parts)}`"

    def _triage_recheck_section(self, spec_name: str) -> str:
        """构建优先复核注入段（add-verdict-evidence-taxonomy D5）。

        读取 pm_engine 落盘的 ``.fenix/verify-progress/<spec>/triage_recheck.json``
        （连续 2 轮 warning 的场景清单），注入 planner prompt 的「优先复核」清单，
        与 scenario-freeze 的基准集注入同一接入点（纯本地确定性读取，不触发 LLM）。
        文件缺失 / 为空 → 返回空串（不约束）。
        """
        recheck_path = (
            self._pm.project_root / ".fenix" / "verify-progress" / spec_name / "triage_recheck.json"
        )
        if not recheck_path.exists():
            return ""
        try:
            data = json.loads(recheck_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
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
            "classification=product-bug 并 failed）还是确属 flaky/env（可维持 warning）。\n"
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
            self._pm.project_root
            / ".fenix"
            / "verify-progress"
            / spec_name
            / "verdict_violations.json"
        )
        if not rejection_path.exists():
            return ""
        try:
            data = json.loads(rejection_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
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
                lines.append(f"  - 批量归因查重违规（场景：{sids}）：{v.get('reason')}\n")
            else:
                lines.append(
                    f"  - 场景 `{v.get('scenario_id')}`（status={v.get('status')}）："
                    f"{v.get('reason')}\n"
                )
                # 步骤失败型场景（verdict-step-failure-evidence-derivation）：
                # 框架已由失败信号派生缺省 failed_assertions 清单，逐条抄入
                # evidence.failed_assertions 并给出对应 assertion_triage 即可通过
                # 覆盖校验——重试轮直接拿到应申报条目，不再撞空表死循环。
                derived = v.get("derived_failed_assertions")
                if isinstance(derived, list) and derived:
                    lines.append(
                        "    - 应申报条目（框架派生缺省清单，步骤失败型场景必填）："
                        "逐条抄入 evidence.failed_assertions，并逐条给出对应 "
                        "assertion_triage 归因：\n"
                    )
                    for d in derived:
                        if isinstance(d, dict):
                            lines.append(
                                "      - " + json.dumps(d, ensure_ascii=False) + "\n"
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
            self._pm.project_root
            / ".fenix"
            / "verify-progress"
            / spec_name
            / "dedup_resynthesis_directive.json"
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
            self._pm.project_root
            / ".fenix"
            / "verify-progress"
            / spec_name
            / "requeue_manifest.json"
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

    def _result_gate_section(self, spec_name: str, agent_type: str = "planner-judge",
                             wt_path: Path | None = None) -> str:
        """产物硬门契约注入段（add-judge-artifact-gate D2）。

        告知 planner-judge/planner-plan：run 成功判定 = 进程正常退出 **且** 结果
        文件落盘且为可解析非空 JSON；收工不写/写空/非法 JSON → 判失败并自动原地
        退避重试（不进裁决重试预算）。路径经 planner_result_path 与 runner 硬门
        同源计算。纯静态文本，零 IO、零状态条件。

        spec-review（2026-09-15 事故修复）：评审车道此前没有本段，模型把结果
        JSON 当正文 fenced 代码块吐出、end_turn 自然收工，结果文件从未落盘。
        评审段额外强调「正文里的 JSON 不算交付，框架只读文件」并把路径经
        spec_review_result_path 同源计算。

        implementer / fast-track（fix-impl-resultfile-contract-gap D1/D2）：实现者
        车道此前也没有本段——plan/评审补充后仍漏实现者两分支，2026-09-16 起
        implementer 收工硬门（_check_impl_result_artifact，fail-closed）一直拦截，
        但提示词从未告知「不写=判失败」，模型把结果文件当最后一件家务、优先跑
        全量套件/核实交付物，验证中自然 end_turn → 文件从未落盘 → 整轮白烧重派
        （7 次实证，合计 $97.86）。本段按 agent_type 分派路径并补齐实现者特有
        要素：先落盘再深入（绑定到全量套件**之前**）、无后台节拍声明。
        """
        if agent_type == "spec-review":
            result_path = spec_review_result_path(self._pm.project_root, spec_name)
            return (
                "\n\n## 结果文件硬门（强制）\n"
                "- 框架对本次评审的成功判定 = 进程正常退出 **且** 结果文件已落盘"
                "且为可解析的非空 JSON。\n"
                f"  - 评审结果文件（**唯一交付落点**）：{result_path}\n"
                "- **只把 JSON 写在回复正文里不算交付**：框架不解析正文，只读文件。"
                "正文里的 JSON 会被当作「结果文件缺失」→ 本次评审判**失败**并整轮"
                "重派（浪费一轮 token）。\n"
                "- MUST 用 Write 工具写入上方路径；收工前未写 / 文件为空 / 非法 "
                "JSON → 判**失败**并原地重试（fail-closed）。\n"
                "- 结果文件 MUST 为合法 JSON——字符串内换行/引号/控制字符必须转义。\n"
                "- **先落盘再深入**：先完成最小必要结果落盘，再做深入调查/复现——"
                "深入调查不会为产物缺失兜底。\n"
            )
        if agent_type in ("implementer", "fast-track"):
            if wt_path is not None:
                result_path = str(impl_result_path(wt_path))
            else:
                # wt_path 不可得（测试/异常场景）→ 降级相对路径表述（D1），不崩溃。
                result_path = ".fenix-run-result.json（worktree 根目录）"
            text = (
                "\n\n## 结果文件硬门（实现者收工契约，强制）\n"
                "- 框架对本次 run 的成功判定 = 进程正常退出 **且** 结果文件已落盘"
                "且为可解析的非空 JSON。\n"
                f"  - 结果文件（**唯一交付落点**）：{result_path}\n"
                "- **收工前未写 / 文件为空 / 非法 JSON → 本次 run 判失败并原地"
                "退避重试（整轮 token 重烧）**。\n"
                "- **正文里的 JSON 不算交付**：框架不解析正文，只读文件——正文里的"
                "JSON 会被当作「结果文件缺失」→ 本次 run 判**失败**。\n"
                "- **先落盘再深入**：先写一份最小可判的结果文件，再做（降级路径的）"
                "全量套件回归 / 交付物核实等收尾工作——深入调查/验证不会为产物缺失"
                "兜底。\n"
                "- 结果文件 MUST 为合法 JSON——字符串内换行/引号/控制字符必须转义"
                "（建议以 `json.dump` 生成而非手工拼接文本）。\n"
                "- 本车道无定时唤醒节拍：`ScheduleWakeup` 在非交互派发下不产生"
                "唤醒，后台 Bash 任务的**完成通知同样不会送达**（run 结束当前 "
                "turn 即进程终止、后台子进程被杀）——「后台启动 + 等通知」在本"
                "模式下等价于「启动即忘」，MUST NOT 采用。\n"
                "- 长任务（可能超过 600s 工具上限：全量回归/大范围构建/超时探针）"
                "若存在受硬超时约束、必在返回前给出完整结果的有界入口，如 "
                "`python3 bin/run_full_suite.py --timeout 3600`，MUST **前台"
                "直接跑**该入口。仅在确无有界入口时才用**一次** "
                "`run_in_background: true` 启动，且启动后 MUST NOT 收工——必须"
                "显式 `Read` 其输出文件（`output-file` 路径）确认完成或失败。"
                "MUST NOT 用 `sleep` / 周期性 `ps` 空转模拟等待。\n"
            )
            if agent_type == "fast-track":
                # add-fasttrack-verification-write-gate（任务 1.2）：fast-track
                # 专属契约句，与 run 末产物硬门（result_gate._check_impl_result_
                # artifact → parse_fast_track_verification）同一解析口径。MUST
                # 仅在 fast-track 车道拼入——本块被 implementer（full 车道）
                # 共用，无条件注入会给 full 车道强加 fast-track 专属义务。
                text += (
                    "- **fast-track 车道专属**：success 结果文件必须含合法 "
                    "verification 段（scenarios 非空、每条含非空 "
                    "scenario_id/description、status 枚举合法、verdict 属 "
                    "verified/bug-found）——run 末产物硬门按同一解析口径校验，"
                    "缺段/不完整当场拒收并要求原地补写。\n"
                )
            return text
        result_path = planner_result_path(self._pm.project_root, spec_name, "planner-judge")
        scenarios_path = planner_result_path(self._pm.project_root, spec_name, "planner-plan")
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
            self._pm.project_root / ".fenix" / "verify-progress" / spec_name / "report.json"
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
            self._pm.project_root / ".fenix" / "verify-progress" / spec_name / "report.json"
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
            self._pm.project_root
            / ".fenix"
            / "verify-progress"
            / spec_name
            / "scenario_reroute_directive.json"
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
        if not isinstance(counts, dict):
            counts = {}
        failed_ids = data.get("failed_ids") or []
        if not isinstance(failed_ids, list) or not failed_ids:
            return ""
        id_line = "、".join(str(s) for s in failed_ids)
        counts_txt = (
            "、".join(f"{k}={v}" for k, v in counts.items()) if counts else "全 test-defect"
        )
        # 申报落点 = judge 结果文件（与 _result_gate_section 同源计算；
        # code-review item 8fbab623b92d：旧实现字符串缺 f 前缀，占位符
        # 原样吐出，counts_txt/id_line 成死变量且 result_path 不在作用域）
        result_path = planner_result_path(
            self._pm.project_root, spec_name, "planner-judge"
        )
        return (
            f"\n\n## ⚠️ 场景缺陷改道（MANDATORY：按原地修复协议申报 scenario-repaired）\n"
            f"\n"
            f"- 框架已判定：上一轮失败清单全部为**场景文件缺陷**（classification "
            f"分布 {counts_txt}，product-bug=0）——打回 implementer 修场景是错误路由，"
            f"**修场景是你的职责**（与出题同源知识 + 本轮执行证据）。\n"
            f"- **MUST 按文末「原地修复协议」直接修场景文件并在 {result_path} "
            f"申报 ``scenario-repaired``**；禁止申报 ``bug-found``（仅当你在修复过程"
            f"中发现真产品缺陷——选择器/场景与源码对证为产品 bug——才允许改判 "
            f"product-bug 并申报 bug-found）。\n"
            f"- 本上轮清单场景：{id_line}——修复前先核对场景文件现状，确认缺陷"
            f"根因后逐条修复（补自建夹具/seed、修正客观错误步骤与断言、补 "
            f"depends_on 串接）。\n"
            "- **修复已裁决场景（含跨轮写回场景）合法**：受冻结 diff 记账保护，"
            "无理由的移除才会被确定性补齐——有理由的修复/移除不会被回补，"
            "不视为冻结违规。\n"
            "- 修完逐场景以 checkpoint 写回 report.json（test-defect + evidence 写明"
            "「场景文件缺陷：<改了什么、为什么>」），最后申报 scenario-repaired。\n"
        )
