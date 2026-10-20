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
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core.agent_runner.prompt_builder import (
    ACCEPTANCE_DEVIATION_ANNOTATION,
    ACCEPTANCE_DEVIATION_TYPE,
    impl_result_path,
    IMPL_FINDINGS_TYPE_WHITELIST,
    planner_result_path,
    PLANNER_RESULT_STATUS_WHITELIST,
    spec_review_result_path,
    SPEC_REVIEW_RESULT_STATUS_WHITELIST,
)
from core.agent_runner.run_files import append_run_line
from core.fast_track_result import parse_fast_track_verification
from core.run_task_track import (
    find_impl_run_file,
    is_task_id,
    parse_tasks_md,
    parse_unattainable,
    tasks_md_path,
)

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
# 即降级——硬门与读侧口径完全一致。不复用四值白名单常量 PLANNER_RESULT_STATUS_WHITELIST，
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


class FrozenTerminatedError(Exception):
    """run 因其所属 SPEC 被冻结而终止时抛出。

    与 RunCancelledError 并列（add-freeze-stop-inflight-agents D2）：取消是
    run 级人工动作（写 _cancelled_hold），冻结终止是 spec 级停止（写
    _frozen_hold）——两者语义不同、互不读写，MUST NOT 复用取消通道。
    不走通用 Exception 处理路径——不重试、不计秒挂、不触发 provider 切换。
    携带 reason（冻结来源）与 by（冻结操作方）。
    """

    def __init__(self, reason: str = "", by: str = "admin"):
        self.reason = reason
        self.by = by
        msg = f"run frozen-terminated by {by}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class AgentArtifactGateError(Exception):
    """planner 产物硬门失败（add-judge-artifact-gate D1）。

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
        frozen_terminated: bool = False,
        api_error_status=None,
        conn_error=None,
        stderr_tail=None,
        exit_code=None,
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
        # add-freeze-stop-inflight-agents D1：run 是否因 spec 冻结被终止
        # （FrozenTerminatedError → 独立 frozen-terminated 终态；与 cancelled
        # 并列、互不读写——dispatch 侧据此写 _frozen_hold 而非 _cancelled_hold）。
        self.frozen_terminated = frozen_terminated
        # evo-fix-spec-review-infra-attribution-bridge 1.1：单轮 API 错误的结构化
        # 归因（对齐 exc.api_error_status / exc.conn_error 挂载先例 runner.py）。
        # 异常上挂的归因经 run 车道 catch-all 回填（spec_review 车道 1.2），随
        # 结果对象传递到失败分类层——失败分类优先消费结构化字段，不再依赖经
        # _denoise_stderr 降噪后的 stderr 文本（降噪后只剩 "Exit code: 1"，
        # 文本分类恒 False）。缺省 None：既有构造点不传即兼容。
        self.api_error_status = api_error_status
        self.conn_error = conn_error
        # evo-add-review-failure-attribution 1.2：失败行归因括注素材（形态对齐
        # api_error_status 的桥接回填先例）。stderr_tail = 异常原始 stderr_lines
        # 的尾行摘要（maintenance_runs._stderr_tail_summary 单源，追溯用非判别
        # 用）；exit_code = 进程退出码。二者随 spec-review 车道 catch-all 回填，
        # 供失败 ERROR 行就地归因；evo-add-verifier-infra-death-triage 1.2 起
        # verifier 车道（主车道 _execute_agent_inner catch-all → _exhausted_result
        # 终态透传）同样回填，供 infra 死亡分流台账辅助标注与排障追溯；
        # 缺省 None：既有构造点不传即兼容。
        self.stderr_tail = stderr_tail
        self.exit_code = exit_code

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
            "frozen_terminated": self.frozen_terminated,
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
        choice_id: str = "",
        suggested_choice: str = "",
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
        # add-human-adjudication-choices 4.2：处置结论的结构化裁决表达——
        # choice_id 非空时框架按注册表 action 执行（与人工 alert-resolve 同一
        # 执行路径）；suggested_choice 为注册表未覆盖处置的建议新增选项 id。
        # 可选键缺省空串，既有处置记录（无这两个键）完全兼容。
        self.choice_id = choice_id or ""
        self.suggested_choice = suggested_choice or ""

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
            "choice_id": self.choice_id,
            "suggested_choice": self.suggested_choice,
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


class CodeReviewResult:
    """周期性代码审查 run 的结果（run_code_review 返回，add-code-review-agent-and-quality-tab）。

    - inserted/updated: 落账到 items.jsonl 的条目数（inserted=新插入，
      updated=重复观测刷新）
    - resolved: 全仓快照核销的条目数（仅 manual_full 收尾核销非 0）
    - error: success=False 时的失败原因
    """

    def __init__(
        self,
        run_id: str = "",
        success: bool = True,
        inserted: int = 0,
        updated: int = 0,
        resolved: int = 0,
        error: str = "",
        output: str = "",
        shards: int = 0,
    ):
        self.run_id = run_id
        self.success = success
        self.inserted = inserted
        self.updated = updated
        self.resolved = resolved
        self.error = error
        self.output = output
        # 本 run 被消费的分片数（add-code-review-sharded-out 2.3：完成日志
        # 补 shards=N 便于取证——分片直写模式下「零台账增长」归因时先看
        # 是零分片还是分片零行）
        self.shards = shards
        # 429 限流重派意图（add-code-review-concurrency-and-429-resilience D4）：
        # 终态归因为 429 限流时由 runner._ratelimit_redispatch_on_terminal 登记
        # （dict：reason/provider/run_id/cooldown_until/cooldown_until_epoch/
        # max_redispatches），随结果信封上交消费侧（admin_monitor._worker）
        # 冷却到期后延迟重投递；非 429 失败/成功路径恒 None（消费侧零感知）。
        self.ratelimit_redispatch = None


class RegressionResult:
    """全量回归 run 的结果（run_regression 返回，add-test-regression-tab）。

    与 CodeReviewResult 同形态：维护型 run 的结果信封。run_regression
    不经 LLM——直接执行 regression.cmd 并解析 JUnit XML（core/regression.py），
    故本类只承载信封字段：status 沿用快照状态（passed/failed/timeout/
    parse_error/skipped），snapshot 为完整快照（含计数/耗时/failures/
    long_tests，design D6）。
    """

    def __init__(
        self,
        run_id: str = "",
        success: bool = True,
        status: str = "",
        error: str = "",
        snapshot: dict = None,
        output: str = "",
    ):
        self.run_id = run_id
        self.success = success
        self.status = status
        self.error = error
        self.snapshot = snapshot or {}
        self.output = output


class CodeFixResult:
    """code-fix run 的结果信封（run_code_fix 返回，add-code-review-auto-fix）。

    与 CodeReviewResult / RegressionResult 同形态的维护型 run 结果：
    - ``fixed`` / ``skipped``: out 产物行中 status=fixed / skipped 的计数
      （skipped 条目 MUST 保持 open——由编排器在合回成功后只核销 fixed）；
    - ``error``: success=False 时的失败原因（含产物硬门拦截文案）；
    - 结构化失败签名（evo-code-fix-api-timeout-salvage 1.2）：``api_timeout``
      （单轮 API 请求超时终局，判别单源在 runner 层挂异常标记）、
      ``exit_code`` / ``stderr_summary``（原始退出码与 stderr 尾行摘要）——
      失败现场可判别、可追溯，不再把签名压扁为异常字符串；
    - ``conn_error`` / ``result_text``（evo-add-codefix-conn-error-cooldown
      1.3）：连接类 api_error 布尔（判别单源在 runner 层挂异常标记，三判据
      见 provider_circuit.is_code_fix_conn_error）与末次 result 事件文本原样
      透传——conn_error 驱动车道冷却，result_text 供告警 evidence 与单测。
      与 api_timeout 的分工（design D2）：api_timeout 保持「现场抢救」触发
      语义不变，conn_error 只驱动冷却、不参与 salvage 判定；两布尔可同时为
      真（api_error 是 api_timeout 的宽判分支），互不掣肘。

    与同族维护型 run 结果信封同址本模块（code-review item 08e3c8a68262）；
    原定义于 maintenance_runs.py，该模块改为导入本类，既有
    ``from core.agent_runner.maintenance_runs import CodeFixResult`` 路径
    保持可用。
    """

    def __init__(
        self,
        run_id: str = "",
        success: bool = True,
        fixed: int = 0,
        skipped: int = 0,
        error: str = "",
        output: str = "",
        api_timeout: bool = False,
        exit_code=None,
        stderr_summary: str = "",
        conn_error: bool = False,
        result_text: str = "",
    ):
        self.run_id = run_id
        self.success = success
        self.fixed = fixed
        self.skipped = skipped
        self.error = error
        self.output = output
        self.api_timeout = api_timeout
        self.exit_code = exit_code
        self.stderr_summary = stderr_summary
        self.conn_error = conn_error
        self.result_text = result_text


# ── 产物门族（add-judge-artifact-gate / add-planready-artifact-gate /
#     fix-verdict-read-failclosed / fix-impl-tasks-completion-gate）──
#
# 门面依赖统一经 `runner` 参数注入（D2b 规则 1）；兄弟函数间调用一律
# `runner.<方法名>`（D2b 规则 2），保证实例属性打桩/运行期替换仍然生效。

# ── 归因类别共享常量（code-review item b02fb265b7e5）────────────────────
# _check_artifact_json_file 的失败归因文案被本模块两处消费方按子串判定类别：
# _check_impl_code_review_artifact 区分「文件缺失」与其他校验失败（探测竞态
# 下的缺失 err 不得记进 first_err），classify_and_enrich_artifact_error 判定
# 是否拼接终态归因；「陈旧」文案则承载 fix-impl-code-review-gate-readback 的
# spec 契约（主树残留终态 MUST 指明陈旧）。此前文案与两处判定各写一份字面
# 量，任一侧措辞调整即静默失效且无类型层保护；现文案统一由常量插值生成、
# 消费方按同一常量判定，字面值保持既有契约（含下游测试断言）不变。
_ARTIFACT_ERR_MISSING = "结果文件缺失"
_ARTIFACT_ERR_STALE = "陈旧"


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
            return (f"exit 0 但{_ARTIFACT_ERR_MISSING}（{agent_type} 产物硬门）: {path}", None)
        if path.stat().st_size == 0:
            return (f"exit 0 但结果文件为空（{agent_type} 产物硬门）: {path}", None)
        if run_started_at is not None and not is_resumed_worktree:
            mtime = path.stat().st_mtime
            if mtime < run_started_at - _ARTIFACT_FRESHNESS_GRACE_SECONDS:
                return (
                    f"exit 0 但结果文件早于本轮启动（{_ARTIFACT_ERR_STALE}残留，{agent_type} "
                    f"产物硬门）: {path} (mtime={mtime:.1f} < "
                    f"run_started_at - grace={run_started_at - _ARTIFACT_FRESHNESS_GRACE_SECONDS:.1f})",
                    None,
                )
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        return (f"exit 0 但结果文件不可读（{agent_type} 产物硬门）: {path} ({e})", None)
    except (json.JSONDecodeError, RecursionError) as e:
        # 超深嵌套 JSON 会让 json.loads 抛 RecursionError（非 JSONDecodeError
        # 子类，不接住会逸出硬门、被 runner 通用异常通道按未归因失败处理）——
        # 与非法 JSON 同口径 fail-closed（MUST NOT 以未捕获异常崩溃硬门本身）。
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
        if status not in SPEC_REVIEW_RESULT_STATUS_WHITELIST:
            return (
                f"exit 0 但结果文件 status='{status}' 不在白名单"
                f"（{agent_type} 产物硬门）: {path}"
            )
        return None
    if agent_type not in ("planner-judge", "planner-plan"):
        # 兜底分支本就放行（verifier / self-review 等无结果文件契约的车道合法
        # 落此），但「门静默消失」须可观测：车道新增/拼错 agent_type（如
        # implementor）时此处零校验零留痕即失去全部产物硬门。记 WARNING 留痕
        # （返回语义不变），与 _check_impl_code_review_artifact 门开关读取
        # 失败留痕的既有取向对齐。
        runner.logger.warning(
            "agent_runner",
            f"产物硬门未识别 agent_type='{agent_type}'（按无门放行，留痕）"
            f": spec={spec_name}",
        )
        return None
    if agent_type == "planner-plan":
        # 双产物叠加校验：test_scenarios.json（既有，保持不变）+
        # .fenix-run-result.json（add-planready-artifact-gate，新增）。
        scenarios_path = planner_result_path(runner.project_root, spec_name, "planner-plan")
        # planner-judge 标签 = 共享 .fenix-run-result.json 路径；planner-plan 标签
        # 返回的是场景集 test_scenarios.json 路径，故此处借 planner-judge 取本车道
        # 的结果文件路径做叠加校验（勿改成 planner-plan——那会拿场景集当结果文件）。
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
    if status not in PLANNER_RESULT_STATUS_WHITELIST:
        return (
            f"exit 0 但结果文件 status='{status}' 不在白名单" f"（{agent_type} 产物硬门）: {path}"
        )
    return None


# disposition 合法值白名单（add-impl-selfcheck-model-probe 1.1 提为模块常量）：
# 校验体与自检 CLI 的 prompt 注入（正反例措辞）共用同一来源，禁止第二份同义词表。
DISPOSITION_WHITELIST = ("fixed", "rejected", "deferred")

# code_review 处置段键名别名清单（evo-spec-concurrency-flight-guard 容错键名）：
# 硬门（_validate_code_review_report）与自检（_selfcheck_dispositions_violations）
# 共用同一来源，新增别名只改此处即双侧同源生效，禁止各写一份字面量元组。
_DISPOSITION_KEY_ALIASES = ("dispositions", "findings_summary")


def _validate_disposition_entries(cr_dispositions, report_rel: str) -> str | None:
    """逐条 disposition 条目校验体（add-impl-selfcheck-model-probe 1.1 抽取）。

    自 ``_validate_code_review_report`` 的条目循环原样抽出（判定语义零变化），
    供两处共用同一函数对象：①收尾审查报告硬门（daemon 侧 ocr join）；
    ②实现者收工自检 CLI（结果文件自带 code_review 段时的条目形状自证）。
    前置条件：``cr_dispositions`` 已为 list 且长度与 findings 对齐（调用方保证）。

    逐条判据：条目须为对象（含 ``disposition`` 键）→ disposition 在
    DISPOSITION_WHITELIST → rejected/deferred 须附非空 ``reason``。
    """
    for idx, disp in enumerate(cr_dispositions):
        if not isinstance(disp, dict):
            return (
                f"exit 0 但 code_review.dispositions[{idx}] 非对象"
                f"（impl-code-review-gate）: {report_rel}"
            )
        d = disp.get("disposition", "")
        if d not in DISPOSITION_WHITELIST:
            return (
                f"exit 0 但 code_review.dispositions[{idx}].disposition='{d}' 不在"
                f"白名单（合法值为 fixed/rejected/deferred）（impl-code-review-gate）: "
                f"{report_rel}"
            )
        if d in ("rejected", "deferred"):
            r = disp.get("reason", "")
            if not isinstance(r, str) or not r.strip():
                return (
                    f"exit 0 但 code_review.dispositions[{idx}] disposition={d} "
                    f"缺非空 reason（impl-code-review-gate）: {report_rel}"
                )
    return None


def _validate_code_review_report(
    cr_data, data: dict, report_rel: str
) -> str | None:
    """收尾审查报告校验体（fix-impl-code-review-gate-readback D1，双候选共用）。

    worktree / 主树两条候选路径读到 ``code-review.json`` 内容后都走本函数，
    逐字相同的判定语义，杜绝双实现漂移。``report_rel`` 仅用于归因文案拼接
    （统一用相对路径字样，与既有文案风格一致）。

    校验顺序与 add-impl-code-review-gate 任务 6.1 完全一致（行为零变化）：
    ``cr_data`` 顶层须为 dict → ``status`` 在 completed/unavailable 白名单内 →
    unavailable 须附非空 ``reason``（否则放行，环境缺失降级）→ ``findings``
    为 list → 结果文件 ``code_review`` 段存在 → ``dispositions`` 别名解析 →
    逐条 disposition 白名单（fixed/rejected/deferred）且 rejected/deferred
    须附非空 ``reason``（条目循环在 ``_validate_disposition_entries``）。
    """
    if not isinstance(cr_data, dict):
        return (
            f"exit 0 但收尾审查报告顶层非对象（impl-code-review-gate）: {report_rel}"
        )
    cr_status = cr_data.get("status", "")
    if cr_status not in ("completed", "unavailable"):
        return (
            f"exit 0 但收尾审查报告 status='{cr_status}' 不在白名单"
            f"（impl-code-review-gate，合法值为 completed/unavailable）: {report_rel}"
        )
    if cr_status == "unavailable":
        reason = cr_data.get("reason", "")
        if not isinstance(reason, str) or not reason.strip():
            return (
                f"exit 0 但收尾审查报告 status=unavailable 缺非空 reason"
                f"（impl-code-review-gate，unavailable MUST 附非空原因）: {report_rel}"
            )
        # unavailable + 非空 reason → 放行（环境缺失降级）
        return None
    # status == "completed" → 校验 findings 与逐条处置
    findings = cr_data.get("findings")
    if not isinstance(findings, list):
        return (
            f"exit 0 但收尾审查报告 findings 非列表（impl-code-review-gate）: {report_rel}"
        )
    code_review = data.get("code_review")
    if not isinstance(code_review, dict):
        return (
            f"exit 0 但结果文件缺少 code_review 段（impl-code-review-gate）: "
            f"请在 .fenix-run-result.json 顶层增加 code_review 段（含 report_path 与"
            f"逐条处置摘要）"
        )
    # evo-spec-concurrency-flight-guard 解卡：键名别名容错。
    # 规范键为 `dispositions`，但提示词/spec 只描述为「逐条处置摘要」而从未
    # 固化键名（spec.md 正文、design.md、prompt 段均未出现该字面量），实现者
    # 据语义自选键名（实测 add-impl-code-review-gate 首跑写的是
    # `findings_summary`，dispositions 缺席）→ 硬门数 0 条而 findings N 条，
    # 判「条数不匹配」→ 原地重试无限循环（键名契约缺口，非 agent 违规）。
    # 读侧 fail-open 接受同义键名，与「软契约不应承担机械对账」的既有取向一致；
    # 对账语义不变（仍是逐条计数 + reason 强校验）。
    cr_dispositions = None
    _alias_hit = "dispositions"
    for _alias in _DISPOSITION_KEY_ALIASES:
        _val = code_review.get(_alias)
        if _val is not None:
            cr_dispositions = _val
            _alias_hit = _alias
            break
    if cr_dispositions is None:
        cr_dispositions = []
    if not isinstance(cr_dispositions, list):
        # 异构载荷（如整型条数——findings_summary 别名本身就暗示可能是摘要
        # 标量）MUST NOT 以未捕获 TypeError 崩溃硬门本身（_format_gap_list
        # 对 code-review item 58ae4e08513b 的同类立场）：先定向归因非数组，
        # 再 fail-closed 落结构化失败（与自检侧 _selfcheck_dispositions_
        # violations 的非数组分支同文案口径，归因用实际命中的别名键名）。
        return (
            f"exit 0 但结果文件 code_review.{_alias_hit} 非数组"
            f"（逐条处置 MUST 为对象数组，每项含 disposition 键）"
            f"（impl-code-review-gate）: {report_rel}"
        )
    if len(cr_dispositions) != len(findings):
        return (
            f"exit 0 但收尾审查 findings 条数({len(findings)})与结果文件"
            f" code_review.{_alias_hit} 条数({len(cr_dispositions)})不匹配"
            f"（impl-code-review-gate）: {report_rel}"
        )
    return _validate_disposition_entries(cr_dispositions, report_rel)


def _check_impl_code_review_artifact(
    runner,
    spec_name: str,
    wt_path: Path | None,
    data: dict,
    run_started_at: float | None = None,
    is_resumed_worktree: bool = False,
) -> str | None:
    """收尾代码质量审查产物硬门（add-impl-code-review-gate，任务 6.1）。

    开关关闭时返回 None（零校验）。开启时按「worktree 优先、主树回退」
    （fix-impl-code-review-gate-readback D2）两处候选路径探测
    ``.fenix/verify-progress/<spec>/code-review.json``：worktree 内存在即以其
    为判定对象（现状行为，零变化）；worktree 缺失时回退读
    ``<project_root>/.../code-review.json``（主树回退候选经
    ``_check_artifact_json_file`` 施加存在/非空/mtime 新鲜/可解析校验，
    ``is_resumed_worktree=True`` 时跳过 mtime 硬拦，见 D3）。两处候选读到
    数据后走**同一套**校验体 ``_validate_code_review_report``（status 白名单 /
    findings 与逐条处置对账 / rejected/deferred 须附非空 reason，D1）。

    两处均缺失时才报缺失，文案同时给出两个已探测位置；候选「文件存在但未过
    校验」（无法解析/陈旧/空等）时原样上抛该候选归因，MUST NOT 折叠为缺失。
    所有失败原因 MUST 含报告路径与具体缺口，格式与既有硬门文案风格一致。
    """
    try:
        from core.config import ConfigLoader

        enabled = ConfigLoader.get_impl_code_review_enabled(runner.config)
    except Exception as e:  # noqa: BLE001
        # 静默吞异常会把整个硬门变成 no-op（code-review item 42781988b0a6）：
        # 懒导入/配置查找里的意外错误（ImportError/AttributeError/配置形态异常）
        # 会让门「消失」而非 fail-closed。此处记 WARNING 留痕（仍返回 None 以
        # 保持与既有降级语义一致——门消失不足以拦下一轮，但至少可观测）。
        runner.logger.warning(
            "agent_runner",
            f"impl-code-review 门开关读取失败（按未启用降级，留痕）: "
            f"{type(e).__name__}: {e}",
        )
        return None
    if not enabled:
        return None

    # ── 候选路径收集（fix-impl-code-review-gate-readback D2）──
    # worktree 候选先行；主树回退候选仅在 project_root 为真 Path 载体时加入
    # （裸 getattr 对 MagicMock 替身无效：其任意属性恒 truthy，`isinstance`
    # 判定才能拦下替身，防 json.loads(mock.read_text()) 抛 TypeError 逸出）。
    report_rel = f".fenix/verify-progress/{spec_name}/code-review.json"
    candidates = []
    if wt_path is not None:
        candidates.append(
            ("worktree", Path(wt_path) / ".fenix" / "verify-progress" / spec_name / "code-review.json")
        )
    root = getattr(runner, "project_root", None)
    if isinstance(root, (str, Path)):
        candidates.append(
            ("main", Path(root) / ".fenix" / "verify-progress" / spec_name / "code-review.json")
        )
    # 按 Path.resolve() 去重（wt_path == project_root / 测试用 tmp_path 同时
    # 充当两者）：保留**先出现者**的校验模式——worktree 语义，不做 mtime 硬拦。
    seen = set()
    dedup_candidates = []
    for mode, path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        dedup_candidates.append((mode, path))
    candidates = dedup_candidates
    if not candidates:
        # 缺载体不校验（与现状 wt_path is None → return None 同语义；MUST NOT
        # 落到下方「两处皆缺」缺失归因，与 spec「无 worktree 载体时不误判」一致）
        return None

    # ── 探测循环（fix-impl-code-review-gate-readback D3/D4）──
    # first_err：记住「文件存在但未过校验」的首个归因（含主树陈旧 err，其文案
    # 含「陈旧」）。全部候选无有效数据时：曾命中非法/陈旧 → 返回该 err；
    # 所有候选文件均不存在 → 缺失归因。
    first_err = None
    for mode, path in candidates:
        if not path.is_file():
            continue
        if mode == "worktree":
            # worktree 候选保持现状：read_text + json.loads，不做 mtime 硬拦
            # （本轮 run 写出的文件本就晚于 run_started_at，加拦无收益）。
            try:
                raw = path.read_text(encoding="utf-8")
                cr_data = json.loads(raw)
            # UnicodeDecodeError / RecursionError 与主树候选
            # _check_artifact_json_file 的防御口径对齐（该函数显式捕之）：
            # 非 UTF-8 字节、超深嵌套 JSON（RecursionError 非 JSONDecodeError
            # 子类，同 _check_artifact_json_file 先例）同样归因为「无法解析」
            # 而非从硬门逸出（fail-closed 契约）。
            except (OSError, UnicodeDecodeError, json.JSONDecodeError,
                    RecursionError) as e:
                if first_err is None:
                    first_err = (
                        f"exit 0 但收尾审查报告无法解析（impl-code-review-gate）: "
                        f"{report_rel} ({e})"
                    )
                continue
        else:
            # 主树回退候选：与其它产物门同源的基础校验（存在/非空/mtime 新鲜/
            # 可解析 JSON）；is_resumed_worktree=True 时跳过 mtime 硬拦（D3，
            # resume 轮的主树陈留报告只剩内容判据保证）。
            err, cr_data = runner._check_artifact_json_file(
                path, "implementer", run_started_at,
                is_resumed_worktree=is_resumed_worktree,
            )
            if err is not None:
                # 文件存在但未过校验（陈旧/空/不可读/非法 JSON）→ 记住归因并
                # 继续尝试下一候选；「缺失」err 不属此类（先行 is_file 已排除，
                # 仅防御探测竞态）。MUST NOT 折叠成缺失归因——spec「主树报告
                # 陈旧 → 文案 MUST 指明陈旧」场景依赖此终态。
                # 按共享常量判定类别（item b02fb265b7e5）：err 的唯一缺失归因
                # 即 _check_artifact_json_file 的「结果文件缺失」文案，与既有
                # 「缺失」子串判定等价，不再依赖裸字面量。
                if _ARTIFACT_ERR_MISSING not in err and first_err is None:
                    first_err = err
                continue
        # 读到有效数据 → 同一套校验体（worktree / 主树逐字相同的判定语义）；
        # 结构校验失败即作为本轮候选的判定结果上抛（MUST NOT 继续探测）。
        return _validate_code_review_report(cr_data, data, report_rel)

    if first_err is not None:
        return first_err
    # 所有候选文件均不存在 → 缺失归因，文案列出两个已探测位置（既有测试断言
    # 依赖 `报告缺失` 与 `code-review.json` 字样，动态部分追加探测范围说明）。
    return (
        f"exit 0 但收尾审查报告缺失（impl-code-review-gate）: {report_rel}"
        f"（已探测 worktree 与主树两个位置）"
    )


# quality-gates.json 形态违规告警的 signal_type（fix-quality-gates-flat-form-
# and-explainability 3.1，契约源 specs/quality-gates-soft-gate-alerts/spec.md）。
# 不在 admin_monitor.STORED_SIGNAL_TYPES 封闭白名单内 → monitor 摄取循环跳过，
# 不触发任何自动唤起/派发——「只加可见性不加强度」在消费面成立。
_QG_FORM_DRIFT_SIGNAL_TYPE = "quality-gates-form-drift"


def _alert_quality_gates_form_drift(
    runner,
    spec_name: str,
    rel: str,
    violation_class: str,
    description: str,
    *,
    location: str,
    gate_id: str | None = None,
) -> None:
    """quality-gates.json 形态违规写人工告警（宽松对账可见性增强、不加强度）。

    与既有 WARNING 同语义、新增 admin_alerts 落面：dashboard 告警面板可见，
    脱离「只有 daemon 日志」的盲区。软约束边界不变——告警 MUST NOT 产生任何
    失败终态/打回/预算消耗/派发阻塞；不注册 choices（落不可裁决信号桶，人工
    确认处理即可）。

    entry 字段固化约定（design Decision 3，防消费面踩空）：
    - ``kind`` 显式写 SIGNAL——``_normalize_entry`` 无 kind 默认值，而消费面
      按 kind 分派（``mark_alert_handled`` → ``mark_signal_handled`` 只认
      SIGNAL），漏写则两个闭环端点都不匹配（处置 404 死胡同）；
    - ``violation_class`` 机器可读类别（missing-gates / bad-json /
      out-of-contract-gate-id / out-of-enum-status 四值，与四类违规一一对应）
      ——signal_type 单值固定，is_inflight 按 (spec, signal_type,
      violation_class) 判在途，否则一类未处理会抑制其余三类；
    - ``location`` 漂移副本标记（worktree / main-tree）——``rel`` 对两处候选
      位置是同一常量串，仅凭 file/evidence 无法定位实际漂移的是哪个副本；
    - ``gate_id`` 仅按 gate 的类别（out-of-contract-gate-id /
      out-of-enum-status）携带违规 gate-id；文件级类别（missing-gates /
      bad-json）无 gate 维度，缺省不写。

    在途身份 = (spec, signal_type, violation_class, location, gate_id)：除按
    类别防跨类抑制外，再按副本与 gate 实例区分——否则一处告警未处理期间，
    另一副本/另一 gate-id 的同类漂移会被 append_if_absent 静默去重，只留
    daemon 日志（code-review item 26cf034dbb6f）。残留限制：同一身份在未
    处理期间仍只保留首见一条，后续复现不刷新已存记录的 description/evidence
    （append_if_absent 语义，首见为准），身份内逐次漂移仅 daemon 日志留痕；
    修复前落盘的存量记录（无 location/gate_id 字段）不计入在途，升级后同类
    漂移会再落一条新告警。

    写入整体 try/except fail-open（仅记日志），不影响 run 收尾主流程。
    """
    try:
        from core.admin_store import SIGNAL, AdminStore

        store = AdminStore(getattr(runner, "project_root", None), runner.logger)
        entry = {
            "kind": SIGNAL,
            "signal_type": _QG_FORM_DRIFT_SIGNAL_TYPE,
            "spec": spec_name,
            "severity": "info",
            "description": description,
            "file": rel,
            "location": location,
            "violation_class": violation_class,
            "evidence": (
                f"file={rel}; location={location}; violation_class={violation_class}"
                + (f"; gate_id={gate_id}" if gate_id else "")
            ),
        }
        if gate_id is not None:
            entry["gate_id"] = gate_id
        store.append_if_absent(
            entry,
            is_inflight=lambda r: (
                r.get("kind") == SIGNAL
                and r.get("signal_type") == _QG_FORM_DRIFT_SIGNAL_TYPE
                and r.get("spec") == spec_name
                and r.get("violation_class") == violation_class
                and r.get("location") == location
                and r.get("gate_id") == gate_id
                and not r.get("handled")
            ),
        )
    except Exception as e:  # noqa: BLE001 —— fail-open：告警通道故障不阻断收尾
        _logger.warning(
            "quality-gates 形态违规告警写入失败（fail-open，不影响收尾）: %s", e
        )


def _check_quality_gates_soft(runner, spec_name: str, wt_path: Path | None) -> None:
    """quality-gates.json 宽松对账（add-quality-gates-visibility，任务 3.2）。

    落盘是 prompt 软约束，本检查 MUST NOT 产生任何失败终态/打回/预算消耗：
    - 文件缺失 → 零拦截、零告警（历史 spec 与偶尔漏写的 run 零打回）；
    - 文件存在 → 仅做机械合法性检查（JSON 可解析、status 在枚举内、gate-id 在
      全集内），违规记 WARNING 日志并放行，同时经 _alert_quality_gates_form_drift
      写 admin_alerts 人工告警（fix-quality-gates-flat-form-and-explainability
      3.1，可见性增强不加强度：signal_type=quality-gates-form-drift、
      severity=info、kind=SIGNAL、不注册 choices，未处理期间按
      (spec, signal_type, violation_class, location, gate_id) 去重——副本与
      gate 实例各自成条，见 _alert_quality_gates_form_drift）。

    双位置候选与读侧一致（worktree 优先、主树兜底），两处各自独立检查，并以
    location 标记（worktree / main-tree）随告警落库——``rel`` 对两处是同一
    常量串，无标记则告警无法区分实际漂移副本。常量经懒导入取自 dashboard
    读侧单点（模块加载期反向 import 会成环，D4 先例；调用点在 run 收尾，
    无循环风险）。键名以 quality_gates.py 固化契约为唯一真源，禁止在本处
    另写同义词表。
    """
    try:
        from core.dashboard.data.quality_gates import GATE_STATUSES, RUN_GATE_IDS
    except Exception as e:  # noqa: BLE001
        # 懒导入失败（循环导入/dashboard.data 包 __init__ 副作用等）不得击穿
        # 本函数「MUST NOT 产生任何失败终态」的宽松对账契约（code-review
        # item 9f167849d8a1）：记 WARNING 留痕后按未启用降级返回 None（直接
        # 返回，下方 GATE_STATUSES/RUN_GATE_IDS 引用点不再触达，避免
        # NameError）。日志走模块标准通道 _logger（通道契约见 _logger 定义
        # 处：MUST NOT 走 runner.logger，测试替身无法被 caplog 捕获），与
        # 同函数 JSON 解析/枚举违规告警同通道。
        _logger.warning(
            "quality-gates 宽松对账常量导入失败（按未启用降级，留痕）: %s: %s",
            type(e).__name__,
            e,
        )
        return None

    rel = f".fenix/verify-progress/{spec_name}/quality-gates.json"
    candidates: list[tuple[Path, str]] = []
    if wt_path is not None:
        candidates.append(
            (
                Path(wt_path) / ".fenix" / "verify-progress" / spec_name / "quality-gates.json",
                "worktree",
            )
        )
    root = getattr(runner, "project_root", None)
    if isinstance(root, (str, Path)):
        candidates.append(
            (
                Path(root) / ".fenix" / "verify-progress" / spec_name / "quality-gates.json",
                "main-tree",
            )
        )
    seen: set = set()
    for path, location in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            # 文件系统级读取失败 / 编码级损坏 ≠ JSON 损坏（与
            # _check_artifact_json_file 的 unreadable 归因同口径、与
            # _check_repo_code_review_artifact 的分类取向一致；code-review
            # item dd9b8603791a）：只记 WARNING、不落 bad-json 告警，避免
            # 环境/编码侧异常冒用 violation_class 污染在途身份去重、误导
            # 排障方向。注意 UnicodeDecodeError 是 ValueError 子类，本分支
            # MUST 列于其后 ValueError 分支之前。
            _logger.warning(
                "quality-gates.json 读取失败（宽松对账，仅告警放行；非 JSON 损坏）"
                ": %s (%s)", rel, e,
            )
            continue
        except (ValueError, RecursionError) as e:
            # RecursionError：超深嵌套 JSON 会让 json.loads 抛 RecursionError
            # （非 JSONDecodeError/ValueError 子类，同 _check_artifact_json_file
            # 与 _check_repo_code_review_artifact 既有先例）——quality-gates.json
            # 是 agent 侧产物，不接住会逸出本软检查、击穿「MUST NOT 产生任何
            # 失败终态」契约，故与非法 JSON 同口径记 WARNING + bad-json 告警放行。
            _logger.warning(
                "quality-gates.json 无法解析（宽松对账，仅告警放行）: %s (%s)", rel, e
            )
            _alert_quality_gates_form_drift(
                runner, spec_name, rel, "bad-json",
                f"quality-gates.json 无法解析（宽松对账，仅告警放行）: {rel} ({e})",
                location=location,
            )
            continue
        gates = data.get("gates") if isinstance(data, dict) else None
        if not isinstance(gates, dict):
            _logger.warning(
                "quality-gates.json 顶层缺 gates 对象（宽松对账，仅告警放行）: %s", rel
            )
            _alert_quality_gates_form_drift(
                runner, spec_name, rel, "missing-gates",
                f"quality-gates.json 顶层缺 gates 对象（宽松对账，仅告警放行）: {rel}",
                location=location,
            )
            continue
        for gid, entry in gates.items():
            if gid not in RUN_GATE_IDS:
                _logger.warning(
                    "quality-gates.json 出现契约外 gate-id='%s'（宽松对账，仅告警"
                    "放行；合法集 %s）: %s", gid, list(RUN_GATE_IDS), rel,
                )
                _alert_quality_gates_form_drift(
                    runner, spec_name, rel, "out-of-contract-gate-id",
                    f"quality-gates.json 出现契约外 gate-id='{gid}'（宽松对账，仅"
                    f"告警放行；合法集 {list(RUN_GATE_IDS)}）: {rel}",
                    location=location, gate_id=gid,
                )
            if not isinstance(entry, dict) or entry.get("status") not in GATE_STATUSES:
                bad = entry.get("status") if isinstance(entry, dict) else "<非对象>"
                _logger.warning(
                    "quality-gates.json gate-id='%s' status='%s' 不在枚举（宽松对账，"
                    "仅告警放行；合法值 %s）: %s", gid, bad, list(GATE_STATUSES), rel,
                )
                _alert_quality_gates_form_drift(
                    runner, spec_name, rel, "out-of-enum-status",
                    f"quality-gates.json gate-id='{gid}' status='{bad}' 不在枚举"
                    f"（宽松对账，仅告警放行；合法值 {list(GATE_STATUSES)}）: {rel}",
                    location=location, gate_id=gid,
                )
    return None


def _check_repo_code_review_artifact(manifest: list, project_root, run_id: str) -> str | None:
    """周期性代码审查 run 的产物硬门（2026-09-19 原地修复；聚合口径
    add-code-review-sharded-out 2.2/D5）。

    事故取证（触发首次修复的实证）：`run_code_review` 此前**全链无任何产物门**
    ——run 退出码 0（转录 `subtype: success`）但 agent 从未写过
    ``out-<run_id>.jsonl``（只写了自己切批的 ``batch_N.json``，声明要起 10 个
    并行子代理后末轮直接收工），``_read_code_review_out`` 对缺失文件返回空列表，
    落账走完 ``inserted=0/updated=0`` 后仍返回 ``success=True``：空跑被当成功，
    用户在 Dashboard 看到的进度条闪一下就消失，且全仓核销因 ``findings`` 为空而
    被跳过（未误核销，属侥幸）。对照同族车道——spec-review 有
    ``_check_agent_result_artifact``、implementer 有 ``_check_impl_result_artifact``
    ——本车道是唯一完全无门的。

    判据（fail-closed：无审查产物 ≠ 无问题；分片直写模式下为聚合口径）：
    - ``manifest`` 为空 → 返回 None（调用方已前置跳过，此处不重复判定，
      避免「空 manifest」被误伤）；
    - 主产物 ``out-<run_id>.jsonl`` 与全部分片 ``out-<run_id>-b<N>.jsonl``
      （``code_review.shard_paths`` 发现）**合计零有效行**（或全部缺失）→
      返回失败原因（点名 run_id）；任一来源存在至少一行有效结果行即通过
      存在性校验（manifest 覆盖率校验口径不变）。

    「有效行」与 ``_read_code_review_out`` 同口径：非空、可解析为 dict、
    且 ``findings`` 为列表——「该文件审完了」的登记形态。刻意不复用
    ``read_progress`` 的 ``done``（聚合去重行数，服务进度条实时性）：
    进度展示与门禁判定目的不同，门禁必须防「写满垃圾行骗过门」。

    注：``unavailable`` 降级语义（ocr 缺失/网关不可达）**不适用于本车道**——
    本 run 的审查手段是 agent 自身的 LLM 阅读，ocr 只是可选加速器；agent 没写
    逐文件结果就是没审，不存在「环境不可用所以免责」的口子。

    签名说明（模块函数形态，非门族 runner 首参）：首参为 ``manifest`` 而非
    runner，MUST NOT 登记进 runner._FORWARDER_REGISTRY（partial 会把 runner
    注入 manifest 形参 → TypeError，code-review 条目 30a9ff6b4000 确认的
    埋雷形态）。本函数**直 import 专用、不经门面**——调用方经
    ``from core.agent_runner.result_gate import
    _check_repo_code_review_artifact`` 直取（maintenance_runs.run_code_review /
    tests），后续新增调用点按此形态，勿经 runner.<方法名> 误调。
    """
    if not manifest:
        return None
    from core.code_review import out_path as cr_out_path, shard_paths

    main = cr_out_path(project_root, run_id)
    shards = shard_paths(project_root, run_id)
    sources = [*shards, main]
    valids = 0
    unreadable: list[str] = []
    for src in sources:
        if not src.is_file():
            continue
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            # 静默跳过会把「文件系统读取失败」误归因为「agent 没落行」，
            # 取证门失真——记 WARNING（经 _logger，caplog 可断言）
            # 并收集名单进失败文案，供 valids<=0 时区分环境侧根因。
            unreadable.append(src.name)
            _logger.warning(
                "审查产物读取失败（repo-code-review-gate，该来源不计入有效行）"
                ": %s (%s)", src.name, e,
            )
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, RecursionError):
                # 超深嵌套行会让 json.loads 抛 RecursionError，与非法 JSON 行
                # 同口径：不计入有效行（valids<=0 时由上方失败文案统一归因）。
                continue
            if isinstance(rec, dict) and isinstance(rec.get("findings"), list):
                valids += 1
    if valids <= 0:
        base = (
            f"审查产物为零有效行（repo-code-review-gate）：run {run_id} manifest "
            f"{len(manifest)} 个文件，主产物 {main.name} 与 {len(shards)} 个分片"
            f"合计无任何有效结果行"
        )
        if unreadable:
            return (
                f"{base}；其中 {'、'.join(unreadable)} 存在但读取失败（OSError，"
                f"已记 WARNING）——有来源因文件系统级异常被排除出有效行统计，"
                f"优先排查环境侧读取错误而非 agent 转录"
            )
        return (
            f"{base}——run 退出码为 0 不等于审查完成，agent MUST "
            f"逐文件落结果行（主产物或分片均可）"
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

    # add-fasttrack-verification-write-gate（任务 1.1）：fast-track 的 success
    # 结果文件在 run 末即校验 verification 段结构，缺段/不完整当场报错——由既有
    # 产物门重试机制（_handle_artifact_gate_retry，结构类失败不计数不降级）驱动
    # 实现者同 session 原地补写，不再等到 merge 前 dispatch 交接点才拒收（run 已
    # success 终态、只能整轮作废重派）。解析单源复用
    # core/fast_track_result.parse_fast_track_verification，与 dispatch 第二道
    # 防线（_hard_check_fast_track）同一 schema。本函数被 full 车道共用，故以
    # 结果文件自报 mode 字段为车道判据：partial/error（诚实退出，本就不含
    # verification 段）与 mode 非 fast-track 的结果一律不触发，full 车道不变。
    # 取舍（code-review item 35216f232507）：车道事实（runner 侧 lane）未传入
    # 本门，判据依赖结果文件自白——fast-track 车道 run 成功收尾但漏写 mode 时
    # 本段静默不触发，属有时效损耗的 fail-open，由 merge 前 dispatch 侧
    # _hard_check_fast_track 第二道网兜底拒收；反之 full 车道误写
    # mode=fast-track 被强制要求携带合法 verification 段（fail-closed 方向）。
    if (
        status == "success"
        and data.get("mode") == "fast-track"
        and parse_fast_track_verification(data) is None
    ):
        return (
            f"exit 0 但 fast-track 结果文件 verification 段缺失或结构不完整"
            f"（须含非空 scenarios、每条含非空 scenario_id/description、"
            f"status 枚举合法、verdict 属 verified/bug-found，"
            f"{agent_type} 产物硬门）: {result_path}"
        )

    # status ∈ {success, partial} → 以 worktree 内 tasks.md 为对象的判据
    # （tasks.md 相对路径单点在 run_task_track.tasks_md_path，判据读取与
    # 各失败文案同源取用——code-review item df136b3985e7 / 52e0dac160b4）
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

    # evo-add-acceptance-deviation-reporting 2.1：findings 数组结构校验——字段
    # 缺失零拦截（历史 run、无偏差 run 零开销）；形态非法 fail-closed（结构类
    # 失败，不计数不降级）。implementer/fast-track 两车道共用本判据，同义生效。
    findings_err = _validate_impl_findings(data, agent_type, result_path)
    if findings_err is not None:
        return findings_err

    # add-impl-ocr-parallel-lane（任务 2.2）：实现者产物硬门不再校验
    # code_review/dispositions 段——收尾 ocr 由框架侧异步车道承载，裁决点
    # 移至 testing 出口 join（core/pm_engine/dispatch/queue.py 的
    # ``Dispatcher._ocr_join_gate``，其自持 _read_ocr_artifact + 指纹校验
    # 的完整判定，不经本函数）。实现者不带 code_review 段即可正常过门；
    # ``_check_impl_code_review_artifact`` 现已无生产调用点（join 侧不
    # 复用它），仅 runner.py 门面注册桩与测试引用保留——勿视为仍在
    # 收尾链路生效。

    # add-quality-gates-visibility（任务 3.2）：quality-gates.json 宽松对账——
    # 独立于上方判定：存在则仅机械合法性检查、违规仅 WARNING 放行；缺失零拦截。
    # 本调用 MUST NOT 影响返回值（无失败终态，不新增打回路径）。
    runner._check_quality_gates_soft(spec_name, wt_path)

    if status == "success":
        # 诚实退出（改进②）：无法完成的已申报任务从「全部任务」基准里扣除，
        # 使「未勾选硬缺口」不含它们，同时 completed_tasks 仍须 == 已勾选集合。
        effective_all = [t for t in all_ids if t not in unattainable_ids]
        gate_err = runner._check_success_completion(
            spec_name, result_path, data, effective_all, checked_ids
        )
        if gate_err is None:
            # evo-add-acceptance-deviation-reporting 2.1：组合校验——success ∧
            # 偏差任务 ∈ completed_tasks → 拒绝（结构类失败；partial/unattainable
            # 路径不感知 findings，语义不变）。
            gate_err = _check_acceptance_deviation_success(runner, data, result_path)
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
            # 降级放行与自然通过同为「成功姿态过门」，此处补跑 host_changes 汇总
            # 软校验（纯 WARNING 留痕，MUST NOT 影响返回值），使两条放行路径的
            # 软审计覆盖一致，与下方注释声明对齐（code-review item 7f2bff4c4adc）。
            runner._check_host_changes_summary_soft(spec_name, data, result_path, wt_path)
            return None
        return gate_err

    if gate_err is None:
        # 门禁干净通过 → 清零任务完成度类拒绝计数（防陈旧计数日久误降级）。
        _clear_task_gate_rejections(runner, spec_name)

    # evo-add-host-change-governance 2.3：host_changes 汇总字段警告级校验——
    # 独立于上方判定：字段缺失零拦截，形态/一致性问题仅 WARNING 放行。
    # 本调用 MUST NOT 影响返回值（无失败终态，不新增打回路径），与上方
    # _check_quality_gates_soft 同机制。
    runner._check_host_changes_summary_soft(spec_name, data, result_path, wt_path)

    return gate_err


# ── 宿主变更登记与汇总对账（evo-add-host-change-governance 2.3）─────────────
# 登记权威载体在 worktree 根 host_changes.json（与 .fenix-run-result.json 同级）：
# 击杀类终止（超时/轮次上限/判停）无 run-result 时登记文件是唯一权威载体
# （design「登记载体实测约束」），收尾才在 run 结果 host_changes 字段汇总，
# 两处须一致。解析与常量在 result_gate 单点定义（runner 终态路径与软校验共引，
# 禁止第二套解析）。

# 登记文件名（worktree 根，与 .fenix-run-result.json 同级）。
HOST_CHANGES_REGISTRY_NAME = "host_changes.json"

# 汇总/登记元素的字段约定（design D3：对象路径/版本/备份位置/回滚指引）。
HOST_CHANGE_FIELDS = ("object_path", "version", "backup", "rollback")


def host_change_object_path(entry) -> str:
    """取登记/汇总元素的对象路径（兼容 path 别名）；非 dict 或缺路径返回 ""。"""
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("object_path") or entry.get("path") or "").strip()


def parse_host_changes_registry(path) -> "list | None":
    """读取宿主变更登记文件（worktree 根 host_changes.json）。

    返回登记条目列表；文件缺失/不可读/非法 JSON/顶层非数组 → ``None``（按
    「无有效登记」处理，调用方零动作——登记文件是 agent 侧手写产物，解析
    缺陷 MUST NOT 放大为终态/门禁路径的新失败面）。空数组是合法值（返回
    ``[]``），与「文件缺失」可区分，供调用方按需留痕。
    容忍 ``{"changes": [...]}`` 包装形态（agent 习惯元数据包裹的容错）。
    """
    try:
        p = Path(path)
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        # RecursionError：超深嵌套 JSON（非 ValueError 子类，同
        # _check_artifact_json_file 先例）——登记是 agent 产物，不接住会
        # 逸出到 runner 终态路径，违反 fail-open 契约。
        return None
    if isinstance(data, dict) and isinstance(data.get("changes"), list):
        data = data["changes"]
    if not isinstance(data, list):
        return None
    return data


def _check_host_changes_summary_soft(
    runner, spec_name: str, data, result_path, wt_path
) -> None:
    """run-result host_changes 汇总字段警告级校验（evo-add-host-change-governance 2.3）。

    提示词契约：登记以 worktree 根 host_changes.json 为权威载体，收尾在 run
    结果汇总且两处一致。本检查只做警告级机械对账，MUST NOT 产生任何失败终态/
    打回/预算消耗（返回值恒 None、不参与门判定）：

    - run 结果缺 ``host_changes`` 字段 → 零拦截零告警（历史 run、无宿主变更
      的 run 零开销；「缺失不拒绝结果」的 fail-open 语义）；
    - 字段在场但形态非法（非数组/元素缺对象路径）→ WARNING 放行；
    - 与 worktree 登记文件两处不一致（登记在场但汇总缺字段、或对象路径集合
      不等）→ WARNING 放行（权威载体是登记文件，汇总漂移只降级留痕质量）。

    日志走模块标准通道 _logger（通道契约见 _logger 定义处：MUST NOT 走
    runner.logger，测试替身无法被 caplog 捕获），与 quality-gates 软检查同型。
    """
    try:
        if not isinstance(data, dict) or "host_changes" not in data:
            return  # 字段缺失 → 零拦截（fail-open 语义锚点）
        summary = data.get("host_changes")
        rel = f"{result_path}#host_changes" if result_path is not None else "#host_changes"
        if not isinstance(summary, list):
            _logger.warning(
                "run-result host_changes 汇总字段非法（须为数组，宽松对账仅告警"
                "放行）: %s", rel,
            )
            return
        bad = [e for e in summary if not host_change_object_path(e)]
        if bad:
            _logger.warning(
                "run-result host_changes 汇总存在 %d 个缺对象路径的元素（宽松对账"
                "仅告警放行）: %s", len(bad), rel,
            )
        # 两处一致对账：worktree 登记在场时，对象路径集合应与汇总一致。
        reg = None
        if wt_path is not None:
            reg = parse_host_changes_registry(
                Path(wt_path) / HOST_CHANGES_REGISTRY_NAME)
        if reg is None:
            return  # 登记缺失/非法：权威载体缺位，汇总无从对账 → 放行
        summary_paths = {host_change_object_path(e) for e in summary} - {""}
        reg_paths = {host_change_object_path(e) for e in reg} - {""}
        if summary_paths != reg_paths:
            _logger.warning(
                "run-result host_changes 汇总与 worktree 登记不一致（宽松对账仅"
                "告警放行；汇总=%s 登记=%s）: spec=%s",
                sorted(summary_paths), sorted(reg_paths), spec_name,
            )
    except Exception as e:  # noqa: BLE001 — fail-open：软检查自身故障不阻断门禁
        _logger.warning(
            "host_changes 汇总软校验异常（fail-open 放行）: %s: %s",
            type(e).__name__, e,
        )


# ── 转录末轮 fenced JSON 捞回（fix-impl-resultfile-contract-gap D4）────────────
# 与 runner.py 既有 spec-review 捞回同族：从 .fenix/runs/<run_id>.jsonl 末轮
# assistant text 抽最后一个 fenced JSON，status 在白名单内即代写落盘——把
# 「整轮白烧重试」降为「零成本回收」。泛化为车道无关：路径与白名单按
# agent_type 分派；调用点（runner.py）MUST 在拷回块之前执行。
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)

# 模块唯一标准 logging 通道（add-quality-gates-visibility 任务 3.2 引入的
# soft-gate 告警与 salvage 捞回共用；历史 _salvage_logger / _soft_gate_logger /
# _SELFCHECK_LOGGER 三别名已合并为单常量，避免误读为三条独立通道）。caplog
# 可断言；MUST NOT 走 runner.logger（测试替身无法被 caplog 捕获）。
_logger = logging.getLogger("fenixd.agent_runner.result_gate")


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

    白名单分派：spec-review 用 ``SPEC_REVIEW_RESULT_STATUS_WHITELIST``
    （本模块已导入，默认值）；implementer/fast-track 的 ``_IMPL_RESULT_STATUSES``
    是 ``AgentRunner`` 类属性，不得导出为模块常量（1.1），MUST 经 ``statuses``
    参数由调用点传入。``statuses is None`` 时降级为该车道白名单或空（fail-closed）。
    """
    if agent_type == "spec-review":
        target = spec_review_result_path(project_root, spec_name)
        whitelist = statuses if statuses is not None else SPEC_REVIEW_RESULT_STATUS_WHITELIST
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
                except (json.JSONDecodeError, RecursionError):
                    # 超深嵌套行会让 json.loads 抛 RecursionError（非
                    # JSONDecodeError 子类，同 _check_artifact_json_file 口径）
                    # ——按不可读行跳过，守住本函数「转录损坏不抛异常」契约。
                    continue
                if not isinstance(d, dict):
                    continue
                if d.get("type") != "assistant":
                    continue
                # message 为非 dict 载荷（JSON 字符串/数字/列表等）时不调 .get，
                # 防 AttributeError 逸出本函数「转录损坏不抛异常」的防御口径。
                msg = d.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                # content 为不可迭代标量（int/float/bool 等）时 for 会抛
                # TypeError，与 msg 同口径归一为 None，守住「转录损坏不抛异常」。
                if not isinstance(content, list):
                    content = None
                for c in content or []:
                    if isinstance(c, dict) and c.get("type") == "text":
                        last_text = c.get("text") or ""
    except (OSError, UnicodeDecodeError):
        # 转录含无效 UTF-8 视为「不可读」（同 _check_artifact_json_file 口径），
        # 不抛异常、不落盘返回 False。
        return False
    if not last_text:
        return False
    matches = _FENCED_JSON_RE.findall(last_text)
    if not matches:
        return False
    # code-review item 5513a0971a0a：fail-closed 对齐 docstring——只认末轮
    # 最后一个 fenced 块。旧实现倒序扫全部块取首个白名单命中，末块为白名单
    # 外形态（总结性/异构 JSON）时会把更早位置的历史草稿载荷捞出代写为结果
    # 文件，与「末轮终态」契约相悖；现在末块不合规即整体放弃（返回 False），
    # 交由既有重试/归因通道处置。
    try:
        payload = json.loads(matches[-1])
    except (json.JSONDecodeError, RecursionError):
        # fenced 块来自 agent 完全可控的末轮 assistant text，超深嵌套 JSON
        # 会让 json.loads 抛 RecursionError（非 JSONDecodeError 子类，同
        # _check_artifact_json_file 先例）——按「抽不出合法 JSON」口径放弃，
        # 守住本函数「转录缺失/不可读 → 不抛异常」契约。
        payload = None
    if not isinstance(payload, dict) or payload.get("status") not in whitelist:
        _logger.warning(
            "%s 结果捞回放弃：转录末轮最后一个 fenced JSON 非合法结果载荷"
            "（status=%r 不在白名单或块不可解析），不代写 spec=%s run_id=%s",
            agent_type,
            payload.get("status") if isinstance(payload, dict) else None,
            spec_name, run_id)
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # code-review item ceea0880b863：mkstemp + os.replace 原子落盘（同
        # _copyback_run_result 的 _write_atomic 手法），避免写盘中途异常/被杀
        # 留下截断 JSON——上方 target.exists() 守卫会把半截文件当成「结果已写」
        # 永久阻断后续轮捞回。
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                # 孤立代理符预清洗（code-review item 0207a767a725，同
                # run_files.append_run_line 的 3644eb85f017 口径）：载荷可含
                # \udXXX 转义（json.loads 接受、json.dumps 本身成功），文本模式
                # write 的 UTF-8 编码抛 UnicodeEncodeError（ValueError 族）不在
                # 下方 except OSError 捕获面内，会击穿「转录缺失/不可读 → 不落
                # 盘不抛异常返回 False」契约——encode('utf-8', 'replace') 预清洗
                # 后写。
                f.write(
                    json.dumps(payload, ensure_ascii=False, indent=2)
                    .encode("utf-8", "replace")
                    .decode("utf-8")
                )
            # mkstemp 建文件为 0600，rename 前放宽到 write_text 的 umask 缺省
            # 0644（同 verify_report 手法；chmod 失败不阻断写入）。
            try:
                os.chmod(tmp_path, 0o644)
            except OSError:
                pass
            # code-review item b926fcc65614：os.replace 无条件覆盖，会击穿上方
            # target.exists() 守卫与落盘之间的竞态窗口（并发 attempt/同轮二次
            # 捞回抢先建目标）。改用同目录硬链接 os.link 占位提交——目标已存在
            # 即 FileExistsError，按上方「已存在不覆盖」口径放弃；个别不支持
            # 硬链接的文件系统退回 replace（接受极窄竞态，保住落盘可用性）。
            try:
                os.link(tmp_path, target)
            except FileExistsError:
                return False
            except OSError:
                os.replace(tmp_path, target)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
    except OSError as e:
        _logger.warning(
            "结果捞回写盘失败 '%s' (%s): %s", spec_name, agent_type, e)
        return False
    _logger.warning(
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
    if not sub_run_id or _ARTIFACT_ERR_MISSING not in error_text:
        return error_text
    stall_reason = classify_terminal_stall(runner, sub_run_id)
    return error_text.replace(
        _ARTIFACT_ERR_MISSING, f"{_ARTIFACT_ERR_MISSING}（{stall_reason}）", 1)


def _format_gap_list(gap: list, limit: int = 20) -> str:
    """缺口任务 id 清单格式化（2.7 归因可诊断）：超 limit 项截断并标注总数。

    元素统一转 str 再排序/拼接（code-review item 58ae4e08513b）：入参直接来自
    解析后的 result-file JSON（completed_tasks/unfinished/unattainable），格式
    并不受控——异构载荷（如 ``[1, "1.1"]``）会让 ``sorted`` 抛 TypeError、
    同构非字符串列表会让 ``join`` 抛 TypeError。gate 的预期姿态是 fail-closed
    落失败消息，MUST NOT 以未捕获异常崩溃硬门本身。
    """
    if not gap:
        return ""
    items = sorted(str(x) for x in gap)
    if len(items) <= limit:
        return "、".join(items)
    return "、".join(items[:limit]) + f" 等共 {len(gap)} 项"


def _invalid_completed_ids(items) -> list:
    """completed_tasks / unfinished 中的非法任务 id（形如 x.y 之外的取值）。

    合法性判定与 parse_tasks_md 同源（core.run_task_track.is_task_id）：
    任务 id 语法为 ``<组号>.<任务号>[可选小写字母后缀]``（``1.1`` / ``1.2b``）。
    字母后缀是 planner 产出补充任务时的正常形态，判为非法会让实现者
    如实上报被硬门拒绝（2026-09-15 事故，见 run_task_track 模块 docstring）。
    """
    bad = []
    for it in items:
        if not is_task_id(it):
            bad.append(it)
    return bad


def _validate_impl_findings(data: dict, agent_type: str, result_path) -> str | None:
    """impl run 结果 findings 数组结构校验（evo-add-acceptance-deviation-reporting 2.1）。

    findings 为可选字段：缺失 → 零拦截（历史 run、无偏差 run 零开销）。在场时
    须为对象数组且逐条 ``type`` 在 IMPL_FINDINGS_TYPE_WHITELIST 内（白名单单源
    在 prompt_builder，提示词契约与硬门共用）；acceptance-deviation 条目须含
    三要素（``task`` 合法 id / ``literal`` / ``substitute`` 非空）与非空
    ``evidence``（替代证据路径，防口头替代——design Open Question 首版必填裁定）。

    违规返回**结构类**失败文案（无 TASK_GATE_ERROR_PREFIX 前缀 → runner 归
    [artifact-structural]，不参与「只卡第一次」降级）：findings 形态是产物
    结构问题，与任务完成度对账分属两类。implementer/fast-track 两车道共用
    本判据（_check_impl_result_artifact 单点），同义生效。
    """
    findings = data.get("findings")
    if findings is None:
        return None
    if not isinstance(findings, list):
        return (
            f"exit 0 但结果文件 findings 非数组（{agent_type} 产物硬门）: "
            f"{result_path}"
        )
    for idx, item in enumerate(findings):
        if not isinstance(item, dict):
            return (
                f"exit 0 但结果文件 findings[{idx}] 非对象（{agent_type} 产物硬门）: "
                f"{result_path}"
            )
        ftype = item.get("type", "")
        if ftype not in IMPL_FINDINGS_TYPE_WHITELIST:
            return (
                f"exit 0 但结果文件 findings[{idx}].type='{ftype}' 不在白名单"
                f"（合法值: {'/'.join(IMPL_FINDINGS_TYPE_WHITELIST)}，"
                f"{agent_type} 产物硬门）: {result_path}"
            )
        if ftype != ACCEPTANCE_DEVIATION_TYPE:
            continue
        if not is_task_id(item.get("task", "")):
            return (
                f"exit 0 但结果文件 findings[{idx}]（acceptance-deviation）"
                f"task='{item.get('task', '')}' 非合法任务 id"
                f"（{agent_type} 产物硬门）: {result_path}"
            )
        for key in ("literal", "substitute", "evidence"):
            val = item.get(key, "")
            if not isinstance(val, str) or not val.strip():
                return (
                    f"exit 0 但结果文件 findings[{idx}]（acceptance-deviation）"
                    f"缺非空 {key}（三要素 task/literal/substitute + evidence "
                    f"替代证据路径，{agent_type} 产物硬门）: {result_path}"
                )
    return None


def impl_findings_deviation_tasks(data: dict) -> list:
    """提取结果文件 findings 中验收偏差条目的任务 id（结构合法前提下调用）。

    仅返回 ``type == acceptance-deviation`` 条目的 ``task``；字段缺失/形态
    异常返回空列表（结构违规由 ``_validate_impl_findings`` 归因，本函数只做
    组合判据的取值）。
    """
    findings = data.get("findings")
    if not isinstance(findings, list):
        return []
    return [
        str(item.get("task"))
        for item in findings
        if isinstance(item, dict) and item.get("type") == ACCEPTANCE_DEVIATION_TYPE
    ]


def _check_acceptance_deviation_success(
    runner, data: dict, result_path, agent_type: str = "implementer"
) -> str | None:
    """组合校验：success ∧ 偏差任务 ∈ completed_tasks → 拒绝（…2.1）。

    验收偏差条目在场的任务当轮 MUST NOT 勾选（design 闭环语义：该轮经
    unfinished 申报走 partial；规划层按任务行注解重出替代场景链后，后续
    success 轮不再带偏差条目，自然过门——本门无状态，不感知轮次）。命中返回
    结构类失败文案（无 TASK_GATE_ERROR_PREFIX 前缀 → runner 归
    [artifact-structural]，不参与「只卡第一次」降级），文案指引 partial /
    替代场景链 / unattainable 三条出路。partial/unattainable 路径不调用本
    函数（语义不变）。
    """
    deviation_tasks = impl_findings_deviation_tasks(data)
    if not deviation_tasks:
        return None
    raw_ct = data.get("completed_tasks")
    ct = set(map(str, raw_ct)) if isinstance(raw_ct, list) else set()
    hits = sorted(t for t in deviation_tasks if t in ct)
    if not hits:
        return None
    return (
        f"exit 0 但结果文件 success 携带验收偏差条目且对应任务出现在 "
        f"completed_tasks（{agent_type} 产物硬门）: {result_path} "
        f"偏差任务 {runner._format_gap_list(hits)}——偏差任务当轮 MUST NOT "
        f"勾选：把它移出 completed_tasks 并在 tasks.md 取消勾选，列入 "
        f"unfinished 申报走 partial；或按任务行内「以 X "
        f"{ACCEPTANCE_DEVIATION_ANNOTATION}」注解经规划层重出替代场景链后，"
        f"以替代场景链为验收基准达标再勾选（届时不再登记偏差条目）；无可达成"
        f"替代方式时走 unattainable 诚实退出"
    )


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
            f"{tasks_md_path(result_path.parent, spec_name)} "
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
    # completed_tasks 契约：每个任务 id 恰出现一次（code-review item
    # c4de694c2059）。重复条目此前经 set 去重静默放行，会原样流入后续
    # taskupdate 交叉核对与状态回写链路——按结构违规拒收。置于非法 id 检查
    # 之后，此处元素已全为合法 id 字符串。
    dupes = sorted({tid for tid in raw_ct if raw_ct.count(tid) > 1})
    if dupes:
        return (
            f"{TASK_GATE_ERROR_PREFIX} exit 0 但结果文件 completed_tasks 含重复条目"
            f"（每个任务 id 须恰出现一次，{agent_type} 产物硬门）: {result_path} "
            f"{runner._format_gap_list(dupes)}"
        )
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
    unfinished 或 unattainable）；completed ∩ unfinished 互斥、三集合并集
    == 全部数字任务 id。任一不满足返回失败归因（防 partial 成为绕过
    success 判据的缺口）。

    互斥范围说明（勿按「三集合全互斥」推理补拦）：completed ∩ unattainable
    由调用方 _check_impl_result_artifact 的 bogus 判定传递保证（unattainable
    ⊆ 未勾选、completed == 勾选）；unfinished ∩ unattainable 双申报则**有意
    放行**——unattainable 已豁免该任务的完成义务，双申报无门禁绕过后果，
    拒回只会把诚实申报者逼回原地重试烧预算
    （tests/test_honest_exit_convergence.py 的
    test_partial_unattainable_also_listed_in_unfinished_passes 显式固化
    该形态放行）。

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
            f"{TASK_GATE_ERROR_PREFIX} exit 0 但结果文件 partial 缺 completed_tasks/unfinished 数组"
            f"（{agent_type} 产物硬门）: {result_path}"
        )
    bad = runner._invalid_completed_ids(raw_ct) + runner._invalid_completed_ids(raw_un)
    if bad:
        return (
            f"{TASK_GATE_ERROR_PREFIX} exit 0 但结果文件 partial 清单含非法任务 id"
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
    """门禁干净通过时清零 task-gate 拒绝计数（改进①，防陈旧计数误降级）。

    走 state_machine 的原子计数原语（与 _bump_task_gate_rejections 对称，
    code-review item 7037da170e00）。归零用 ``reset_task_gate_rejections``
    单临界区原语（code-review item c08bc3db202d）：旧两段式
    ``read_one → bump(delta=-cur)`` 的读与写分持两把锁，其间并发 bump 会被
    -cur 补偿吞掉或留下过时正值（丢失更新）。失败记 WARNING（非静默）。
    """
    if runner.state_machine is None:
        return
    try:
        runner.state_machine.reset_task_gate_rejections(spec_name)
    except Exception as e:
        runner.logger.warning(
            "agent_runner",
            f"task-gate 拒绝计数清零失败 '{spec_name}'（不阻断）: {e}",
        )


# ── 收工自证 CLI（add-impl-selfcheck-model-probe 1.1）────────────────────────
# 把 daemon 侧收工硬门的生产校验体暴露为零网络 CLI：agent 在 run 内、写完
# .fenix-run-result.json 后即可自证形状合法性（dispositions 字符串数组等契约
# 陷阱在退出前发现并修复），不再依赖 daemon 侧打回整轮重派。
#
# 同源保证：校验调用的是本模块**同一批函数对象**（_check_artifact_json_file /
# _check_impl_result_artifact / _validate_code_review_report 等），非复制逻辑；
# daemon 侧硬门判定保持不变（本入口只加出口，不改判定）。


class _SelfcheckLoggerAdapter:
    """门族函数的 (channel, message) 双参 logger 约定 → 标准 logging 适配。

    门族函数按仓库自研 logger 的 ``logger.warning(channel, msg)`` 双参约定
    调用（_check_impl_code_review_artifact 门开关降级 / _register_task_gate_
    rejection 降级路径 / _bump_task_gate_rejections / _alert_task_gate_degraded
    / _clear_task_gate_rejections，其中 _alert_task_gate_degraded 用 debug）。
    标准 ``logging.Logger.warning`` 首参是 message、其余是 %s 参数——shim 若
    直接复用 ``_logger``，channel 会被当格式串、msg 当参数，args 非空时
    ``LogRecord.getMessage`` 抛「not all arguments converted」且消息经
    handleError 丢失（code-review item c9827668d555）。本薄适配对齐门面
    logger 签名；未列方法经 ``__getattr__`` 透传标准 logger（单参约定）。
    """

    def __init__(self, logger):
        self._logger = logger

    def warning(self, channel, msg, *args, **kwargs):
        self._logger.warning("%s: %s", channel, msg, *args, **kwargs)

    def debug(self, channel, msg, *args, **kwargs):
        self._logger.debug("%s: %s", channel, msg, *args, **kwargs)

    def __getattr__(self, name):
        if name == "_logger":
            raise AttributeError(name)
        return getattr(self._logger, name)


class _SelfcheckShim:
    """自检 CLI 的门面依赖替身（D2b 规则 1 的离线等价物）。

    ``_check_impl_result_artifact`` 等门族函数首参为 ``runner``，经实例访问
    门面依赖（``_IMPL_RESULT_STATUSES`` / 兄弟门函数 / ``_format_gap_list``）。
    自检 CLI 无 AgentRunner 实例（零 daemon 依赖），本替身把这些依赖**委托回
    本模块的同一批函数对象**——不复制任何判定逻辑。

    有意缺失（与生产语义对齐的 fail-open/skip）：
    - ``state_machine = None``：task-gate 跨轮拒绝计数在无状态机时按 0 处理
      （``_bump_task_gate_rejections`` 的既有 fail-open 分支），不降级放行；
    - ``_check_taskupdate_crosscheck`` 恒 None：TaskCreate/TaskUpdate 覆盖
      核对依赖本轮 run 转录（init.tools 能力探测），自检进程无该载体——与
      生产 D4「工具不可用 → 跳过该项核对并放行」同语义；
    - ``_check_quality_gates_soft`` 恒 None：quality-gates.json 宽松对账是
      纯 WARNING 审计、零拦截，不产生自证违规（也避免 logging 通道噪音混入
      stderr 明细）。
    """

    def __init__(self, project_root):
        self.project_root = project_root
        self.state_machine = None
        # logger 走 (channel, msg) 双参适配（code-review item c9827668d555）：
        # 门族函数按仓库自研 logger 双参约定调用 runner.logger，直接复用标准
        # _logger 会签名失配（见 _SelfcheckLoggerAdapter docstring）。
        self.logger = _SelfcheckLoggerAdapter(_logger)
        # 惰性导入（函数运行期，非模块加载期——本模块 MUST NOT import runner）：
        # 白名单以 AgentRunner 类属性为单源，禁止在本处另写一份字面量。
        from core.agent_runner.runner import AgentRunner

        self._IMPL_RESULT_STATUSES = AgentRunner._IMPL_RESULT_STATUSES

    # ── 兄弟门函数/纯助手：委托回本模块同一函数对象（D2b 规则 2）──
    _check_artifact_json_file = staticmethod(_check_artifact_json_file)
    _format_gap_list = staticmethod(_format_gap_list)
    _invalid_completed_ids = staticmethod(_invalid_completed_ids)

    def _check_success_completion(self, spec_name, result_path, data, all_ids, checked_ids):
        return _check_success_completion(
            self, spec_name, result_path, data, all_ids, checked_ids)

    def _check_partial_consistency(self, spec_name, result_path, data, all_ids,
                                   checked_ids, unattainable_ids=None):
        return _check_partial_consistency(
            self, spec_name, result_path, data, all_ids, checked_ids,
            unattainable_ids=unattainable_ids,
        )

    def _check_taskupdate_crosscheck(self, spec_name, checked_ids):
        return None  # 见类 docstring：无 run 转录载体，fail-open 跳过

    def _check_quality_gates_soft(self, spec_name, wt_path):
        return None  # 见类 docstring：纯 WARNING 审计，不进自证明细

    def _check_host_changes_summary_soft(self, spec_name, data, result_path,
                                         wt_path):
        return None  # 见类 docstring：纯 WARNING 审计，不进自证明细


def _selfcheck_dispositions_violations(data: dict, wt_path: Path, spec_name: str) -> list:
    """收尾审查处置形状自证（ocr join 硬门同源判据，add-impl-selfcheck-model-probe）。

    add-impl-ocr-parallel-lane 起 dispositions 的权威判定点在框架侧 join
    （core/pm_engine/dispatch/queue.py 的 ``Dispatcher._ocr_join_gate``，
    自持 _read_ocr_artifact + 指纹校验的完整判定；
    ``_check_impl_code_review_artifact`` 现已无生产调用点，见
    _check_impl_result_artifact 内注释），不在产物硬门内——但形状陷阱
    （字符串数组）正是打回整轮的重烧源，自检必须覆盖：

    - worktree 内存在 ``.fenix/verify-progress/<spec>/code-review.json`` →
      用产物硬门同一校验体 ``_validate_code_review_report`` 全量校验；
    - 报告缺席但结果文件自带 ``code_review`` 段（含 dispositions 别名键）→
      仅校验条目形状（``_validate_disposition_entries`` 同一函数对象）；
      条数对账需 findings 清单（在 code-review.json 内），报告缺席时无对账
      义务，跳过条数检查与生产「门关闭/报告缺失」语义一致；
    - 两者皆无 → 无处置义务，零违规。
    """
    violations: list = []
    code_review = data.get("code_review")
    report_rel = f".fenix/verify-progress/{spec_name}/code-review.json"
    report_path = Path(wt_path) / ".fenix" / "verify-progress" / spec_name / "code-review.json"
    if spec_name and report_path.is_file():
        try:
            cr_data = json.loads(report_path.read_text(encoding="utf-8"))
        # [fenix-ignore:ab11f8ece35d] except 元组已含 RecursionError（超深嵌套
        # 报告按「收尾审查报告无法解析」违规行 fail-closed，同
        # _check_artifact_json_file 口径），所指漏洞不存在
        except (OSError, ValueError, UnicodeDecodeError, RecursionError) as e:
            # RecursionError：超深嵌套 JSON 会让 json.loads 抛 RecursionError
            # （非 ValueError 子类，同 _check_artifact_json_file 口径）——
            # fail-closed 归因为「收尾审查报告无法解析」违规行，不逸出自检 CLI。
            return [
                f"收尾审查报告无法解析（impl-code-review-gate 自证）: "
                f"{report_rel} ({e})"
            ]
        err = _validate_code_review_report(cr_data, data, report_rel)
        if err is not None:
            violations.append(err)
        return violations
    if isinstance(code_review, dict):
        cr_dispositions = None
        # 显式记录命中别名键（同 _validate_code_review_report 的 _alias_hit），
        # 违规文案不依赖循环变量泄漏取值（别名元组为空/循环重构时防 NameError
        # 或错键名）。
        _alias_hit = "dispositions"
        for alias in _DISPOSITION_KEY_ALIASES:
            val = code_review.get(alias)
            if val is not None:
                cr_dispositions = val
                _alias_hit = alias
                break
        if cr_dispositions is not None:
            if not isinstance(cr_dispositions, list):
                violations.append(
                    f"code_review.{_alias_hit} 非数组（逐条处置 MUST 为对象数组，"
                    f"每项含 disposition 键）（impl-code-review-gate 自证）: "
                    f"{report_rel}"
                )
            else:
                err = _validate_disposition_entries(cr_dispositions, report_rel)
                if err is not None:
                    violations.append(err)
    return violations


_SELFCHECK_USAGE = (
    "用法: python3 -m core.agent_runner.result_gate --selfcheck <结果文件路径>\n"
    "对 .fenix-run-result.json 执行与 daemon 侧收工硬门同源的自证校验\n"
    "（worktree 内可跑、零网络、零 daemon 依赖；只读目标文件，零副作用）。\n"
    "退出码: 0=PASS, 1=FAIL（违规明细逐条打 stderr）, 2=用法错误。\n"
)


def run_selfcheck(result_file) -> int:
    """结果文件收工自证（退出码 0=PASS / 1=FAIL）。

    复用生产校验体（同一函数对象，非复制逻辑），对指定结果文件依次执行：

    1. 基础结构校验（``_check_artifact_json_file``：存在/非空/可解析 JSON，
       ``run_started_at=None``——自检无「本轮启动」概念，不做 mtime 新鲜度判）；
    2. 实现者产物硬门全量判据（``_check_impl_result_artifact``：status 白名单 /
       tasks.md 勾选对账 / completed_tasks·unfinished·unattainable 一致性）；
    3. 收尾审查处置形状（``_selfcheck_dispositions_violations``，join 同源）。

    违规明细逐条输出到 stderr（每行一条，含字段路径与期望形态）；PASS 时
    stdout 打一行确认、stderr 保持干净。除读取目标文件、worktree 内 tasks.md
    与 code-review.json 外无任何文件写入或网络请求。
    """
    path = Path(result_file)
    violations: list = []
    err, data = _check_artifact_json_file(path, "implementer", None)
    if err is not None:
        violations.append(err)
    elif not isinstance(data, dict):
        violations.append(f"结果文件顶层非对象（implementer 产物硬门）: {path}")
    else:
        spec_name = data.get("spec")
        if not isinstance(spec_name, str) or not spec_name.strip():
            violations.append(
                f"结果文件缺非空 spec 字段（implementer 产物硬门，自检无法定位 "
                f"tasks.md 对账）: {path}"
            )
            spec_name = ""
        wt_path = path.resolve().parent
        gate_err = _check_impl_result_artifact(
            _SelfcheckShim(wt_path), spec_name, None, wt_path)
        if gate_err is not None:
            violations.append(gate_err)
        violations.extend(
            _selfcheck_dispositions_violations(data, wt_path, spec_name))
    if violations:
        for v in violations:
            sys.stderr.write(f"selfcheck FAIL: {v}\n")
        sys.stderr.write(
            f"selfcheck: {len(violations)} 条违规——按上方明细修复后重跑至退出码 0"
            f"方可收工\n")
        return 1
    sys.stdout.write(f"selfcheck PASS: {path}\n")
    return 0


def main(argv=None) -> int:
    """CLI 入口（``python3 -m core.agent_runner.result_gate --selfcheck <路径>``）。

    参数缺失/文件不存在 → 输出用法并以非零码（2）退出。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] != "--selfcheck" or not argv[1].strip():
        sys.stderr.write(_SELFCHECK_USAGE)
        return 2
    if not Path(argv[1]).is_file():
        sys.stderr.write(f"selfcheck: 结果文件不存在: {argv[1]}\n")
        sys.stderr.write(_SELFCHECK_USAGE)
        return 2
    return run_selfcheck(argv[1])


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
