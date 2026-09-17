"""
result_gate.py — 结果数据结构与产物门（refactor-agent-runner-module D2）。

从 runner.py 拆出的四类结果/门面异常与产物门族。纯结构搬移，零行为变化
（spec「拆分零行为变化」）：`AgentRunResult.to_dict()` 输出逐字段不变、
产物门判定语义与失败归因文案不变。

本模块 MUST NOT `import runner`（D2b 规则 1：门面依赖以显式 `runner` 参数注入）。

契约：
- 结果类与异常类与拆分前同一构造签名 / to_dict 输出；
- 产物门函数首参为 `runner`（AgentRunner 实例）——`logger` / `project_root` /
  `_IMPL_RESULT_STATUSES` 等门面依赖经实例访问，实例属性打桩不被绕过
  （D2b 规则 2：runner.py 内部调用点 MUST 保持 `self.<方法名>` 形式，本模块
  内在兄弟函数间也一律经 `runner.<方法名>` 调用）。
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from core.agent_runner.prompt_builder import (
    impl_result_path,
    planner_result_path,
    planner_result_status_whitelist,
    spec_review_result_path,
    spec_review_result_status_whitelist,
)
from core.agent_runner.run_files import append_run_line
from core.run_task_track import (
    find_impl_run_file,
    parse_run_task_done,
    parse_tasks_md,
    parse_unattainable,
)
from core.state_machine import TASK_GATE_REJECTIONS_FIELD

# 任务完成度类硬门失败前缀（2026-09-16 改进②/① 的机械识别标记）。
#
# 与 [terminal-no-commit] / [provider-transient] 同款「错误文本前缀即语义标签」
# 约定：产物从「根本没交产物」的**结构类**失败（文件缺失/为空/非法 JSON/顶层
# 非对象/status 白名单外）与「交了产物但任务清单对不上」的**任务完成度类**失败
# 中区分出后者。两处消费：
# - runner 捕获 AgentArtifactGateError 时：仅 task 类失败参与「只卡第一次」
#   跨轮计数降级（结构类一律照现状硬拦）；
# - 诚实退出（unattainable 申报）只从 task 类缺口里扣除。
TASK_GATE_ERROR_PREFIX = "[task-gate]"

# 任务完成度类产物硬门的跨轮拒绝计数阈值（2026-09-16 改进①「只卡第一次」）。
# 每次以 TASK_GATE_ERROR_PREFIX 开头的原因被拒即累积（跨 dispatch，非仅同
# attempt）；累积到该阈值后，task 类失败降级为 WARNING 放行，避免实现者已
# 诚实说明「确实无法满足」时被同一门无限拒回原地重试。结构类失败（缺文件/
# 非法 JSON 等）不计数、不降级。计数在门禁干净通过时或全新派发时清零。
TASK_GATE_DEGRADE_THRESHOLD = 2

# fix-verdict-read-failclosed D2（新鲜度宽限，秒）：planner 产物硬门 mtime 新鲜度
# 校验的容差。文件系统 mtime 写入存在滞后（tmpfs 实测 ~6ms），紧邻
# attempt_started_at 后写入的高速度假 run 会被严格 mtime 校验误标陈旧。宽限远小于
# 真实轮间间隙（agent 全程分钟级，上一轮残留 mtime 滞差秒以上），真陈旧产物仍被
# 可靠拦截，仅吸收 mtime 时钟滞后。随消费者同迁本模块（D2b 规则 3）。
_ARTIFACT_FRESHNESS_GRACE_SECONDS = 1.0
# add-planready-artifact-gate D2：planner-plan 结果文件 status 合法值收窄至
# 单值 ("plan-ready",)。planner-plan 的唯一合法终态是 plan-ready；
# verified/bug-found/scenario-repaired 是 judge/verifier 词汇，出现即语义错位
# （implementer 残留 "success" 同理）。读侧判定本就是 status != "plan-ready"
# 即降级——硬门与读侧口径完全一致。不复用四值白名单常量 planner_result_status_whitelist，
# 防「judge 合法值替 plan 类型放行」。随消费者同迁本模块（D2b 规则 3）。
_PLANREADY_STATUSES = ("plan-ready",)


class RunCancelledError(Exception):
    """run 被 cancel_run 原语人工取消时抛出。

    不走通用 Exception 处理路径——不重试、不计秒挂、不触发 provider 切换。
    携带 reason（取消原因）与 by（操作人）。
    """

    def __init__(self, reason: str = "", by: str = "admin"):
        self.reason = reason
        self.by = by
        msg = f"run cancelled by {by}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class AgentArtifactGateError(Exception):
    """planner 产物硬门失败（add-judge-artifact-gate D1。

    add-planready-artifact-gate：plan 类型也含结果文件契约——planner-plan
    现亦校验 .fenix-run-result.json（status='plan-ready'）。

    进程 exit 0 但结果文件（judge: .fenix-run-result.json / plan:
    test_scenarios.json + .fenix-run-result.json）缺失、为空、非法 JSON 或
    status 白名单外时抛出——run 按瞬态失败走既有原地退避重试通道，不进入
    validate_report 的「裁决重试一次」预算。
    """

    def __init__(self, message: str = ""):
        self.artifact_error = message
        super().__init__(message)


class AgentRunResult:
    """Result of a single Agent run."""

    def __init__(
        self,
        run_id: str,
        spec_name: str,
        agent_type: str,
        success: bool,
        duration_seconds: float,
        turns_used: int = 0,
        error: str = None,
        output: str = "",
        branch: str | None = None,
        provider_used: str | None = None,
        model_used: str | None = None,
        chain_exhausted: bool = False,
        worktree_dirty: list | None = None,
        worktree_path=None,
        worktree_kept: bool = False,
        cancelled: bool = False,
    ):
        self.run_id = run_id
        self.spec_name = spec_name
        self.agent_type = agent_type
        self.success = success
        self.duration_seconds = duration_seconds
        self.turns_used = turns_used
        self.error = error
        self.output = output
        self.branch = branch  # worktree 分支名（成功时由 _execute_agent 填入）
        # add-provider-failover（design D5 / spec failover-dispatch「切换可观测」）：
        # 本次 run 实际使用的 provider 名与 model 名（链选择/切换后落盘可查）。
        self.provider_used = provider_used
        self.model_used = model_used
        # chain_exhausted：链上全部候选均处于 switch 冷却期，attempt 直接失败返回
        # （不启动进程、不计入 spec 重试消耗；design D3 / spec failover-dispatch）。
        self.chain_exhausted = chain_exhausted
        # fix-zero-change-blindspot：implementer 成功收工时、worktree cleanup **前**
        # 取证的 `git status --porcelain` 非空行清单。零变更哨需要「agent 是否真的
        # 动过文件」的证据；cleanup 后证据即销毁（曾致 Bash 写文件的真实工作被
        # 误判为空转、2.11h/$10 全丢）。None/空 = 无脏文件或非 implementer。
        self.worktree_dirty = worktree_dirty
        # worktree 继承（fast-track 打回重派复用）：worktree_path = 本轮使用的
        # worktree（fast-track 成功路径延迟清理、由 dispatch 层判定后处置）；
        # worktree_kept = runner 终态失败时已保留为复用遗产（dispatch 无需重复保留）。
        self.worktree_path = worktree_path
        self.worktree_kept = worktree_kept
        # run 是否被人工取消（cancel_run 旗标命中导致 RunCancelledError）。
        self.cancelled = cancelled

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "spec_name": self.spec_name,
            "agent_type": self.agent_type,
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "turns_used": self.turns_used,
            "error": self.error,
            "branch": self.branch,
            "provider_used": self.provider_used,
            "model_used": self.model_used,
            "chain_exhausted": self.chain_exhausted,
            "cancelled": self.cancelled,
            "output_summary": self.output[-500:] if self.output else "",
        }


class AdminDisposition:
    """Administrator Agent 一次处置的结果（run_administrator 返回）。"""

    def __init__(
        self,
        run_id: str,
        spec: str | None = None,
        success: bool = True,
        problem: str = "",
        actions_taken: str = "",
        result: str = "",
        escalate: bool = False,
        recommended_action: str = "",
        summary: str = "",
        error: str = "",
        output: str = "",
        family_waiver: bool = False,
        failure_evidence: dict | None = None,
    ):
        self.run_id = run_id
        self.spec = spec
        self.success = success
        self.problem = problem
        self.actions_taken = actions_taken
        self.result = result
        self.escalate = escalate
        self.recommended_action = recommended_action
        self.summary = summary
        self.error = error
        self.output = output
        # family_explosion 处置：Administrator 对该父 SPEC「放行一次」。
        # 由 admin_monitor 落成 _family_waiver=true（单次豁免，用后复位）。
        self.family_waiver = family_waiver
        # orphaned-state-probe-calibration 1.5：非零退出的可定位失败证据
        # （原始 stderr 摘录 / 退出码 / provider·model / 带时间戳事件时间线）。
        # 独立字段，不参与 error 归因文本（error-attribution-denoise D5 语义
        # 不变）；成功或无证据时为空 dict。
        self.failure_evidence = failure_evidence or {}

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "spec": self.spec,
            "success": self.success,
            "problem": self.problem,
            "actions_taken": self.actions_taken,
            "result": self.result,
            "escalate": self.escalate,
            "recommended_action": self.recommended_action,
            "summary": self.summary,
            "error": self.error,
        }


class SelfReviewResult:
    """每日自省 run 的结果（run_self_review 返回，add-daily-self-review）。

    waste/mistakes/improvements 为三个小节条目列表（每条含证据与建议，
    由 Agent 在回顾 JSON 中产出）；resolved 为闭环判定清单（``[{id,
    reason}]``，畸形条目在解析时过滤），调度器据此从 todo.md 移除已闭环
    条目；success=False 时 error 携带失败原因。
    """

    def __init__(
        self,
        run_id: str,
        date: str = "",
        success: bool = True,
        waste: list | None = None,
        mistakes: list | None = None,
        improvements: list | None = None,
        summary: str = "",
        resolved: list | None = None,
        error: str = "",
        output: str = "",
    ):
        self.run_id = run_id
        self.date = date
        self.success = success
        self.waste = list(waste or [])
        self.mistakes = list(mistakes or [])
        self.improvements = list(improvements or [])
        self.summary = summary
        self.resolved = list(resolved or [])
        self.error = error
        self.output = output


class EvolutionResult:
    """框架自进化分析 run 的结果（run_evolution 返回，add-framework-self-evolution）。

    - items_ingested: 成功落地到 items.jsonl 的条目数
    - drafts: 生成草稿（状态 pending）的条目数
    - accepted: 本轮已接受（accepted/auto_accepted）条目数（daemon 检查点自动
      接受后由调用方据实更新；run 本身不执行自动接受——那是 5.3 检查点的职责）
    - degraded: 降级原因（"no-task-tool" 等）；None 表示未降级
    - error: success=False 时的失败原因
    """

    def __init__(
        self,
        run_id: str = "",
        success: bool = True,
        items_ingested: int = 0,
        drafts: int = 0,
        accepted: int = 0,
        degraded: str | None = None,
        error: str = "",
        output: str = "",
    ):
        self.run_id = run_id
        self.success = success
        self.items_ingested = items_ingested
        self.drafts = drafts
        self.accepted = accepted
        self.degraded = degraded
        self.error = error
        self.output = output


# ── 产物门族（add-judge-artifact-gate / add-planready-artifact-gate /
#     fix-verdict-read-failclosed / fix-impl-tasks-completion-gate）──
#
# 门面依赖统一经 `runner` 参数注入（D2b 规则 1）；兄弟函数间调用一律
# `runner.<方法名>`（D2b 规则 2），保证实例属性打桩/运行期替换仍然生效。


def _check_artifact_json_file(
    path: Path, agent_type: str, run_started_at: float | None, is_resumed_worktree: bool = False
) -> tuple:
    """单产物文件基础校验（存在/非空/mtime 新鲜/可解析 JSON）。

    多个产物文件共用同一套基础校验（add-planready-artifact-gate：planner-plan
    双产物叠加校验）。新鲜度守卫（fix-verdict-read-failclosed D2）与既有
    test_scenarios.json 同规则。

    is_resumed_worktree（2026-09-16 事故修正）：本轮 attempt 复用的 worktree
    是否承载**上一轮遗留产物**。复用 worktree 做续做/修复轮时，worktree 内本
    就存在前轮的 ``.fenix-run-result.json``（mtime 早于本轮启动），这是设计
    预期而非异常——此时**跳过 mtime 新鲜度硬拦**，正确性交内容判据保证
    （success 需 completed_tasks 与 tasks.md 全勾一致、partial 需申报一致）。
    仅「新建 worktree 的首轮」做 mtime 硬拦（防上一轮/其它 spec 残留冒充本轮）。

    背景：旧实现对**所有**轮做 mtime 硬拦，导致「已完工 worktree 复用做修复轮」
    秒退死循环——agent 判定「无需动作」不重写结果文件，mtime 停在上一轮，被
    误判陈旧（2026-09-15 refactor-dashboard-data-module / 09-16
    refactor-agent-runner-module 两起实测）。

    Returns:
        (err, data)：err 非 None = 失败归因文案（含具体文件路径与原因类别，
        供 error 直用）；否则 data 为解析出的 JSON 值（可为任意类型）。
    """
    try:
        if not path.is_file():
            return (f"exit 0 但结果文件缺失（{agent_type} 产物硬门）: {path}", None)
        if path.stat().st_size == 0:
            return (f"exit 0 但结果文件为空（{agent_type} 产物硬门）: {path}", None)
        if run_started_at is not None and not is_resumed_worktree:
            mtime = path.stat().st_mtime
            if mtime < run_started_at - _ARTIFACT_FRESHNESS_GRACE_SECONDS:
                return (
                    f"exit 0 但结果文件早于本轮启动（陈旧残留，{agent_type} "
                    f"产物硬门）: {path} (mtime={mtime:.1f} < "
                    f"run_started_at - grace={run_started_at - _ARTIFACT_FRESHNESS_GRACE_SECONDS:.1f})",
                    None,
                )
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        return (f"exit 0 但结果文件不可读（{agent_type} 产物硬门）: {path} ({e})", None)
    except json.JSONDecodeError as e:
        return (f"exit 0 但结果文件非法 JSON（{agent_type} 产物硬门）: {path} ({e})", None)
    return (None, data)


def _check_agent_result_artifact(
    runner,
    spec_name: str,
    agent_type: str,
    run_started_at: float | None = None,
    wt_path: Path | None = None,
    is_resumed_worktree: bool = False,
) -> str | None:
    """planner/implementer 产物存在性硬门（fail-closed）。

    fixtures: 从富集注释迁移时保持与拆分前完全一致的判定语义与失败归因文案。
    `runner` 为 AgentRunner 实例（project_root / 兄弟门函数经实例访问）。

    is_resumed_worktree：见 ``_check_artifact_json_file``——仅 implementer /
    fast-track 分支透传（本轮复用 worktree 承载上一轮遗留产物时跳过 mtime
    新鲜度硬拦）；planner / spec-review 分支不做该豁免。
    """
    if agent_type in ("implementer", "fast-track"):
        return runner._check_impl_result_artifact(
            spec_name, run_started_at, wt_path, is_resumed_worktree=is_resumed_worktree
        )
    if agent_type == "spec-review":
        path = spec_review_result_path(runner.project_root, spec_name)
        err, data = runner._check_artifact_json_file(path, agent_type, run_started_at)
        if err is not None:
            return err
        if not isinstance(data, dict):
            return f"exit 0 但结果文件顶层非对象（{agent_type} 产物硬门）: {path}"
        status = data.get("status", "")
        if status not in spec_review_result_status_whitelist:
            return (
                f"exit 0 但结果文件 status='{status}' 不在白名单"
                f"（{agent_type} 产物硬门）: {path}"
            )
        return None
    if agent_type not in ("planner-judge", "planner-plan"):
        return None
    if agent_type == "planner-plan":
        # 双产物叠加校验：test_scenarios.json（既有，保持不变）+
        # .fenix-run-result.json（add-planready-artifact-gate，新增）。
        scenarios_path = planner_result_path(runner.project_root, spec_name, "planner-plan")
        result_path = planner_result_path(runner.project_root, spec_name, "planner-judge")
        err, _data = runner._check_artifact_json_file(scenarios_path, agent_type, run_started_at)
        if err is not None:
            return err
        err, data = runner._check_artifact_json_file(result_path, agent_type, run_started_at)
        if err is not None:
            return err
        if not isinstance(data, dict):
            return f"exit 0 但结果文件顶层非对象（{agent_type} 产物硬门）: {result_path}"
        status = data.get("status", "")
        if status not in _PLANREADY_STATUSES:
            return (
                f"exit 0 但结果文件 status='{status}' 不在白名单"
                f"（{agent_type} 产物硬门）: {result_path}"
            )
        return None
    path = planner_result_path(runner.project_root, spec_name, agent_type)
    err, data = runner._check_artifact_json_file(path, agent_type, run_started_at)
    if err is not None:
        return err
    # fix-verdict-read-failclosed D3：judge 裁决文件（.fenix-run-result.json）
    # 顶层 status 须在白名单内（语义错位取值如 implementer 共享残留的
    # success 不得流入读侧被「unknown status 视为 verified」）。
    if not isinstance(data, dict):
        return f"exit 0 但结果文件顶层非对象（{agent_type} 产物硬门）: {path}"
    status = data.get("status", "")
    if status not in planner_result_status_whitelist:
        return (
            f"exit 0 但结果文件 status='{status}' 不在白名单" f"（{agent_type} 产物硬门）: {path}"
        )
    return None


def _check_impl_result_artifact(
    runner,
    spec_name: str,
    run_started_at: float | None,
    wt_path: Path | None,
    is_resumed_worktree: bool = False,
) -> str | None:
    """implementer / fast-track 结果产物硬门（fix-impl-tasks-completion-gate P0）。

    `runner` 为 AgentRunner 实例：`_IMPL_RESULT_STATUSES`（类属性）与兄弟门
    函数（_check_artifact_json_file / _check_success_completion /
    _check_partial_consistency / _check_taskupdate_crosscheck）经实例访问，
    保证实例属性打桩不被绕过。

    is_resumed_worktree：本轮复用的 worktree 承载上一轮遗留产物时为 True →
    结果文件跳过 mtime 新鲜度硬拦（见 ``_check_artifact_json_file``）。
    """
    agent_type = "implementer"  # 归因文案类别；fast-track 同判据同文案
    if wt_path is None:
        return (
            f"exit 0 但 worktree 路径不可得（{agent_type} 产物硬门），"
            f"无法定位结果文件: {spec_name}"
        )
    result_path = impl_result_path(wt_path)
    err, data = runner._check_artifact_json_file(
        result_path, agent_type, run_started_at, is_resumed_worktree=is_resumed_worktree
    )
    if err is not None:
        return err
    if not isinstance(data, dict):
        return f"exit 0 但结果文件顶层非对象（{agent_type} 产物硬门）: {result_path}"
    status = data.get("status", "")
    if status not in runner._IMPL_RESULT_STATUSES:
        return (
            f"exit 0 但结果文件 status='{status}' 不在白名单"
            f"（{agent_type} 产物硬门）: {result_path}"
        )
    if status == "error":
        # 2.6：error 不施加任何完成度类判据（agent 自报失败即按失败处理）。
        return None

    # status ∈ {success, partial} → 以 worktree 内 tasks.md 为对象的判据
    tasks_path = wt_path / "spec" / "changes" / spec_name / "tasks.md"
    all_ids, checked_ids = parse_tasks_md(wt_path, spec_name)

    # 诚实退出申报（2026-09-16 改进②）：顶层 unattainable 数组 → 机械豁免清单。
    # 非法项 MUST 判失败（防伪造豁免绕过缺口判据）；合法项从「未完成」义务中扣除。
    unattainable_ids, invalid_unat = parse_unattainable(data)
    if invalid_unat:
        return (
            f"exit 0 但结果文件 unattainable 申报非法"
            f"（每项须为含合法 task id 与非空 reason 的对象，{agent_type} 产物硬门）: "
            f"{result_path} 非法项 {len(invalid_unat)} 个"
        )
    unchecked_ids = {tid for tid in all_ids if tid not in checked_ids}
    bogus = sorted(unattainable_ids - unchecked_ids)
    if bogus:
        return (
            f"exit 0 但结果文件 unattainable 申报了非未完成任务"
            f"（只能申报确实无法完成的未勾任务，{agent_type} 产物硬门）: "
            f"{result_path} {runner._format_gap_list(bogus)}"
        )

    if status == "success":
        # 诚实退出（改进②）：无法完成的已申报任务从「全部任务」基准里扣除，
        # 使「未勾选硬缺口」不含它们，同时 completed_tasks 仍须 == 已勾选集合。
        effective_all = [t for t in all_ids if t not in unattainable_ids]
        gate_err = runner._check_success_completion(
            spec_name, result_path, data, effective_all, checked_ids
        )
    else:
        gate_err = runner._check_partial_consistency(
            spec_name, result_path, data, all_ids, checked_ids,
            unattainable_ids=unattainable_ids,
        )
    if gate_err is None:
        # ── 能力探测（D4）：TaskCreate 可用才强制交叉核对，否则 fail-open + 审计。
        # 已申报 unattainable 的任务不产生 TaskUpdate 覆盖义务（诚实退出，改进②）。
        gate_err = runner._check_taskupdate_crosscheck(
            spec_name, checked_ids - unattainable_ids
        )

    if gate_err is not None and gate_err.startswith(TASK_GATE_ERROR_PREFIX):
        # ── 改进①「只卡第一次」（2026-09-16）：任务完成度类失败跨轮计数，达阈值
        # 降级为 WARNING 放行（返回 None）。避免实现者已诚实说明「确实无法满足」
        # 时被同一门无限拒回原地重试。结构类失败（无此前缀）不计数、不降级。
        if _register_task_gate_rejection(runner, spec_name, gate_err):
            runner.logger.warning(
                "agent_runner",
                f"Artifact gate '{spec_name}' task 类失败已达阈值 —— 降级为警告"
                f"放行（只卡第一次）: {gate_err}",
            )
            return None
        return gate_err

    if gate_err is None:
        # 门禁干净通过 → 清零任务完成度类拒绝计数（防陈旧计数日久误降级）。
        _clear_task_gate_rejections(runner, spec_name)
    return gate_err


# ── 转录末轮 fenced JSON 捞回（fix-impl-resultfile-contract-gap D4）────────────
# 与 runner.py 既有 spec-review 捞回同族：从 .fenix/runs/<run_id>.jsonl 末轮
# assistant text 抽最后一个 fenced JSON，status 在白名单内即代写落盘——把
# 「整轮白烧重试」降为「零成本回收」。泛化为车道无关：路径与白名单按
# agent_type 分派；调用点（runner.py）MUST 在拷回块之前执行。
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)

_salvage_logger = logging.getLogger("fenixd.agent_runner.result_gate")


def salvage_result_from_transcript(
    project_root,
    spec_name: str,
    run_id: str | None,
    agent_type: str,
    wt_path: Path | None = None,
    statuses: tuple | None = None,
) -> bool:
    """车道无关的结果文件捞回（fix-impl-resultfile-contract-gap D4）。

    从 run 转录末轮 assistant text 抽最后一个 fenced JSON；``status`` 在
    ``statuses`` 白名单内即代写落盘到按 ``agent_type`` 分派的目标路径。
    守卫（与 spec-review 既有语义逐字一致）：

    - 目标文件已存在 → 不覆盖，直接返回 False；
    - 抽不出合法 JSON / status 不在白名单 → 不落盘返回 False；
    - 转录缺失/不可读 → 不落盘不抛异常返回 False；
    - 成功落盘 → 写一条含 spec/run_id/status 的 WARNING 日志（不静默）。

    目标路径分派：spec-review → ``.fenix/spec-review/<spec>/.fenix-run-result.json``
    （spec_review_result_path）；implementer / fast-track → ``impl_result_path(wt_path)``
    （wt_path 为 None 时返回 False——测试/异常场景无 worktree 载体）。

    白名单分派：spec-review 用 ``spec_review_result_status_whitelist``
    （本模块已导入，默认值）；implementer/fast-track 的 ``_IMPL_RESULT_STATUSES``
    是 ``AgentRunner`` 类属性，不得导出为模块常量（1.1），MUST 经 ``statuses``
    参数由调用点传入。``statuses is None`` 时降级为该车道白名单或空（fail-closed）。
    """
    if agent_type == "spec-review":
        target = spec_review_result_path(project_root, spec_name)
        whitelist = statuses if statuses is not None else spec_review_result_status_whitelist
    elif agent_type in ("implementer", "fast-track"):
        if wt_path is None:
            return False
        target = impl_result_path(wt_path)
        whitelist = statuses
    else:
        return False
    if whitelist is None:
        whitelist = ()
    if target.exists():
        return False
    if not run_id:
        return False
    run_file = Path(project_root) / ".fenix" / "runs" / f"{run_id}.jsonl"
    last_text = ""
    try:
        with run_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") != "assistant":
                    continue
                for c in (d.get("message") or {}).get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "text":
                        last_text = c.get("text") or ""
    except OSError:
        return False
    if not last_text:
        return False
    matches = _FENCED_JSON_RE.findall(last_text)
    if not matches:
        return False
    payload = None
    for block in reversed(matches):
        try:
            candidate = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("status") in whitelist:
            payload = candidate
            break
    if payload is None:
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        _salvage_logger.warning(
            "结果捞回写盘失败 '%s' (%s): %s", spec_name, agent_type, e)
        return False
    _salvage_logger.warning(
        "%s 结果捞回：run 未写结果文件，已从转录末轮 fenced JSON "
        "代写落盘 '%s' run_id=%s status=%s",
        agent_type, spec_name, run_id, payload.get("status"))
    return True


# ── 结果文件缺失归因（fix-impl-resultfile-contract-gap D5）────────────────────
# 复用既有 _classify_terminal_no_commit 的终态机械特征（<function_calls> /
# markdown fenced Edit|Write|Bash|NotebookEdit / fenced <invoke，正则常量
# _TERMINAL_NO_COMMIT_TOOL_PATTERN），新增一层文案映射：「未提交即收工」→
# 「未收工即停」（MUST NOT 改既有返回值——tests/test_terminal_nocommit_gate.py
# :196/203 断言「未提交即收工」）。落位遵守 D2b 模块契约：门族函数首参为
# runner 实例，MUST NOT import runner。


def classify_terminal_stall(runner, sub_run_id: str) -> str:
    """实现者车道结果文件缺失归因文案（4.1）。

    薄包装：委托既有 ``AgentRunner._classify_terminal_no_commit``（唯一实现，
    旧名保留，MUST NOT 改名破坏既有测试），把其返回文案映射为实现者车道
    语义——「格式回退截断」保持不变；「未提交即收工」映射为「未收工即停」
    （文案 MUST 由映射层产出，MUST NOT 改既有方法返回值）。

    转录缺失/损坏时既有方法降级「未提交即收工」→ 映射后即「未收工即停」。
    归因仅用于日志/告警语义区分，MUST NOT 改变处置路径（重试次数/退避/resume
    不变）。
    """
    raw = runner._classify_terminal_no_commit(sub_run_id)
    if raw == "格式回退截断":
        return "格式回退截断"
    return "未收工即停"


def classify_and_enrich_artifact_error(
    runner, error_text: str, agent_type: str, sub_run_id: str | None,
) -> str:
    """结果文件缺失归因拼接（4.2）。

    当 ``agent_type ∈ {implementer, fast-track}`` 且 ``error`` 文本含
    「结果文件缺失」时，把 ``classify_terminal_stall`` 的归因文案拼进 error
    局部变量（形如「结果文件缺失（未收工即停）」），供日志/告警语义区分。
    MUST NOT 改变处置路径——重试次数、退避序列、resume 决策完全一致。

    **归因文本 MUST 只拼进局部变量 ``error_text``**，MUST NOT 改动传给
    ``record_transient_break`` 的 ``str(e)``——全局瞬断指纹记账读的是
    ``str(e)``（runner.py:2040-2051），把归因文案带进 ``str(e)`` 会污染
    dispatch 闸门对瞬断风暴的可见性。

    ``sub_run_id`` 缺失（测试/异常场景）时不归因，原样返回。
    """
    if agent_type not in ("implementer", "fast-track"):
        return error_text
    if not sub_run_id or "结果文件缺失" not in error_text:
        return error_text
    stall_reason = classify_terminal_stall(runner, sub_run_id)
    return error_text.replace(
        "结果文件缺失", f"结果文件缺失（{stall_reason}）", 1)


def _format_gap_list(gap: list, limit: int = 20) -> str:
    """缺口任务 id 清单格式化（2.7 归因可诊断）：超 limit 项截断并标注总数。"""
    if not gap:
        return ""
    if len(gap) <= limit:
        return "、".join(sorted(gap))
    return "、".join(sorted(gap)[:limit]) + f" 等共 {len(gap)} 项"


def _invalid_completed_ids(items) -> list:
    """completed_tasks / unfinished 中的非法任务 id（形如 x.y 之外的取值）。

    合法性判定与 parse_tasks_md 同源（core.run_task_track.is_task_id）：
    任务 id 语法为 ``<组号>.<任务号>[可选小写字母后缀]``（``1.1`` / ``1.2b``）。
    字母后缀是 planner 产出补充任务时的正常形态，判为非法会让实现者
    如实上报被硬门拒绝（2026-09-15 事故，见 run_task_track 模块 docstring）。
    """
    from core.run_task_track import is_task_id

    bad = []
    for it in items:
        if not is_task_id(it):
            bad.append(it)
    return bad


def _check_success_completion(
    runner, spec_name: str, result_path: Path, data: dict, all_ids: list, checked_ids: set
) -> str | None:
    """status == "success" 的任务书完成度判据（spec「success 的完成度判据」）。

    1. 勾选清零：tasks.md 无未勾数字任务（D2 与 _task_completion_blocker 同源；
       tasks.md 缺失/无数字任务 → 通过）；
    2. 完成清单对账：completed_tasks 集合 == 已勾选集合（缺项/多项/非数字 id
       判失败；无数字任务时以空集为基准，空数组或缺失均视为通过）。

    诚实退出（2026-09-16 改进②）：不可完成任务的扣除在调用方
    ``_check_impl_result_artifact`` 完成——它把已申报 unattainable 的 id 从
    ``all_ids`` 里剔除后传入，故本函数无需感知该字段。
    """
    agent_type = "implementer"
    unchecked = [tid for tid in all_ids if tid not in checked_ids]
    if unchecked:
        return (
            f"{TASK_GATE_ERROR_PREFIX} exit 0 但 tasks.md 尚有未勾选数字任务"
            f"（{agent_type} 产物硬门）: "
            f"{result_path.parent / 'spec' / 'changes' / spec_name / 'tasks.md'} "
            f"缺口: {runner._format_gap_list(unchecked)}"
        )
    raw_ct = data.get("completed_tasks")
    if raw_ct is None:
        if not all_ids:
            return None  # 无数字任务 → 缺失/空数组均视为通过
        return (
            f"{TASK_GATE_ERROR_PREFIX} exit 0 但结果文件缺 completed_tasks 清单"
            f"（{agent_type} 产物硬门）: {result_path}"
        )
    if not isinstance(raw_ct, list):
        return (
            f"{TASK_GATE_ERROR_PREFIX} exit 0 但结果文件 completed_tasks 非数组"
            f"（{agent_type} 产物硬门）: {result_path}"
        )
    bad = runner._invalid_completed_ids(raw_ct)
    if bad:
        return (
            f"{TASK_GATE_ERROR_PREFIX} exit 0 但结果文件 completed_tasks 含非法任务 id"
            f"（{agent_type} 产物硬门）: {result_path} {runner._format_gap_list(bad)}"
        )
    ct_set = set(raw_ct)
    missing = sorted(checked_ids - ct_set)
    extra = sorted(ct_set - checked_ids)
    if missing or extra:
        parts = []
        if missing:
            parts.append("缺项: " + runner._format_gap_list(missing))
        if extra:
            parts.append("多项: " + runner._format_gap_list(extra))
        return (
            f"{TASK_GATE_ERROR_PREFIX} exit 0 但 completed_tasks 与 tasks.md 勾选集合不一致"
            f"（{agent_type} 产物硬门）: {result_path} {'；'.join(parts)}"
        )
    return None


def _check_partial_consistency(
    runner, spec_name: str, result_path: Path, data: dict, all_ids: list, checked_ids: set,
    unattainable_ids: set | None = None,
) -> str | None:
    """status == "partial" 的申报一致性判据（spec「partial 的申报一致性判据」）。

    completed_tasks 集合 == 已勾选集合；unfinished 集合 ⊆ 未勾选集合；且
    「未勾选 − unfinished − unattainable」为空（每个未勾任务都必须被申报为
    unfinished 或 unattainable）；三集合互斥且并集 == 全部数字任务 id。
    任一不满足返回失败归因（防 partial 成为绕过 success 判据的缺口）。

    诚实退出衔接（2026-09-16 改进② 补齐 partial 路径）：``unattainable`` 申报
    的任务**不要求**出现在 unfinished 里——它客观上不可由 agent 完成（如
    「经用户确认时机后重启 daemon」这类人工运维门控），既不能勾选（先勾后做）
    也不该被当作 agent 的未完成缺口。修正前判据把「并集 == 全部数字任务 id」
    无条件成立（completed ∪ unfinished ⊊ all），申报 unattainable 的 partial
    必然被拒（2026-09-16 fix-dashboard-read-path-performance 实测：实现者三个
    原地重试轮如实申报 unattainable=[6.2] 均被同一门拒回，spec 在 implementing
    悬置 43 分钟直至 orphaned_state 唤起 admin）。
    """
    agent_type = "implementer"
    unattainable_ids = set(unattainable_ids or ())
    raw_ct = data.get("completed_tasks")
    raw_un = data.get("unfinished")
    # unattainable 申报在场时 unfinished 可省略（缺口全由 unattainable 承载的
    # 收工形态：申报了「做不了」的任务即无需再列「没做完」）；无申报时维持
    # 原样硬拦（缺数组 = 申报不完整）。
    if raw_un is None and unattainable_ids:
        raw_un = []
    if not isinstance(raw_ct, list) or not isinstance(raw_un, list):
        return (
            f"exit 0 但结果文件 partial 缺 completed_tasks/unfinished 数组"
            f"（{agent_type} 产物硬门）: {result_path}"
        )
    bad = runner._invalid_completed_ids(raw_ct) + runner._invalid_completed_ids(raw_un)
    if bad:
        return (
            f"exit 0 但结果文件 partial 清单含非法任务 id"
            f"（{agent_type} 产物硬门）: {result_path} {runner._format_gap_list(bad)}"
        )
    ct_set, un_set = set(raw_ct), set(raw_un)
    expected_un = set(all_ids) - checked_ids
    # 未勾任务中既未申报 unfinished、又未申报 unattainable 的部分（真缺口）。
    undeclared = expected_un - un_set - unattainable_ids
    missing_ct = sorted(checked_ids - ct_set)
    extra_ct = sorted(ct_set - checked_ids)
    extra_un = sorted(un_set - expected_un)
    overlap = sorted(ct_set & un_set)
    parts = []
    if missing_ct or extra_ct:
        parts.append("completed_tasks 与勾选集合不一致")
    if extra_un:
        parts.append("unfinished 含非未勾任务")
    if undeclared:
        parts.append(
            "未申报缺口（既不在 unfinished 也未在 unattainable）: "
            + runner._format_gap_list(sorted(undeclared))
        )
    if overlap:
        parts.append(f"completed_tasks/unfinished 交集非空: {runner._format_gap_list(overlap)}")
    if (ct_set | un_set | unattainable_ids) != set(all_ids):
        parts.append("并集不等于全部数字任务 id")
    if parts:
        return (
            f"{TASK_GATE_ERROR_PREFIX} exit 0 但结果文件 partial 申报一致性判据未通过"
            f"（{agent_type} 产物硬门）: {result_path} {'；'.join(parts)}。"
            f"提示：客观上无法由 agent 完成的未完成任务（人工运维门控——需用户亲手"
            f'重启 daemon、需人工审批、需外部资源）MUST 用顶层 `unattainable` 数组'
            f'申报诚实退出：`"unattainable": [{{"task": "7.3", "reason": "<为何 '
            f'agent 无法完成>", "evidence": "<依据>"}}]`，MUST NOT 勾选或谎报 success'
        )
    return None


def _check_taskupdate_crosscheck(runner, spec_name: str, checked_ids: set) -> str | None:
    """能力探测（D4）：init.tools 含 TaskCreate 才强制 TaskUpdate 交叉核对。

    读本轮 run 产物（find_impl_run_file 按 mtime 取最新 impl run）中
    ``type == "system" && subtype == "init"`` 事件的 tools 数组：
    - 含 "TaskCreate" → 按**跨轮累积**的 Task 记录核对：读该 spec 全部
      impl run（含 a1/a2/a3 与 -rN 重试），任务 id 取族内全局序，
      ``done_ids`` 为各「已创建且已 completed」id 的并集；
    - 不含 / init 事件不可得 → **跳过**该项核对并放行，同时向 run 产物追加
      ``impl-task-crosscheck-skipped`` 审计事件（含 spec/run_id/reason）。
      无条件强制会让硬门在 Task 家族工具不可用的派发路由上永远无法通过，
      形成「拒绝 → resume → 再拒绝」的预算烧穿循环（141/141 实测）。

    判据（2026-09-15 事故修正，两处）：
    1. **跨轮累积**（而非只读 mtime 最新单 run）：修复/续做轮只改文档、
       不调 TaskCreate，其 ``done_ids`` 为空；只读最新一轮必然误拦。
       ``taskId`` 是会话级全局序，须按「派发 epoch 家族」串起全部 run 再映射
       （见 ``parse_run_task_done_cumulative``）。
    2. **只对 tracked 任务要求覆盖**：要求集 = ``checked_ids ∩ tracked_ids``
       （tracked = 曾出现过 TaskCreate 的 id）。任务在 tasks.md 里被勾选
       不等于实现者建过对应 Task——planner 中途插入、未单独建 Task 的
       任务（如 "1.2b"）不应因缺 TaskUpdate 记录被拦。
    """
    agent_type = "implementer"
    run_file = find_impl_run_file(runner.project_root, spec_name)
    tools = runner._read_init_tools(run_file)
    if tools is None or "TaskCreate" not in tools:
        reason = "init 事件不可得" if tools is None else "init.tools 不含 TaskCreate"
        runner._append_crosscheck_skipped(spec_name, run_file, reason)
        return None
    if not checked_ids:
        return None  # 无已勾选任务 → 无覆盖义务
    from core.run_task_track import parse_run_task_done_cumulative

    rd = parse_run_task_done_cumulative(runner.project_root, spec_name)
    done_ids = set(rd.get("done_ids") or ())
    tracked_ids = set(rd.get("tracked_ids") or ())
    # 只对「实现者确实声明过（建过 Task）」的任务要求完成覆盖（调用方已把
    # 已申报 unattainable 的 id 从 checked_ids 扣除）。
    requirement = set(checked_ids) & tracked_ids
    missing = sorted(requirement - done_ids)
    if missing:
        return (
            f"{TASK_GATE_ERROR_PREFIX} exit 0 但已完成任务与 TaskUpdate 记录不一致"
            f"（{agent_type} 产物硬门）: "
            f"done_ids 未覆盖已勾选任务 {runner._format_gap_list(missing)}"
        )
    return None


def _read_init_tools(run_file) -> list | None:
    """读 run 产物 init 事件的 tools 数组（D4 能力探测）。

    fix-impl-tasks-completion-gate：实现下沉至中性模块 core.run_task_track
    （与 prompt_builder 契约段条件生成共用同一实现，避免两份漂移）。

    Returns:
        tools 列表（可为空）；run 文件缺失 / 不可读 / 无 init 事件 /
        tools 非数组 → None（按「工具不可用」处理，fail-open）。
    """
    from core.run_task_track import read_init_tools as _read_tools

    return _read_tools(run_file)


def _append_crosscheck_skipped(runner, spec_name: str, run_file, reason: str) -> None:
    """向 run 产物追加 impl-task-crosscheck-skipped 审计事件（D4 fail-open 留痕）。

    写失败仅记 warning（审计是附加物，不阻塞主流程）。
    """
    if run_file is None:
        return
    try:
        append_run_line(
            run_file,
            {
                "type": "impl-task-crosscheck-skipped",
                "spec": spec_name,
                "run_id": Path(run_file).stem,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
    except OSError as e:
        runner.logger.warning(
            "agent_runner",
            f"impl-task-crosscheck-skipped 审计事件写入失败"
            f"（非阻塞）: {e}",
        )

def _bump_task_gate_rejections(runner, spec_name: str, delta: int = 1) -> int:
    """任务完成度类产物硬门拒绝计数原子增减（改进①「只卡第一次」）。

    state_machine 缺失/异常 fail-open（返回 0 → 调用方视为首次，维持硬拦；
    判定故障不放大为「静默放行」）。
    """
    try:
        if runner.state_machine is None:
            return 0
        return runner.state_machine.bump_task_gate_rejections(spec_name, delta)
    except Exception as e:
        runner.logger.warning(
            "agent_runner",
            f"task-gate 拒绝计数更新失败 '{spec_name}'（fail-open）: {e}",
        )
        return 0


def _alert_task_gate_degraded(runner, spec_name: str, rejections: int,
                              error: str) -> None:
    """task 类产物硬门降级放行时发人工告警（改进①，去重节流）。

    与 _alert_transient_break 同构：AdminStore.latest_signal 按 (spec, signal_type)
    窗口内查重。告警写失败仅记 debug 不阻断。
    """
    try:
        from core.admin_store import AdminStore, ESCALATION
        store = AdminStore(runner.project_root, runner.logger)
        if store.latest_signal(
                spec_name, "artifact_gate_task_degraded", 30) is not None:
            return
        store.append({
            "kind": ESCALATION,
            "signal_type": "artifact_gate_task_degraded",
            "spec": spec_name,
            "severity": "warning",
            "description": (
                f"任务完成度类产物硬门连续 {rejections} 次拒绝后已降级放行——"
                f"可能存在实现者确实无法完成的任务，或门禁判据与实际不符"
            ),
            "evidence": f"rejections={rejections}; last_error={error[:300]}",
            "recommended_action": (
                "检查 tasks.md 未勾任务是否为人工运维门控（如重启/审批），"
                "必要时在结果文件用 unattainable 申报诚实退出；"
                "或核对门禁判据是否误拦正当收工"
            ),
        })
    except Exception as e:
        runner.logger.debug(
            "agent_runner", f"task-gate 降级告警写入失败（不阻断）: {e}")


def _register_task_gate_rejection(runner, spec_name: str, error: str) -> bool:
    """登记一次 task 类拒绝并判定是否降级放行（改进①「只卡第一次」）。

    返回 True = 已达阈值，调用方放行（不再原地重试）；False = 未达阈值，
    照常退避重试。仅对 [task-gate] 前缀的失败计数（结构类失败不参与）。
    """
    rej = _bump_task_gate_rejections(runner, spec_name, 1)
    if rej >= TASK_GATE_DEGRADE_THRESHOLD:
        _alert_task_gate_degraded(runner, spec_name, rej, error)
        return True
    return False


def _clear_task_gate_rejections(runner, spec_name: str) -> None:
    """门禁干净通过时清零 task-gate 拒绝计数（改进①，防陈旧计数误降级）。"""
    if runner.state_machine is None:
        return
    try:
        entry = runner.state_machine.read_one(spec_name) or {}
        if int(entry.get(TASK_GATE_REJECTIONS_FIELD, 0) or 0) > 0:
            runner.state_machine.update_spec(
                spec_name, {TASK_GATE_REJECTIONS_FIELD: 0})
    except Exception:
        pass
