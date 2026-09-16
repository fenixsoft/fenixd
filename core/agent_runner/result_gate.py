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
from datetime import datetime, timezone
from pathlib import Path

from core.agent_runner.prompt_builder import (
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
)

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

    def __init__(self, run_id: str, spec_name: str, agent_type: str,
                 success: bool, duration_seconds: float,
                 turns_used: int = 0, error: str = None, output: str = "",
                 branch: str | None = None,
                 provider_used: str | None = None, model_used: str | None = None,
                 chain_exhausted: bool = False,
                 worktree_dirty: list | None = None,
                 worktree_path=None, worktree_kept: bool = False,
                 cancelled: bool = False):
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

    def __init__(self, run_id: str, spec: str | None = None, success: bool = True,
                 problem: str = "", actions_taken: str = "", result: str = "",
                 escalate: bool = False, recommended_action: str = "",
                 summary: str = "", error: str = "", output: str = "",
                 family_waiver: bool = False):
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

    def __init__(self, run_id: str, date: str = "", success: bool = True,
                 waste: list | None = None, mistakes: list | None = None,
                 improvements: list | None = None, summary: str = "",
                 resolved: list | None = None,
                 error: str = "", output: str = ""):
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

    def __init__(self, run_id: str = "", success: bool = True,
                 items_ingested: int = 0, drafts: int = 0,
                 accepted: int = 0, degraded: str | None = None,
                 error: str = "", output: str = ""):
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


def _check_artifact_json_file(path: Path, agent_type: str,
                              run_started_at: float | None,
                              is_resumed_worktree: bool = False) -> tuple:
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


def _check_agent_result_artifact(runner, spec_name: str,
                                 agent_type: str,
                                 run_started_at: float | None = None,
                                 wt_path: Path | None = None,
                                 is_resumed_worktree: bool = False) -> str | None:
    """planner/implementer 产物存在性硬门（fail-closed）。

    fixtures: 从富集注释迁移时保持与拆分前完全一致的判定语义与失败归因文案。
    `runner` 为 AgentRunner 实例（project_root / 兄弟门函数经实例访问）。

    is_resumed_worktree：见 ``_check_artifact_json_file``——仅 implementer /
    fast-track 分支透传（本轮复用 worktree 承载上一轮遗留产物时跳过 mtime
    新鲜度硬拦）；planner / spec-review 分支不做该豁免。
    """
    if agent_type in ("implementer", "fast-track"):
        return runner._check_impl_result_artifact(
            spec_name, run_started_at, wt_path,
            is_resumed_worktree=is_resumed_worktree)
    if agent_type == "spec-review":
        path = spec_review_result_path(runner.project_root, spec_name)
        err, data = runner._check_artifact_json_file(
            path, agent_type, run_started_at)
        if err is not None:
            return err
        if not isinstance(data, dict):
            return (
                f"exit 0 但结果文件顶层非对象（{agent_type} 产物硬门）: {path}"
            )
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
        scenarios_path = planner_result_path(
            runner.project_root, spec_name, "planner-plan")
        result_path = planner_result_path(
            runner.project_root, spec_name, "planner-judge")
        err, _data = runner._check_artifact_json_file(
            scenarios_path, agent_type, run_started_at)
        if err is not None:
            return err
        err, data = runner._check_artifact_json_file(
            result_path, agent_type, run_started_at)
        if err is not None:
            return err
        if not isinstance(data, dict):
            return (
                f"exit 0 但结果文件顶层非对象（{agent_type} 产物硬门）: {result_path}"
            )
        status = data.get("status", "")
        if status not in _PLANREADY_STATUSES:
            return (
                f"exit 0 但结果文件 status='{status}' 不在白名单"
                f"（{agent_type} 产物硬门）: {result_path}"
            )
        return None
    path = planner_result_path(runner.project_root, spec_name, agent_type)
    err, data = runner._check_artifact_json_file(
        path, agent_type, run_started_at)
    if err is not None:
        return err
    # fix-verdict-read-failclosed D3：judge 裁决文件（.fenix-run-result.json）
    # 顶层 status 须在白名单内（语义错位取值如 implementer 共享残留的
    # success 不得流入读侧被「unknown status 视为 verified」）。
    if not isinstance(data, dict):
        return (
            f"exit 0 但结果文件顶层非对象（{agent_type} 产物硬门）: {path}"
        )
    status = data.get("status", "")
    if status not in planner_result_status_whitelist:
        return (
            f"exit 0 但结果文件 status='{status}' 不在白名单"
            f"（{agent_type} 产物硬门）: {path}"
        )
    return None


def _check_impl_result_artifact(runner, spec_name: str,
                                run_started_at: float | None,
                                wt_path: Path | None,
                                is_resumed_worktree: bool = False) -> str | None:
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
    result_path = wt_path / ".fenix-run-result.json"
    err, data = runner._check_artifact_json_file(
        result_path, agent_type, run_started_at,
        is_resumed_worktree=is_resumed_worktree)
    if err is not None:
        return err
    if not isinstance(data, dict):
        return (
            f"exit 0 但结果文件顶层非对象（{agent_type} 产物硬门）: {result_path}"
        )
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
    if status == "success":
        gate_err = runner._check_success_completion(
            spec_name, result_path, data, all_ids, checked_ids)
    else:
        gate_err = runner._check_partial_consistency(
            spec_name, result_path, data, all_ids, checked_ids)
    if gate_err is not None:
        return gate_err

    # ── 能力探测（D4）：TaskCreate 可用才强制交叉核对，否则 fail-open + 审计 ──
    return runner._check_taskupdate_crosscheck(spec_name, checked_ids)


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


def _check_success_completion(runner, spec_name: str, result_path: Path,
                              data: dict, all_ids: list,
                              checked_ids: set) -> str | None:
    """status == "success" 的任务书完成度判据（spec「success 的完成度判据」）。

    1. 勾选清零：tasks.md 无未勾数字任务（D2 与 _task_completion_blocker 同源；
       tasks.md 缺失/无数字任务 → 通过）；
    2. 完成清单对账：completed_tasks 集合 == 已勾选集合（缺项/多项/非数字 id
       判失败；无数字任务时以空集为基准，空数组或缺失均视为通过）。
    """
    agent_type = "implementer"
    unchecked = [tid for tid in all_ids if tid not in checked_ids]
    if unchecked:
        return (
            f"exit 0 但 tasks.md 尚有未勾选数字任务（{agent_type} 产物硬门）: "
            f"{result_path.parent / 'spec' / 'changes' / spec_name / 'tasks.md'} "
            f"缺口: {runner._format_gap_list(unchecked)}"
        )
    raw_ct = data.get("completed_tasks")
    if raw_ct is None:
        if not all_ids:
            return None  # 无数字任务 → 缺失/空数组均视为通过
        return (
            f"exit 0 但结果文件缺 completed_tasks 清单（{agent_type} 产物硬门）: "
            f"{result_path}"
        )
    if not isinstance(raw_ct, list):
        return (
            f"exit 0 但结果文件 completed_tasks 非数组（{agent_type} 产物硬门）: "
            f"{result_path}"
        )
    bad = runner._invalid_completed_ids(raw_ct)
    if bad:
        return (
            f"exit 0 但结果文件 completed_tasks 含非法任务 id"
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
            f"exit 0 但 completed_tasks 与 tasks.md 勾选集合不一致"
            f"（{agent_type} 产物硬门）: {result_path} {'；'.join(parts)}"
        )
    return None


def _check_partial_consistency(runner, spec_name: str, result_path: Path,
                               data: dict, all_ids: list,
                               checked_ids: set) -> str | None:
    """status == "partial" 的申报一致性判据（spec「partial 的申报一致性判据」）。

    completed_tasks 集合 == 已勾选集合；unfinished 集合 == 未勾选集合；两集合
    互斥且并集 == 全部数字任务 id。任一不满足返回失败归因（防 partial 成为
    绕过 success 判据的缺口）。
    """
    agent_type = "implementer"
    raw_ct = data.get("completed_tasks")
    raw_un = data.get("unfinished")
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
    missing_ct = sorted(checked_ids - ct_set)
    extra_ct = sorted(ct_set - checked_ids)
    missing_un = sorted(expected_un - un_set)
    extra_un = sorted(un_set - expected_un)
    overlap = sorted(ct_set & un_set)
    parts = []
    if missing_ct or extra_ct:
        parts.append("completed_tasks 与勾选集合不一致")
    if missing_un or extra_un:
        parts.append("unfinished 与未勾选集合不一致")
    if overlap:
        parts.append(f"completed_tasks/unfinished 交集非空: {runner._format_gap_list(overlap)}")
    if (ct_set | un_set) != set(all_ids):
        parts.append("并集不等于全部数字任务 id")
    if parts:
        return (
            f"exit 0 但结果文件 partial 申报一致性判据未通过"
            f"（{agent_type} 产物硬门）: {result_path} {'；'.join(parts)}"
        )
    return None


def _check_taskupdate_crosscheck(runner, spec_name: str,
                                 checked_ids: set) -> str | None:
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
    # 只对「实现者确实声明过（建过 Task）」的任务要求完成覆盖
    requirement = set(checked_ids) & tracked_ids
    missing = sorted(requirement - done_ids)
    if missing:
        return (
            f"exit 0 但已完成任务与 TaskUpdate 记录不一致（{agent_type} 产物硬门）: "
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


def _append_crosscheck_skipped(runner, spec_name: str, run_file,
                               reason: str) -> None:
    """向 run 产物追加 impl-task-crosscheck-skipped 审计事件（D4 fail-open 留痕）。

    写失败仅记 warning（审计是附加物，不阻塞主流程）。
    """
    if run_file is None:
        return
    try:
        append_run_line(run_file, {
            "type": "impl-task-crosscheck-skipped",
            "spec": spec_name,
            "run_id": Path(run_file).stem,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except OSError as e:
        runner.logger.warning(
            "agent_runner",
            f"impl-task-crosscheck-skipped 审计事件写入失败"
            f"（非阻塞）: {e}",
        )