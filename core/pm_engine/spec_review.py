"""spec_review.py — SPEC 方案评审门禁的核心逻辑。

实现评审 run 的派发、结果消费、写入边界校验、故障重试与人工恢复入口。
"""

import hashlib
import json
import logging
import math
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, Optional, Tuple

from core.state_machine import (
    SpecStatus,
    FROZEN_FIELD,
    REVIEW_ATTEMPTS_FREEZE_ERROR_PREFIX,
    REVIEW_REJECTED_FREEZE_ERROR_PREFIX,
    _NullLogger,
)
from core.agent_runner.runner import AgentRunner
from core.agent_runner.prompt_builder import (
    spec_review_result_path,
    SPEC_REVIEW_RESULT_STATUS_WHITELIST,
)

_logger = logging.getLogger("fenixd.pm_engine.spec_review")

# 评审尝试上限（首次 + 最多 2 次重试，常量名自解释）
MAX_REVIEW_ATTEMPTS = 3

# content（评审质量）失败重派短退避秒数（evo-fix-spec-review-infra-attribution-
# bridge 3.1）：content 失败的重派原为秒级甚至毫秒级连发（实测失败→重派仅
# 0.05s），批量窗口内同一质量缺陷会瞬间烧光 3 次尝试预算。按
# dispatch/backoff.py _schedule_recovery_timer 范式加一档秒级短延迟；
# 可配 review.content_retry_delay_seconds（0 = 关闭退避立即重派，测试/部署
# 逃生口；负值/非有限浮点回退缺省）。infra 分支不适用——其节奏由熔断冷却
# 负责（两类互不干扰，spec「评审质量失败重派短退避」Requirement）。
REVIEW_CONTENT_RETRY_BACKOFF_SECONDS = 2.0
REVIEW_CONTENT_RETRY_DELAY_CONFIG_KEY = "review.content_retry_delay_seconds"

# 评审否决自动复评上限（2026-09-15 评审误判事故）：`blocking` 由 LLM 自分类，
# 存在把「文档内部矛盾/遗漏」误判为「方向不成立」的残差。首次 rejected 不直接
# 冻结转人工，而是回 reviewing 自动复评；连续达该次数仍 rejected 才认定方向
# 确不成立、冻结转人工。取 2 = 「初次否决 + 1 次复评确认」。
MAX_REJECT_REDO = 2

# 审核收尾回退守卫（evo-spec-concurrency-flight-guard D1）：评审收口
# （approved/repaired → 回退 ready）前重读 spec 当前 status，属这三类说明存在
# 在飞实现 run 或在实现后段（implementer 已派发/合并已推进）——跳过回退，
# 仅清 reviewer_run 锚点 + 落 `_review_skipped_result` 审计侧车。
IN_FLIGHT_IMPL_STATES = ("implementing", "implemented", "testing")

# 写入边界校验：SPEC 目录相对路径前缀
SPEC_CHANGES_PREFIX = "spec/changes/"


def _parse_porcelain_path(line: str) -> Optional[str]:
    """从 `git status --porcelain` 输出行提取文件路径。

    porcelain 固定格式为「两状态符 + 空格 + 原文路径」，路径从 line[3:] 起
    原样截取（可含空格）；不能按空白 split 取 parts[1]——含空格的路径会被
    截断失真（code-review item 27ad5869fb3f）。重命名/拷贝条目（R/C 状态）
    形如「XY orig -> new」，按箭头分段取新路径。行过短（无路径）返回 None。
    """
    if len(line) < 4:
        return None
    path = line[3:]
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path or None

# ── infra 失败指纹（evo-run-failure-classification-circuitbreaker D1）──────
# 评审 API 批量失败（403 网关拒绝 / 402 余额不足 / 429 限流 / quota/budget 耗尽 /
# rate limit / provider 侧熔断信号 / CLI 进程级崩溃）同属 infra——链路级问题，
# 非 spec 内容问题。指纹匹配大小写不敏感；"Exit code: 1" 不得一律判 infra
# （评审器内容失败同样 exit 1），仅当退出码非 0/1（进程级崩溃）才归 infra。
_INFRA_FINGERPRINTS = (
    "quota",
    "budget",
    "余额",
    "insufficient balance",
    "rate limit",
    "provider circuit open",
    "provider chain exhausted",
    "model_chain_preflight_failed",
)
# 监督超时短语（code-review item 4b0176280b0a）：评审 run 被监督机制因超时或被判
# 停滞而杀时 reason 含以下短语——这类失败是「run 没跑完」而非 provider 侧链路故障，
# MUST NOT 判 infra。尤其 "extension budget exhausted" 含裸指纹 "budget"，会被
# _classify_run_failure 误判 infra → _handle_review_failure 清锚点且不递增
# _review_attempts，再死循环零成本复评、MAX_REVIEW_ATTEMPTS 冻结兜底失效。清单与
# budget.py:_is_exemptable_reason 的「不可豁免」分支逐一对应（该处同样把这几个
# 短语明确划为「监督超时、不可豁免」的非 infra 类），两处口径对齐。
_SUPERVISION_TIMEOUT_PHRASES = (
    "extension budget exhausted",
    "run timeout reached",
    "absolute_max_seconds cap reached",
    "stagnant",
)
# 数字类指纹（402/403/429）不做裸子串匹配（code-review item b4ce03fd99c4）：
# 失败原因文本任意位置出现这些数字（如路径 …-1403.md、行号 "line 4290"、
# exit code 14029）都会被误判 infra——不递增 _review_attempts、计入熔断计数，
# 真实 content 失败的重试预算被悄悄跳过。收紧为「两侧为分隔符」边界：
# 仅当数字串不邻接 ASCII 字母/数字/连字符（"HTTP 429"、"Error 403"、
# "402 余额不足"、"错误403"）才归 infra——封死 spec 名拼入 reason 的
# 连字符形态（fix-429-backoff / add-403-retry）误判穿透
# （code-review item 80d45b2a5087）。不用 \w/\b——二者视 CJK 为 word
# 字符，会漏掉中文紧邻数字的真实指纹，故字符类只收 ASCII 字母数字与连字符。
_NUMERIC_INFRA_RE = re.compile(r"(?<![0-9A-Za-z-])(?:402|403|429)(?![0-9A-Za-z-])")
# 词形指纹（quota/budget/余额/rate limit 等）同样不做裸子串匹配（code-review
# item 489d6071b236）：失败原因文本常内嵌 spec 名或产物路径（如
# .fenix/spec-review/add-budget-widget/...、"结果文件读取失败: <spec 目录前缀>…"），
# spec 名含 budget/quota 词根的 content 类失败会被裸子串误判 infra——不递增
# _review_attempts、只清锚点，重试预算被跳过并持续计入熔断。复用
# _NUMERIC_INFRA_RE 的分隔符边界思路：字符类只收 ASCII 字母数字与连字符
# （不用 \w/\b——二者视 CJK 为 word 字符，"402 余额不足" 这类中文紧邻形态
# 会漏判；数字串形态仍由 _NUMERIC_INFRA_RE 兜底命中）。"rate limit exceeded"、
# "quota exceeded" 等正常 infra 文案两侧为空格/标点，边界判定不受影响。
_INFRA_FINGERPRINT_RE = re.compile(
    r"(?<![0-9A-Za-z-])(?:"
    + "|".join(re.escape(fp) for fp in _INFRA_FINGERPRINTS)
    + r")(?![0-9A-Za-z-])"
)
# CLI 进程级崩溃：error 含 "Exit code: <N>" 且 N 非 0/1
_CLI_EXIT_CODE_RE = re.compile(r"Exit code:\s*(-?\d+)")

# 结构化归因的 infra 状态码集（evo-fix-spec-review-infra-attribution-bridge
# 1.3）：与 _NUMERIC_INFRA_RE 的数字词表同源（402 余额不足 / 403 网关拒绝 /
# 429 限流）。结构化字段（AgentRunResult.api_error_status）由 runner 层从
# result 事件挂载、随异常回填，不经 stderr 降噪——是降噪后文本指纹失效时
# 唯一可靠的供给瞬态归因来源；判定优先于文本词表（spec「优先消费结构化
# 归因，文本分类作为回退」）。
_STRUCTURED_INFRA_API_STATUS = frozenset((402, 403, 429))


# spec-review 打回理由结构化分类（add-pipeline-throughput-governance 5.1/5.2）
# 枚举固化：format=草稿结构/契约段/键名等可机械修复问题；substantive=方案、
# 场景覆盖、正确性等实质问题。缺字段/非法值按 unknown 兼容（存量结果零迁移、
# 不因缺该字段被判非法）；通过（approved/repaired）结果不要求该字段。
REJECTION_CLASS_WHITELIST = ("format", "substantive")


def normalize_rejection_class(raw) -> str:
    """rejection_class 归一化：合法枚举原样返回；缺失/非法值按 ``unknown`` 兼容。

    读侧 fail-open：历史打回结果无该字段时解析不失败、不告警升级，统计归入
    unknown 桶（add-pipeline-throughput-governance 5.2 存量零迁移）。
    """
    if not isinstance(raw, str):
        return "unknown"
    value = raw.strip().lower()
    return value if value in REJECTION_CLASS_WHITELIST else "unknown"


def rejection_class_stats(project_root) -> dict:
    """按 ``rejection_class`` 分桶统计打回结果（读侧数据层查询函数）。

    扫描 ``.fenix/spec-review/*/.fenix-run-result.json`` 中 ``status=rejected``
    的结果文件，按归一化分类分桶（format/substantive/unknown）。fail-open：
    单文件损坏跳过、MUST NOT 抛异常。返回形状两态（code-review item
    f2a745c96d9c）：目录缺失返回空 dict（无键）；目录存在恒为固定三键
    {format, substantive, unknown} 桶 dict（计数可为零）——调用方按桶键迭代
    或取占比时 MUST 同时兼容两形态。``format`` 桶占比用于评估「机械可预防
    打回」规模。
    """
    buckets = {"format": 0, "substantive": 0, "unknown": 0}
    base = Path(project_root) / ".fenix" / "spec-review"
    if not base.is_dir():
        return {}
    for path in base.glob("*/.fenix-run-result.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict) or data.get("status") != "rejected":
            continue
        buckets[normalize_rejection_class(data.get("rejection_class"))] += 1
    return buckets


def _runner_result_gate(agent_runner):
    """评审结果硬门入口解析（code-review item 9e1197a61f51 契约化）。

    真实 AgentRunner 走公开别名 ``check_result_artifact``（显式契约：runner
    侧重构签名/语义时本文件调用点可被静态检查覆盖，不再依赖下划线私有成员
    构成的事实契约；别名经 ``self.<私有名>`` 委派，实例打桩继续生效）。测试
    替身（MagicMock 属性自动生成、手写 stub 按旧私有名打桩，无法甄别公开
    别名是否真实存在）回退私有名——缺失时 AttributeError 与既有形态一致。
    """
    if isinstance(agent_runner, AgentRunner):
        return agent_runner.check_result_artifact
    # [fenix-ignore:a75a03b14717] 公开别名打桩尚未全仓铺开（多处手写 stub/MagicMock 仍按私有名打桩），删回退分支会破坏既有 stub 测试且迁移超出本文件可改边界
    return agent_runner._check_agent_result_artifact


def _runner_salvage_hook(agent_runner):
    """评审结果捞回入口解析（code-review item 9e1197a61f51 契约化）。

    分流口径同 ``_runner_result_gate``；回退分支保留 ``getattr(..., None)``
    容忍（CLI 形态 agent_runner=None 与不及格替身均返回 None，由调用方
    ``callable`` 判定跳过——沿用旧口径不改变行为）。
    """
    if isinstance(agent_runner, AgentRunner):
        return agent_runner.salvage_spec_review_result
    return getattr(agent_runner, "_salvage_spec_review_result", None)


class SpecReviewManager:
    """评审管理器：负责评审 run 的派发、结果消费、边界校验、重试与恢复。"""

    def __init__(
        self,
        project_root: Path,
        state_machine,
        agent_runner: AgentRunner,
        pm_engine,
        config: dict,
        logger=None,
    ):
        self.project_root = project_root
        self.state_machine = state_machine
        self.agent_runner = agent_runner
        self.pm_engine = pm_engine
        self.config = config
        # logger 缺省时兜底 _NullLogger（同 state_machine/verify_engine 先例）：
        # 本类日志调用均为 (component, message) 两位置参数形态，若兜底 stdlib
        # Logger，首参会被当格式串（"spec_review" % msg）致日志错乱或被
        # handleError 吞掉——模块级 _logger 仅供本文件 stdlib %s 风格调用。
        self.logger = logger if logger is not None else _NullLogger()

    # ── 评审派发 ────────────────────────────────────────────────

    def dispatch_review(self, spec_name: str) -> bool:
        """为指定 SPEC 派发一次评审 run，并在其收工后机械收口。

        本方法是评审的**唯一派发收口点**，「锚点落盘 → 快照 → 阻塞执行 → 消费结果」
        四步全在此闭合（评审门禁接线修复）：

        - **锚点（``reviewer_run``）在 run 启动之前写入**。``run_spec_review`` 为同步
          阻塞（分钟级）；若沿用「run 收工后才写锚点」的旧序，阻塞期间第二条派发通道
          （event_bus 轮询与 ``_on_spec_drafted`` 直调各一）读到锚点为空会再派一次，
          两个评审 Agent 并发改写同一 SPEC 目录（并发写者事故）。
        - **run 收工后立即 ``consume_review_result`` 收口**（approved/repaired → ready、
          rejected → blocked）。此前该消费点在全部生产路径上零调用——评审结果写盘后
          无人读，SPEC 永久停在 reviewing，随 daemon 重启被反复重派。

        Returns: True 表示评审 run 已执行收工；False 表示被拒或 run 执行失败。
        """
        # 链路级熔断短路（evo-run-failure-classification-circuitbreaker D2）：
        # spec-review 链路熔断窗口内直接返回不派发；冷却到期自动恢复重试。
        breaker = getattr(self.pm_engine, "infra_breaker", None)
        if breaker is not None:
            cond = breaker.condition("spec-review")
            if cond == "broken":
                remaining = breaker.cooldown_remaining("spec-review")
                self.logger.info(
                    "spec_review", f"评审派发熔断短路: {spec_name}，冷却剩余 {remaining}s"
                )
                return False
            if cond == "recovered":
                # 冷却到期自动恢复：落恢复 SIGNAL 记录（D3）
                self.pm_engine._emit_infra_breaker_event(
                    "recovered", spec_name, "", breaker.get_state("spec-review")
                )
        # 防重派（fix-spec-review-blocking-dispatch 2.4 改口径）：
        # ① ``_active_reviews`` 命中 → 拒绝：覆盖「条目已出队、锚点尚未落盘」
        #    的窗口。异步化后本入口只由 worker（``_run_spec_review_worker``）
        #    调用——worker 在调用前已释放本次登记（释放时点 ≤ 锚点落盘，
        #    design D4 重入安全性），故本判据主要防御其它并发直调通道。
        # ② 锚点非空 → MUST 经 ``reviewer_in_flight`` 取**在飞结论**：
        #    ``in_flight == True`` 拒派；仅 ``reason == "stale"``（陈旧锚点，
        #    run 已终态）才清锚点后继续。MUST NOT 按「锚点非空」直接自清——
        #    ``_should_defer_for_reviewer`` 的判定异常分支为 fail-open
        #    ``(False, None)``，直接自清会在评审仍在跑时放行并发派发。
        #    判定异常 fail-closed 拒派（记 WARNING，recovery 兜底）——评审
        #    自身派发宁可不发，与实现派发侧的 fail-open 取相反保守方向。
        # 重入保护：content 失败重试入队（``_handle_review_failure`` 清锚点后
        # 重新入队 → 新 worker）进入本入口时 ``_active_reviews`` 已被
        # ``_run_spec_review_worker`` 释放、锚点已被收口路径清除——两者皆空
        # 放行，评审不被自己挡住（spec-review-recovery spec Scenario「续
        # attempt 不被自身在飞登记否决」）。
        pm_engine = self.pm_engine
        if pm_engine is not None and pm_engine.is_review_in_flight(spec_name):
            self.logger.info("spec_review", f"评审条目已在飞（队列/未收口）: {spec_name}")
            return False
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            self.logger.warning("spec_review", f"SPEC 不存在: {spec_name}")
            return False
        reviewer_run = entry.get("reviewer_run")
        if reviewer_run:
            try:
                in_flight, reason = self.agent_runner.reviewer_in_flight(
                    spec_name, reviewer_run
                )
            except Exception as e:
                # 判定异常 fail-closed 拒派（不自行清锚点）
                self.logger.warning(
                    "spec_review",
                    f"在飞评审判定异常 '{spec_name}'（fail-closed 拒派）: {e}",
                )
                return False
            if in_flight:
                self.logger.info("spec_review", f"已有在飞评审 run: {spec_name}")
                return False
            if reason == "stale":
                self.logger.warning(
                    "spec_review",
                    f"陈旧评审锚点（run 已终态）清理后继续派发: "
                    f"{spec_name} run={reviewer_run}",
                )
                self.state_machine.update_spec(spec_name, {"reviewer_run": None})
        # 检查评审尝试次数
        try:
            attempts = int(entry.get("_review_attempts", 0) or 0)
        except (TypeError, ValueError):
            attempts = 0
        if attempts >= MAX_REVIEW_ATTEMPTS:
            # 耗尽即转冻结转人工（fix-blocked-freeze-classification 2.2）：
            # 改走 freeze_for_human「冻结 + 告警」成对入口——admin 对
            # 「评审器连续失败」无杠杆（模型链/配置问题）；冻结后
            # admin_monitor 的 blocked_stuck 豁免生效。
            # 评审专用冻结前缀（evo-fix-spec-review-infra-attribution-bridge
            # 4.1）：自动冻结不自称「用户指令冻结」；「原状态 reviewing」子串
            # 与 spec-review-incomplete 标记按红线保留（解冻还原 + 既有契约）。
            error_msg = (
                f"{REVIEW_ATTEMPTS_FREEZE_ERROR_PREFIX}原状态 reviewing · "
                f"spec-review-incomplete: 评审尝试已达上限"
                f"（{MAX_REVIEW_ATTEMPTS}）"
            )
            self.state_machine.freeze_for_human(
                spec_name,
                error=error_msg,
                signal_type="spec-review-incomplete",
                severity="major",
                description=(
                    f"'{spec_name}' 评审尝试已达上限（{MAX_REVIEW_ATTEMPTS}），"
                    "评审器连续失败，需人工排查（模型链/配置问题）"
                ),
                evidence=(
                    f"spec={spec_name}; run_id={entry.get('reviewer_run') or '无'}; "
                    f"attempts={MAX_REVIEW_ATTEMPTS}"
                ),
                recommended_action=(
                    "人工排查评审链路（模型链/配置/结果硬门）；排查后经 "
                    "dashboard/CLI 解冻——解冻恢复原状态 reviewing，daemon "
                    "自动重派评审；或直接撤销该 spec"
                ),
                # pm_engine None 守卫（code-review item a74a3c85dec1）：CLI 与
                # Dashboard 均以 SpecReviewManager(proot, sm, None, None, {},
                # logger) 构造（与 :480/:1182 先例同款），缺守卫会在冻结前取属性
                # 抛 AttributeError，spec 停在 reviewing 既不冻结也不告警。
                # freeze_for_human 对 None 回调按静默冻结处理（记 ERROR 审计）。
                alert_callback=(
                    self.pm_engine._send_human_escalation_alert
                    if self.pm_engine is not None
                    else None
                ),
                extra_updates={
                    "reviewer_run": None,
                    "_review_attempts": 0,
                    # 与否决冻结站点及四处通过收口对齐清零否决计数（code-review
                    # item 10592411f0b1）：冻结前可能已记录 rejected 次数，陈旧
                    # 计数会使解冻重走评审时首次否决即达 MAX_REJECT_REDO、跳过
                    # 「初次否决 + 复评确认」的有界自动复评直接冻结转人工。
                    # _review_rejection_class 按既有清零口径保留作最后打回分类
                    # 留痕。
                    "_review_rejections": 0,
                },
            )
            return False

        # ① 锚点先落盘：预生成 run_id，保证 STATE 里的 reviewer_run 与实际 run 一致
        # 随机中缀（code-review item 08fa550ac034）：秒级时间戳在 content 失败
        # 重派（review.content_retry_delay_seconds=0 即立即入队）同秒收口再派发
        # 时会生成与上一轮逐字相同的 run_id，下游以整串 run_id 作锚点/salvage/
        # 在飞关联键，同 id 复用会把上一轮终态 run 的转录/存活状态误关联到本轮。
        # 随机段 MUST 放在 epoch 尾段**之前**：_artifact_landed_valid 的回落
        # 锚点解析按 ``rsplit("-", 1)[-1].isdigit()`` 取尾段秒级 epoch（见下方
        # :1113），尾段若被非数字后缀占据会让解析静默失效、产物 mtime 新鲜度
        # 校验被跳过。
        run_id = f"spec-review-{spec_name}-{uuid.uuid4().hex[:6]}-{int(time.time())}"
        self.state_machine.update_spec(spec_name, {"reviewer_run": run_id})

        # ② 派发前快照（写入边界校验的基线）
        snapshot = self._take_snapshot(spec_name)
        snapshot_dir = self.project_root / ".fenix" / "spec-review" / spec_name
        snapshot_path = snapshot_dir / "snapshot.json"
        try:
            # mkdir 同入 try（code-review item 26df83a3df5c）：.fenix/spec-review
            # 不可写（磁盘满/权限）时 OSError 与下方快照写入同口径 WARNING 降级，
            # 不逃出本方法留下「锚点已落盘、run 未派发」的残余（派发异常须收口
            # 锚点、不得留残余的不变量，见下方 ③ 的注释自述）。
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            # 原子写（tempfile + os.replace，同 engine._write_impl_result_snapshot
            # 手法，code-review item f851cefd6aa4）：快照是写入边界校验（SPEC 目录
            # 删除比对）的唯一基线，旧实现直接 write_text，进程中途崩溃/磁盘满会留
            # 下截断 JSON——下游 _check_write_boundary 读失败仅 WARNING 降级、本轮
            # 删除检测静默失效。
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".snapshot.{spec_name}.",
                suffix=".tmp",
                dir=str(snapshot_dir),
            )
            tmp_path = Path(tmp_name)
            # fdopen 失败路径显式接管（同 scenarios.write_scenarios_array /
            # judge_files.save_attribution 的 cbb57806fbfd 口径，code-review item
            # 8d3d45a9b9ab）：with 的 close 只在 fdopen 成功后才生效，fdopen 自身
            # 抛错（fd 非法等罕见路径）时裸 fd 无人关闭，长驻 daemon 进程下泄漏
            # 累积——f 为 None 时兜底 os.close 并吞 OSError。
            f = None
            try:
                try:
                    f = os.fdopen(fd, "w", encoding="utf-8")
                    json.dump(snapshot, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    if f is not None:
                        f.close()
                    else:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                os.replace(str(tmp_path), str(snapshot_path))
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
        except OSError as e:
            self.logger.warning("spec_review", f"快照保存失败: {spec_name}: {e}")

        # ③ 阻塞执行评审 run（正常收工或异常后返回）
        attempt_started_at = time.time()
        result = None  # 异常路径下不绑定（修复验证轮 BUG：UnboundLocalError）
        try:
            result = self.agent_runner.run_spec_review(spec_name, run_id=run_id)
            run_ok = bool(getattr(result, "success", False))
            run_err = getattr(result, "error", None)
        except Exception as e:  # noqa: BLE001 — 派发异常须收口锚点，不得留残余
            run_ok, run_err = False, str(e)
        if not run_ok:
            # evo-add-review-failure-attribution 1.3：失败行归因括注——形态对齐
            # code-fix 车道（maintenance_runs.py 括注结构与 stderr_tail 位置），
            # 键名用 api_error_status 而非 code-fix 的 api_timeout（评审车道无
            # salvage 语义）。素材读失败结果的结构化字段（runner 桥接 1.1 从
            # 异常回填）；result 为 None 的异常子路径（run_spec_review 抛异常，
            # 上方 429-430）无结构化字段可读，三元全空整体省略不添噪。
            # 属性读回按严格形态校验（与下方 frozen_terminated 的 `is True`
            # 同款纪律）：MagicMock 等替身结果在属性访问时自动生成 truthy
            # 子对象，非预期形态一律按缺省处理，防替身 repr 里的十六进制
            # 地址段被误当归因。
            _api_err = getattr(result, "api_error_status", None)
            if isinstance(_api_err, bool) or not isinstance(_api_err, (int, str)):
                _api_err = None
            _exit_code = getattr(result, "exit_code", None)
            if isinstance(_exit_code, bool) or not isinstance(_exit_code, int):
                _exit_code = None
            _stderr_tail = getattr(result, "stderr_tail", None)
            if not isinstance(_stderr_tail, str):
                _stderr_tail = ""
            _attribution = ""
            if _api_err is not None or _exit_code is not None or _stderr_tail:
                _attribution = (
                    f" [api_error_status={_api_err} exit_code={_exit_code}"
                    + (f" stderr_tail: {_stderr_tail}" if _stderr_tail else "")
                    + "]"
                )
            self.logger.error(
                "spec_review",
                f"评审 run 执行失败: {spec_name}: {run_err}{_attribution}",
            )

            # ③0 add-freeze-stop-inflight-agents 3.5：冻结终止在失败分类之前拦截——
            # 评审 run 因 spec 冻结被终止（frozen_terminated=True）：写
            # _frozen_hold 标记、保持 reviewing、不重派、不递增 _review_attempts、
            # 不触发熔断。MUST NOT 走 _classify_run_failure 的 content/infra
            # 分支（_INFRA_FINGERPRINTS 含 "rate limit" 等指纹、数字指纹
            # 402/403/429 同归 infra，评审 run 的限流/配额类失败重试会被误判
            # infra 而递增计数/熔断）。
            # 判定用 `is True` 严格等值（修复验证轮 BUG）：MagicMock 等替身
            # 在属性访问时自动生成 truthy 子对象，`if getattr(...)` 裸布尔会把
            # 非冻结的替身结果误判为冻结终止、跳过重试递增——生产结果
            # AgentRunResult.frozen_terminated 为显式 bool，严格等值判定不受影响。
            if result is not None and getattr(result, "frozen_terminated", False) is True:
                rev_err = getattr(result, "error", None) or run_err or ""
                frozen_err = (
                    f"评审 run 因 spec 冻结被终止（进度已保全，解冻后续做）"
                    f"{': ' + rev_err if rev_err else ''}"
                )
                self.state_machine.mark_frozen_hold(spec_name, frozen_err)
                self.logger.warning(
                    "spec_review",
                    f"评审 run 因 spec 冻结被终止 — hold-state '{spec_name}'"
                    f"（保持 reviewing，不重派）: {frozen_err}",
                )
                return False

            # ① 结果捞回（run 失败时尝试从转录代写落盘，避免白烧重试）
            # 公开契约解析（code-review item 9e1197a61f51）：不再直取 runner
            # 下划线私有成员形成隐式耦合。
            salvage = _runner_salvage_hook(self.agent_runner)
            if callable(salvage):
                try:
                    salvage(spec_name, run_id)
                except Exception as e:  # noqa: BLE001 — 捞回失败不得阻断判定
                    self.logger.warning("spec_review", f"结果捞回异常: {spec_name}: {e}")

            # ② 产物优先判定（D1）：产物已合法落盘 → 按产物消费，exit code 失败仅
            #    降级 warning 日志留痕，不递增 _review_attempts、不重派
            artifact_ok, artifact_data = self._artifact_landed_valid(
                spec_name, run_started_at=attempt_started_at
            )
            if artifact_ok:
                self.logger.warning(
                    "spec_review",
                    f"评审 run exit code 失败但产物已落盘，优先按产物消费"
                    f"（error={run_err}）: {spec_name}",
                )
                self.consume_review_result(spec_name, run_started_at=attempt_started_at)
                return True

            # ③ 产物不合法 → 走既有重试语义（attempt 递增）
            # 结构化归因随结果透传（evo-fix-spec-review-infra-attribution-bridge
            # 1.3）：run 失败结果可能携带 api_error_status / conn_error（runner
            # catch-all 从异常回填），分类层优先消费——异常路径 result=None 时
            # getattr 缺省 None，自然回退文本分类。
            self._handle_review_failure(
                spec_name, f"评审 run 执行失败: {run_err}{_attribution}",
                api_error_status=getattr(result, "api_error_status", None),
                conn_error=getattr(result, "conn_error", None),
            )
            return False
        self.logger.info("spec_review", f"评审 run 已收工: {spec_name} run_id={run_id}")
        # evo-add-review-failure-attribution 2.2（design D3）：评审 run 跑通即
        # 「链路证明可用」——成功收工路径清零连续 infra 失败计数，恢复
        # 「连续 ≥3 次」语义（陈旧跨周计数不再凭一次真实失败误触熔断）。
        # 落点在 consume 之前：run 跑通但产物不合法、走 content 类重试的分支
        # 同样经过此处——产物质量类失败不影响 infra 计数。熔断短路期间未
        # 实际派发的尝试（dispatch_review 入口 condition()=="broken" 直接
        # 返回）到不了本行，不计成功。
        _breaker = getattr(self.pm_engine, "infra_breaker", None)
        if _breaker is not None:
            _breaker.record_success("spec-review")

        # ③b 结果捞回（2026-09-15 事故修复）：评审 run 正常收工但从未调用 Write，
        # 把结果 JSON 当正文 fenced 代码块吐出。此处从转录代写落盘，避免整轮白烧
        # 重试。抽不出/已存在时不动作，交下方硬门按既有语义处理。
        salvage = _runner_salvage_hook(self.agent_runner)
        if callable(salvage):
            try:
                salvage(spec_name, run_id)
            except Exception as e:  # noqa: BLE001 — 捞回失败不得阻断收口
                self.logger.warning("spec_review", f"结果捞回异常: {spec_name}: {e}")

        # ④ 机械收口：结果缺失/越界由 _handle_review_failure 重试（保持既有语义）
        self.consume_review_result(spec_name, run_started_at=attempt_started_at)
        return True

    # ── 评审结果消费 ────────────────────────────────────────────

    def consume_review_result(self, spec_name: str, run_started_at: float | None = None) -> bool:
        """消费评审结果：校验结果硬门与写入边界，按 status 机械收口。

        Args:
            run_started_at: 本轮 attempt 的启动 epoch 秒（供结果文件 mtime 新鲜度
                校验，防上轮残留合法文件替本轮放行——fix-verdict-read-failclosed
                D2 同款）。None 时跳过新鲜度校验（直调/测试兼容）。

        Returns: True 表示消费成功（状态已变更），False 表示消费失败（需重试）。
        """
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            return False
        run_id = entry.get("reviewer_run")
        if not run_id:
            return False

        # 结果硬门校验（复用 _check_agent_result_artifact，spec-review 分支
        # 2026-09-15 已真接线：缺失/空/非白名单 status/陈旧 mtime 均由此拦截）
        # agent_runner 为 None 的 CLI 场景无硬门可复用：与 re_review/复评入队
        # 的 None 降级口径对齐，fail-closed 按硬门失败收口，不裸取属性抛
        # AttributeError 逃出评审收口（code-review item 79306fe3541e）；
        # allow_artifact=False 禁 artifact 回流——回流会递归回本方法再撞同一
        # None 守卫（4b9f59b8717f 同款防递归口径）。
        if self.agent_runner is None:
            err = "agent_runner 未注入（CLI 形态），结果硬门校验不可用"
            self.logger.warning("spec_review", f"结果硬门校验失败: {spec_name}: {err}")
            self._handle_review_failure(
                spec_name, err, allow_artifact=False, run_started_at=run_started_at
            )
            return False
        # 公开契约调用（code-review item 9e1197a61f51）：硬门入口经
        # _runner_result_gate 解析，不再直取 runner 下划线私有方法。
        err = _runner_result_gate(self.agent_runner)(
            spec_name, "spec-review", run_started_at=run_started_at
        )
        if err is not None:
            self.logger.warning("spec_review", f"结果硬门校验失败: {spec_name}: {err}")
            # allow_artifact=False（code-review item 6aca929144e4）：硬门失败本身
            # 已判定产物不可信，artifact 回流无增益；且分类器 _artifact_landed_valid
            # 与 runner 硬门 _check_agent_result_artifact 是两套独立实现，判据
            # 分歧时回流会走 artifact 分类 → 再次 consume → 再次硬门失败 → 无限
            # 递归（4b9f59b8717f 同形防递归口径，与上下两个失败分支同参形态）。
            # content_failure=True（code-review item 4a086cfce2e9）：硬门文案内嵌
            # 产物 status/解析器行号/产物路径（如 "status='429' 不在白名单"），
            # 不可按文本指纹判 infra——硬门失败是产物落盘/格式/取值问题，恒归
            # content 走重试预算。
            self._handle_review_failure(
                spec_name, err, allow_artifact=False, run_started_at=run_started_at,
                content_failure=True,
            )
            return False

        # 读取结果文件
        result_path = spec_review_result_path(self.project_root, spec_name)
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            # UnicodeDecodeError 非 OSError 子类（与本文件既有同族收口一致，
            # code-review item f818a54f3297）：非 UTF-8/多字节中截断的结果文件
            # 按读取失败走 _handle_review_failure 的分类/重试/冻结收口，不逃出
            # 本方法。
            self.logger.warning("spec_review", f"结果文件读取失败: {spec_name}: {e}")
            # content_failure=True（code-review item 4a086cfce2e9）：异常文案内嵌
            # JSON 解析器行号（"Expecting value: line 429 column 3"），行号随产物
            # 内容变化，不得按文本指纹判 infra。
            self._handle_review_failure(
                spec_name, f"结果文件读取失败: {e}", content_failure=True
            )
            return False

        # 写入边界校验。MUST NOT 再走 artifact 分类（code-review item 4b9f59b8717f）：
        # 边界错误（approved 带 repairs / repaired 无 repairs / repairs 路径非法）
        # 的产物在 `_artifact_landed_valid` 眼里是**合法**的（它只看文件可解析 +
        # status 白名单 + mtime + 快照一致性，不看 repairs 与 status 的一致性），
        # 故旧实现会判 artifact → 再次 consume_review_result → 再次命中同一（未被
        # 修正的）边界错误 → 无限递归，最终 RecursionError 被 worker 捕获后重新入队
        # 退化为活锁。显式 forbade_artifact + 透传 run_started_at（旧实现顺带跳过
        # mtime 新鲜度校验）。
        boundary_err = self._check_write_boundary(spec_name, data)
        if boundary_err:
            self.logger.warning("spec_review", f"写入边界校验失败: {spec_name}: {boundary_err}")
            self._handle_review_failure(
                spec_name, boundary_err, allow_artifact=False, run_started_at=run_started_at
            )
            return False

        # 按 status 机械收口
        status = data.get("status")
        if status not in SPEC_REVIEW_RESULT_STATUS_WHITELIST:
            self.logger.warning("spec_review", f"未知 status: {status}")
            # content_failure=True（code-review item 4a086cfce2e9）：status 回显值
            # 来自产物 JSON（不可信内容），"未知 status: 429" 形态会被数字指纹
            # 误判 infra——白名单外恒为产物取值问题，归 content。
            self._handle_review_failure(
                spec_name, f"未知 status: {status}", content_failure=True
            )
            return False

        if status in ("approved", "repaired"):
            # ── 审核收尾回退守卫（evo-spec-concurrency-flight-guard D1）──
            # 评审 run 收尾时，实现 run 可能已在飞（implementer 已派发 →
            # implementing；或已合并 → implemented/testing）。此刻把状态回退到
            # ready 会：① 产生「ready 态残留」→ 后续 merge 收尾 ready→implemented
            # 非法转移 ERROR（16:29:24Z 事故实证）；② ready 残留把同一 spec 拉进
            # 重复派发面。故本分支最前重读 spec 当前 status——属在飞实现状态则
            # 跳过回退，仅清 reviewer_run 锚点 + 落审计侧车。
            current = self.state_machine.read_one(spec_name) or {}
            cur = current.get("status")
            if cur in IN_FLIGHT_IMPL_STATES:
                self.logger.info(
                    "spec_review",
                    f"评审收尾遇在飞实现 run（status={cur}），跳过回退: {spec_name}",
                )
                # 清锚点（否则 reviewer_run 永久残留，与 D2 派发前校验合流后
                # 阻塞后续派发——本 SPEC 自造死锁）；审计侧车留痕本轮评审结论
                # 未被状态机消费（不写 error 字段，防事件总线自触发反馈环，D0）。
                self.state_machine.update_spec(
                    spec_name,
                    {
                        "reviewer_run": None,
                        "_review_attempts": 0,
                        # 本分支消费的同样是 approved/repaired 结果，与其他收口
                        # 分支对齐清零否决计数（code-review item 33fff9e737b3），
                        # 防陈旧计数使下轮 rejected 提前达上限冻结转人工。
                        "_review_rejections": 0,
                        "_review_skipped_result": f"{status}@result-path={result_path}",
                    },
                )
                # 早于下方 :300 的 _on_spec_ready 调用返回（MUST NOT 调用它：
                # 此刻无待派发实现 run，且若调用会被 D2 判定为在飞评审而顺延，
                # 语义重复）。
                return True
            # 转 ready 并触发实现调度（fix-observability-gaps 2.2：自动来源标注）
            # transition 返回值校验：读态守卫（:445）与 transition 之间存在
            # TOCTOU 窗口，并发写者可能已把 spec 推进到别的状态（或冻结剥离）
            # 致非法转移返回 False。失败时保留 reviewer_run 锚点与重试计数
            # （交由收口重试/审计），不继续清字段、不触发实现调度——与
            # re_review 的 transition 校验同款。
            success = self.state_machine.transition(
                spec_name, "ready",
                trigger_run_id=run_id, agent_type="spec-review", channel="auto",
            )
            if not success:
                self.logger.warning(
                    "spec_review",
                    f"评审通过但 transition 到 ready 失败，保留锚点待重试: {spec_name}",
                )
                return False
            self.state_machine.update_spec(
                spec_name,
                {
                    "reviewer_run": None,
                    "_review_attempts": 0,
                    # 通过即清零否决计数（含自动复评后通过）：下一次评审从零起算
                    "_review_rejections": 0,
                    "error": None,
                },
            )
            # 触发实现调度（pm_engine None 守卫，code-review item b110838b85e0）：
            # 与 rejected 分支（:541）及 responsible_release（:1139）同款——CLI 与
            # Dashboard 均以 SpecReviewManager(proot, sm, None, None, {}, logger)
            # 构造（bin/fenix_cli.py cmd_review、core/dashboard/data/admin_actions.py
            # re_review_spec），缺守卫会在状态已转 ready 后抛 AttributeError，调用方
            # 拿不到结果而状态已变更。此处按 None 跳过派发（状态已在 ready，由
            # daemon full_scan recovery 兜底拾取）。
            if self.pm_engine is not None:
                self.pm_engine._on_spec_ready(spec_name)
            self.logger.info("spec_review", f"评审通过: {spec_name} status={status}")
            return True
        elif status == "rejected":
            # 评审否决 → 冻结转人工（fix-blocked-freeze-classification D3）：
            # admin 对「方案被否」无操作杠杆（2026-09-14 事故：17 分钟 admin
            # run 结论「无需介入」把原样 spec 弹回 reviewing → 下轮评审再次否决，
            # 整轮纯烧 token），故不打裸 blocked 而是 frozen=True + 人工升级
            # 告警，使 admin_monitor 的 blocked_stuck 豁免生效。
            #
            # 有界自动复评（2026-09-15 评审误判事故）：`blocking` 由 LLM 自分类，
            # 存在把「文档内部矛盾/遗漏」误判为「方向不成立」的残差（实证：
            # refactor-agent-runner-module 一轮 rejected→人工修补→复评 repaired）。
            # 故首次 rejected MUST NOT 立刻冻结转人工——改回 reviewing 并重派一次
            # 复评（带上一轮 blocking 摘要），把误判自愈在体系内；连续
            # MAX_REJECT_REDO 次（含首次）仍 rejected 才认定方向确不成立，冻结转人工。
            # 计数存 `_review_rejections`（`_` 前缀随 STATE 往返持久化）；任何一次
            # approved/repaired 收口即清零（见上一分支的 update_spec）。
            findings = data.get("findings") or []
            # findings 元素类型校验（code-review item 29ed238af688）：findings 由
            # LLM 产出，元素非 dict 时旧实现 f.get(...) 抛 AttributeError 逃出
            # consume_review_result，绕过失败分类/重试与冻结路径。非 dict 元素
            # 直接忽略（不进 blocking 摘要）。
            if not isinstance(findings, list):
                findings = []
            blocking = [
                f
                for f in findings
                if isinstance(f, dict) and f.get("severity") == "blocking"
            ]
            # detail 值类型归一（code-review item b2b32a1e6f28）：detail 由 LLM
            # 产出，显式 null/数字/嵌套对象（JSON 合法形态）会让 join 抛
            # TypeError 逃出 consume_review_result，绕过失败分类/重试与冻结路径
            # （get 默认值只兜「键缺失」，兜不住显式 null）。`or ""` 归一 falsy
            # 值、str() 兜底非字符串，与 findings 元素级校验同族收口。
            # blocked_summary 统一截断（code-review item cf117513de9e）：detail 由
            # LLM 产出、长度无上界，未经截断进 STATE error/description/evidence 会
            # 撑爆 STATE 行、影响解析与面板展示；同文件日志侧已有 [:200]、recovery.py
            # 写 evidence 有 [:120] 先例，此处源头统一截断，日志侧 [:200] 保留现状。
            # 兜底按 join 结果判空（code-review item 458c827690de）：旧三元只在
            # blocking 列表本身为空时写「无详情」，blocking 非空但 detail 全缺失/
            # falsy 时 join 结果为空串，冻结 error 与人工告警 description 退化为
            # 空详情、丢失兜底语义；空列表 join 亦为空串，天然覆盖原分支。
            blocked_summary = (
                "; ".join(str(f.get("detail") or "") for f in blocking) or "无详情"
            )[:500]

            # 否决计数走锁内原子递增（bump_counters 返回写后值参与阈值判定，
            # code-review item 40842f773883，与 family._do_spec_bug_found 对
            # _verify_fail_rounds 的同型修复 code-fix dd37a2be6ef6 对齐）：
            # 原先「read_one 读旧值 → 内存 +1 → 下方 update_spec 整体写回」
            # 读与写分处两个 STATE 锁临界区，与并发写者（恢复扫描重置字段、
            # 人工面板写 error 的 update_spec）时间重叠时，读旧值写回会吞掉
            # 对方刚写的增量——少计多烧一轮复评；读到并发方刚写的更大值再
            # +1 落回则多计，提前达上限冻结转人工。
            rejections = self.state_machine.bump_counters(
                spec_name, {"_review_rejections": 1}
            ).get("_review_rejections", 0)
            # rejection_class 结构化打回分类（add-pipeline-throughput-governance
            # 5.2）：缺字段/非法值按 unknown 兼容，读侧解析不失败、不告警升级；
            # 分类随 STATE 持久化供统计分桶（统计查询函数 rejection_class_stats
            # 直接扫结果文件，此处记录为 spec 级可追溯冗余）。
            rejection_class = normalize_rejection_class(data.get("rejection_class"))

            if rejections < MAX_REJECT_REDO:
                # 未达上限：不冻结，回 reviewing 触发复评。
                # transition 返回值校验（与上方 approved 分支的 TOCTOU 口径对称）：
                # 读态与 transition 之间存在并发窗口，写者可能已把 spec 推进到
                # 别的状态（或冻结剥离），reviewing→ 非法/被剥离返回 False。失败时
                # 保留 reviewer_run 锚点，不落打回字段、不入队复评——否则非评审态
                # 的 spec 会被盖上评审打回错误文案并丢失锚点（否决计数已由上方
                # bump_counters 原子落盘：该次否决真实发生，保留计入）。
                success = self.state_machine.transition(
                    spec_name, "reviewing",
                    trigger_run_id=run_id, agent_type="spec-review", channel="auto",
                )
                if not success:
                    self.logger.warning(
                        "spec_review",
                        f"评审否决但 transition 回 reviewing 失败，保留锚点待重试: {spec_name}",
                    )
                    return False
                self.state_machine.update_spec(
                    spec_name,
                    {
                        "reviewer_run": None,
                        "_review_attempts": 0,
                        # _review_rejections 已由上方 bump_counters 原子递增
                        # 落盘，此处不再并写（防覆盖并发写者增量）
                        "_review_rejection_class": rejection_class,
                        "error": (f"spec-review-rejected: {blocked_summary}"),
                    },
                )
                self.logger.warning(
                    "spec_review",
                    f"评审否决（第 {rejections}/{MAX_REJECT_REDO} 次）→ 自动复评"
                    f"（未冻结，避免误判转人工）: {spec_name}；"
                    f"blocking: {blocked_summary[:200]}",
                )
                # 复评派发（fix-spec-review-blocking-dispatch 2.6）：rejected 后
                # 自动复评改为入队 spec-review 由队列接力（不再递归直调
                # dispatch_review——收口线程内递归调用会与在飞判据互相否决）。
                # agent_runner 为 None 的 CLI 场景跳过，由 daemon recovery 的
                # reviewing 分支拾取。上轮 blocking 摘要已写入 error，经
                # _prev_error_section 注入复评 prompt（复评者据此区分
                # 「前提证伪」与「文档不一致」）。
                if self.agent_runner is not None and self.pm_engine is not None:
                    self.pm_engine._enqueue(spec_name, "spec-review")
                return True

            # 达上限：方向确不成立，冻结转人工（原语义）；评审专用冻结前缀
            # （4.1），「原状态 reviewing」与 spec-review-rejected 标记保留。
            error_msg = (
                f"{REVIEW_REJECTED_FREEZE_ERROR_PREFIX}原状态 reviewing · "
                f"spec-review-rejected: {blocked_summary}"
            )
            self.state_machine.freeze_for_human(
                spec_name,
                error=error_msg,
                signal_type="spec-review-rejected",
                severity="major",
                description=(
                    f"'{spec_name}' 方案连续 {rejections} 次被评审否决"
                    f"（已自动复评 {rejections - 1} 次仍不成立），需人工修订方案"
                    f"或撤销（blocking findings: {blocked_summary}; "
                    f"评审 run={run_id}）"
                ),
                evidence=(
                    f"spec={spec_name}; run_id={run_id}; "
                    f"rejections={rejections}; findings={blocked_summary}"
                ),
                recommended_action=(
                    "人工修订 spec 方案（proposal.md/design.md）后经 dashboard/"
                    "CLI 解冻——解冻恢复原状态 reviewing，daemon 自动重派评审；"
                    "或直接撤销该 spec"
                ),
                # pm_engine None 守卫（同上两处 freeze 站点先例）：CLI 形态
                # pm_engine=None，缺守卫会在冻结前取属性抛 AttributeError。
                alert_callback=(
                    self.pm_engine._send_human_escalation_alert
                    if self.pm_engine is not None
                    else None
                ),
                extra_updates={
                    "reviewer_run": None,
                    "_review_attempts": 0,
                    "_review_rejections": 0,
                    # 最后一次打回的分类留痕（freeze 时保留，unknown 兼容缺字段）
                    "_review_rejection_class": rejection_class,
                },
            )
            self.logger.info(
                "spec_review",
                f"评审否决（第 {rejections}/{MAX_REJECT_REDO} 次，达上限）"
                f"已冻结转人工: {spec_name}",
            )
            return True
        else:
            # 理论上不会到这里
            # content_failure=True（code-review item 4a086cfce2e9）：同上方
            # 未知 status 通道——status 回显值来自产物，不按文本指纹判 infra。
            self._handle_review_failure(
                spec_name, f"未知 status: {status}", content_failure=True
            )
            return False

    # ── 写入边界校验 ────────────────────────────────────────────

    def _take_snapshot(self, spec_name: str) -> dict:
        """派发前对 SPEC 目录与工作区脏文件记录快照。

        返回快照 dict，包含：
        - spec_files: {相对路径: 内容哈希}——SPEC 目录完整性硬门依据（删除即越界）
        - dirty_files: {相对路径: 内容哈希}（仅 git status --porcelain 列出的脏文件）
          ——仅供 `_verify_snapshot` 记 WARNING 留痕与「新增文件」去重，不作硬门
        """
        spec_dir = self.project_root / "spec" / "changes" / spec_name
        snapshot = {"spec_files": {}, "dirty_files": {}}
        if not spec_dir.is_dir():
            return snapshot
        # 记录 SPEC 目录内所有文件的内容哈希
        for file in spec_dir.rglob("*"):
            if file.is_file():
                rel = str(file.relative_to(self.project_root))
                try:
                    content = file.read_bytes()
                    h = hashlib.md5(content).hexdigest()
                    snapshot["spec_files"][rel] = h
                except OSError:
                    pass
        # 记录工作区脏文件的内容哈希
        try:
            result = subprocess.run(
                ["git", "-C", str(self.project_root), "-c", "core.quotePath=false",
                 "status", "--porcelain"],
                capture_output=True,
                # errors="replace"（code-review item 2e49d64043c9）：text=True
                # 严格解码下非 UTF-8 文件名（core.quotePath=false 原样输出）抛
                # UnicodeDecodeError（ValueError 族）逃出下方 except 元组——
                # 有损替换解码即可（core/regression.py 加固先例同款）。
                text=True, encoding="utf-8", errors="replace",
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    # 脏文件判定：porcelain 首两字符（index 列/工作区列）任一非
                    # 空格即脏——覆盖 ??、MM/AM/MT 组合态，及 index 列 D/R/C 的
                    # 暂存删除/重命名/拷贝（code-review item 0e6649a88334：旧判据
                    # index 列仅认 M/A，'D ' 两列均不命中、暂存删除漏出快照）。
                    # dirty_files 仅作 _verify_snapshot 的 WARNING 留痕、不作硬门，
                    # 放宽判据无行为安全风险；'!!'（assume-unchanged/skip-worktree）
                    # 默认 porcelain 输出不含，语义不受影响。
                    status = line[:2]
                    is_dirty = len(status) == 2 and (status[0] != " " or status[1] != " ")
                    if not is_dirty:
                        continue
                    path = _parse_porcelain_path(line)
                    if path is None:
                        continue
                    # 忽略 SPEC 目录内的文件（已经单独记录）
                    if path.startswith(SPEC_CHANGES_PREFIX):
                        continue
                    full = self.project_root / path
                    if full.is_file():
                        try:
                            content = full.read_bytes()
                            h = hashlib.md5(content).hexdigest()
                            snapshot["dirty_files"][path] = h
                        except OSError:
                            pass
        except (subprocess.SubprocessError, OSError):
            pass
        return snapshot

    def _verify_snapshot(
        self,
        spec_name: str,
        snapshot: dict,
        *,
        status: Optional[str] = None,
        repair_paths: Optional[set] = None,
    ) -> Optional[str]:
        """收工后比对快照，检出越界写入。

        Returns: None 表示通过，否则返回错误信息。

        **只对可归因信号开硬门**（该变动有且仅有「评审者越界」一种解释）：

        - SPEC 目录内文件被删除——评审者只被授权就地修补，删除必为越界。
        - status 为 repaired 时 repairs 条目指向的快照文件哈希未变化——声称的
          修补未实际发生（repairs 由评审器自报，归因明确；code-review item
          d012f86680b9）。

        status 为 approved/rejected 时（契约上 repairs 必为空），SPEC 目录内文件
        哈希变化且未登记对应 repairs 条目属不可归因为合法修补的改动——但并发
        人工编辑同样命中、非归因，不作硬门，记 WARNING 留痕使越界写入可观测
        （code-review item 2ab8c934d277）。

        工作区扫描（既存脏文件被改动、SPEC 目录外新增未跟踪文件）**不作为硬门**：
        评审 run 同步阻塞数分钟且 cwd = 主树，期间任何并发写者（人工编辑、其他
        会话、其他 run）触碰主树都会命中，两者都无法与评审者越界区分。2026-09-14
        evo-item-retention-doc-tracking 因此连丢三份评审结果（约 $25）并空转至尝试
        耗尽。现改为记 WARNING 留痕、放行——评审者的真实写入边界由 repairs 路径
        合法性（`_check_write_boundary` 步骤 1）与结果契约共同钉死。
        """
        spec_dir = self.project_root / "spec" / "changes" / spec_name
        if not spec_dir.is_dir():
            return f"SPEC 目录不存在: {spec_dir}"

        # 检查 SPEC 目录内文件哈希是否变化
        modified_spec = []
        for rel, old_hash in snapshot.get("spec_files", {}).items():
            full = self.project_root / rel
            if not full.exists():
                return f"SPEC 目录内文件被删除: {rel}"
            try:
                content = full.read_bytes()
                new_hash = hashlib.md5(content).hexdigest()
                if new_hash != old_hash:
                    # 文件被修改，这是允许的（repaired 状态）
                    modified_spec.append(rel)
            except OSError:
                return f"无法读取文件: {rel}"

        # repaired 契约上 repairs 须指向实际被修改的文件（code-review item
        # d012f86680b9）：repairs 由评审器自报、归因明确，条目指向快照中存在但
        # 哈希未变化的文件说明声称的修补未实际发生——一份指向未触碰文件的
        # repairs 清单即可按 repaired 收口转 ready，写入边界硬门对该形态失守。
        # 故作硬门（_check_write_boundary 对本函数返回错误按边界错误收口走
        # _handle_review_failure）；快照中不存在的路径（评审期间新增文件）不在
        # 比对范围；快照缺失/损坏时本函数不被调用、检查随之降级跳过（见
        # _check_write_boundary 的读取失败口径）。
        if status == "repaired" and repair_paths is not None:
            unmodified = sorted(
                path for path in repair_paths
                if path in snapshot.get("spec_files", {})
                and path not in modified_spec
            )
            if unmodified:
                return (
                    "repaired 状态 repairs 指向的文件未发生实际改动: "
                    f"{', '.join(unmodified)}"
                )

        # approved/rejected 契约上 repairs 必为空（_check_write_boundary 步骤 3），
        # 此时 SPEC 目录内文件哈希变化且未登记对应 repairs 条目，不可归因为合法
        # 修补——但并发人工编辑同样命中、非归因，不作硬门，仅 WARNING 留痕使
        # 越界写入可观测（code-review item 2ab8c934d277）。
        if status in ("approved", "rejected") and modified_spec:
            unregistered = [
                rel for rel in modified_spec
                if repair_paths is None or rel not in repair_paths
            ]
            if unregistered:
                self.logger.warning(
                    "spec_review",
                    f"评审结果 {status} 但 SPEC 目录内文件被改动（未登记对应 "
                    f"repairs，非归因可能为并发编辑，留痕放行）: {spec_name}: "
                    f"{', '.join(sorted(unregistered))}",
                )

        # 工作区脏文件变动：非归因，仅留痕
        changed_dirty = []
        for rel, old_hash in snapshot.get("dirty_files", {}).items():
            full = self.project_root / rel
            if not full.exists():
                continue  # 文件被删除，可能不是评审者所为
            try:
                content = full.read_bytes()
                new_hash = hashlib.md5(content).hexdigest()
                if new_hash != old_hash:
                    changed_dirty.append(rel)
            except OSError:
                pass
        if changed_dirty:
            self.logger.warning(
                "spec_review",
                f"评审期间工作区脏文件被改动（非归因，放行）: {spec_name}: "
                f"{', '.join(sorted(changed_dirty))}",
            )

        # SPEC 目录外新增未跟踪文件：非归因（并发写者新建文件同样命中），仅留痕
        added_untracked = []
        try:
            result = subprocess.run(
                ["git", "-C", str(self.project_root), "-c", "core.quotePath=false",
                 "status", "--porcelain"],
                capture_output=True,
                # errors="replace"（code-review item 2e49d64043c9）：text=True
                # 严格解码下非 UTF-8 文件名（core.quotePath=false 原样输出）抛
                # UnicodeDecodeError（ValueError 族）逃出下方 except 元组——
                # 有损替换解码即可（core/regression.py 加固先例同款）。
                text=True, encoding="utf-8", errors="replace",
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("??"):
                        path = _parse_porcelain_path(line)
                        if path is None:
                            continue
                        if not path.startswith(SPEC_CHANGES_PREFIX):
                            # 检查是否在快照中已存在
                            if path not in snapshot.get("dirty_files", {}):
                                added_untracked.append(path)
        except (subprocess.SubprocessError, OSError):
            pass
        if added_untracked:
            self.logger.warning(
                "spec_review",
                f"评审期间 SPEC 目录外新增未跟踪文件（非归因，放行）: {spec_name}: "
                f"{', '.join(sorted(added_untracked))}",
            )

        return None

    def _check_write_boundary(self, spec_name: str, review_data: dict) -> Optional[str]:
        """校验评审 run 的写入边界：repairs 路径合法性、SPEC 目录完整性、status 与改动一致。

        工作区扫描（脏文件变动 / 目录外新增文件）只留痕不拦截——非归因信号，
        见 `_verify_snapshot`。

        Returns: None 表示通过，否则返回错误信息。
        """
        spec_dir = self.project_root / "spec" / "changes" / spec_name
        if not spec_dir.is_dir():
            return f"SPEC 目录不存在: {spec_dir}"

        # 1. repairs 路径合法性（解析后归属校验，code-review item bdec829dca96）
        # 评审结果 JSON 由 LLM 产出（不可信输入），此处是写入边界的唯一硬门。
        # 旧实现只做字符串前缀 startswith("spec/changes/")：`spec/changes/../foo.txt`
        # 未归一化即可穿过，且 `/` 形态的绝对/跨 spec 路径只要文件存在也能通过。
        # 改为 Path 解析 + 归属校验：归一化后唯一合法落点必须是**本 spec** 目录
        # （spec/changes/<spec_name>/）内的文件。
        spec_root = (self.project_root / "spec" / "changes").resolve()
        allowed_dir = (spec_root / spec_name).resolve()
        repairs = review_data.get("repairs") or []
        # repairs 元素类型校验（code-review item 29ed238af688）：repairs 由 LLM
        # 产出，可能非列表/元素非 dict；旧实现 repair.get(...) 会抛 AttributeError
        # 逃出 consume_review_result，绕过本文件的失败分类/重试与冻结路径。
        # 非法形态按「非法产物」直接判失败（fail-closed），不进 repairs 校验循环。
        if not isinstance(repairs, list):
            return f"repairs 非列表（非法产物）: {type(repairs).__name__}"
        # 归一化后的 repairs 路径集合（快照键同形），供步骤 2 集合比对消费。
        repair_paths: set = set()
        for repair in repairs:
            if not isinstance(repair, dict):
                return f"repairs 元素非对象（非法产物）: {repair!r}"
            path = repair.get("path", "")
            if not isinstance(path, str) or not path:
                return f"repairs 路径越界: {path!r}"
            candidate = Path(path)
            if candidate.is_absolute():
                return f"repairs 路径越界（绝对路径）: {path}"
            resolved = (self.project_root / candidate).resolve()
            # 归一化后必须落在本 spec 目录内的文件上（等于目录本身视为越界：
            # 目录 exists() 恒真，一条指向目录自身的伪 repair 即可满足
            # 「repaired 状态无修补清单」硬门，repairs 清单失去指向真实被修补
            # 文件的审计语义——code-review item b497c1b4ebbc）
            if resolved == allowed_dir or allowed_dir not in resolved.parents:
                return f"repairs 路径越界（须落在 {spec_name}/ 内）: {path}"
            if not resolved.exists():
                return f"repairs 路径不存在: {path}"
            # 归一化为快照键同形（code-review item 8477caae0977）：快照键是
            # str(file.relative_to(project_root)) 规范形（spec/changes/<spec>/a.md），
            # 步骤 1 归属校验只经 resolve() 判合法性——'./spec/...'、冗余分隔符等
            # 形态可通过校验却在 _verify_snapshot 的集合比对中失配，repaired 硬门
            # 误判「未发生实际改动」、approved/rejected 留痕比对同理误报。两侧均
            # 已 resolve，relative_to 纯词法比较口径一致。
            try:
                repair_paths.add(
                    resolved.relative_to(self.project_root.resolve()).as_posix()
                )
            except ValueError:
                # 极端布局（spec/ 为符号链接等）致两侧前缀不一致时保留原始
                # 字符串，比对口径退回旧行为，不让归一化自身引入新异常面。
                repair_paths.add(path)

        # status 提前取出供步骤 2/3 消费（approved/rejected 伴随的 SPEC 目录改动
        # 须留痕，code-review item 2ab8c934d277）；repair_paths 已在步骤 1 归一化
        # 构造（快照键同形，code-review item 8477caae0977）。
        status = review_data.get("status")

        # 2. 快照比对（需要从临时文件加载派发前快照；读取/解析抽公共助手
        # _load_snapshot_or_none 与 _artifact_landed_valid 共用，不再各复制一份
        # ——code-review item ade5d0dfdc2b）
        snapshot, snap_err_type, snap_err_msg = self._load_snapshot_or_none(spec_name)
        if snapshot is not None:
            try:
                snapshot_err = self._verify_snapshot(
                    spec_name, snapshot, status=status, repair_paths=repair_paths
                )
                if snapshot_err:
                    return snapshot_err
            except TypeError as e:
                # 与读取失败同口径降级（沿用抽助手前 verify 位于读取 try 内的
                # 防御行为，不逃出本方法）。
                snap_err_type, snap_err_msg = type(e).__name__, str(e)
        if snap_err_type is not None:
            # 读取失败不再静默放行（code-review item 5d38e8dd6478 / 6a3f77476d0f）：
            # 快照是 SPEC 目录完整性硬门（删除检测）的唯一依据，缺失/损坏时
            # 旧实现 pass 静默放行、且无日志——越界删除将无人发现。Non-UTF8
            # 内容抛 UnicodeDecodeError（非 OSError 子类）此前还会直接逃出本方法。
            # 记 WARNING 明确降级（保留既有放行语义，但使降级可观测）。
            _logger.warning(
                "spec_review: 快照读取失败 '%s'（%s，跳过目录完整性比对，"
                "删除检测降级）: %s",
                spec_name,
                snap_err_type,
                snap_err_msg,
            )

        # 3. status 与改动一致性
        if status == "approved" and repairs:
            return "approved 状态伴随文件改动"
        if status == "repaired" and not repairs:
            return "repaired 状态无修补清单"
        # rejected 必须无修补清单：既判「前提/方向不成立」又改了文档属自相矛盾。
        # 判据依据（2026-09-15 评审误判事故）：能落在 SPEC 目录内修复的问题
        # 一律属 repairable（agent prompt 的「severity 判定标准」已固化该口径）；
        # 若评审确实改了文档使方案成立，正确结论是 repaired 而非 rejected。
        if status == "rejected" and repairs:
            return "rejected 状态伴随文件改动"

        return None

    def _load_snapshot_or_none(
        self, spec_name: str
    ) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
        """加载派发前快照 JSON（_check_write_boundary 与 _artifact_landed_valid 共用）。

        「读 snapshot.json → json.loads → 非 dict 抛 TypeError → 降级」此前在两个
        调用点各复制一份，且已为同一缺陷（5d38e8dd6478）两次成对修改（code-review
        item ade5d0dfdc2b）——抽公共入口，后续再补异常类（如 UnicodeDecodeError
        家族）只改一处，防人肉同步漂移。快照可能被外部写成合法但非对象的 JSON
        （如 []），_verify_snapshot 的 .get 会抛 AttributeError 逃出调用方——按
        读取失败同款口径降级：抛 TypeError 归入读取失败。

        Returns:
            (snapshot, None, None)：快照存在且为 JSON 对象；
            (None, None, None)：快照文件不存在（调用方跳过比对）；
            (None, 异常类型名, 异常消息)：读取失败/非 JSON 对象（调用方记
            WARNING 降级）。
        """
        snapshot_path = self.project_root / ".fenix" / "spec-review" / spec_name / "snapshot.json"
        if not snapshot_path.exists():
            return (None, None, None)
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if not isinstance(snapshot, dict):
                raise TypeError(f"快照非 JSON 对象: {type(snapshot).__name__}")
            # 子字段形态校验（code-review item cd7e15d9b3ac）：顶层是 dict 而
            # spec_files/dirty_files 被外部写成字符串/列表/数字/null 时，
            # _verify_snapshot 的 .get(...).items() 会抛 AttributeError 逃出调用方
            # 仅捕 TypeError 的 except——与顶层非对象同口径抛 TypeError 归入读取
            # 失败；键缺失时 .get 缺省 {}，与 _verify_snapshot 的缺省口径一致。
            for key in ("spec_files", "dirty_files"):
                if not isinstance(snapshot.get(key, {}), dict):
                    raise TypeError(
                        f"快照字段 {key} 非 JSON 对象: {type(snapshot[key]).__name__}"
                    )
            return (snapshot, None, None)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError) as e:
            # Non-UTF8 内容抛 UnicodeDecodeError（非 OSError 子类），显式收口。
            return (None, type(e).__name__, str(e))

    # ── 故障重试 ────────────────────────────────────────────────

    def _artifact_landed_valid(
        self, spec_name: str, run_started_at: float | None = None
    ) -> Tuple[bool, Optional[dict]]:
        """校验评审 run 产物是否已合法落盘（任务 1.1）。

        判定「合法」的条件：
        1. 结果文件存在、非空、可解析为 JSON 对象
        2. status ∈ {approved, repaired}
        3. mtime ≥ 锚点写入时刻（防上轮残留合法文件替本轮放行）
        4. 快照 spec 一致性校验通过（复用 _verify_snapshot）

        Returns:
            (True, data) 如果产物合法，data 为解析后的结果对象。
            (False, None) 如果产物不合法。

        设计依据（D1 产物优先判定）：run 成败由 CLI exit code 一票判定时，
        产物是否已合法落盘不作为判败前置条件——「产物已具备却被退出码一票否决」。
        本方法在 run 失败时前置校验，合法产物优先消费，exit code 失败仅降级
        为 warning 日志并留痕。

        锚点优先级：调用方显式传入的 ``run_started_at`` 优先生效（与
        ``consume_review_result`` 同名单参同口径，code-review item 1ea5bc3bc4b7
        ——旧实现被 run_id 尾段 epoch 无条件覆盖，参数语义失效）；未显式传入时
        才回落解析 entry.reviewer_run 内嵌 epoch 时间戳（dispatch_review 步骤①
        写入 run_id 的时刻，run_id 形如
        ``spec-review-<spec>-<rand>-<ts>``，尾段恒为秒级 epoch）。
        """
        result_path = spec_review_result_path(self.project_root, spec_name)

        # 锚点解析：显式传入的 run_started_at 优先生效；仅未传时回落 reviewer_run
        # 内嵌 epoch 时间戳（run_id 尾部段）——旧实现尾段无条件覆盖显式传参，
        # 参数语义失效（code-review item 1ea5bc3bc4b7）。
        anchor_ts = run_started_at
        if anchor_ts is None:
            try:
                entry = self.state_machine.read_one(spec_name) or {}
                run_id = entry.get("reviewer_run") or ""
                if run_id:
                    tail = str(run_id).rsplit("-", 1)[-1]
                    if tail.isdigit():
                        anchor_ts = float(tail)
            except (TypeError, ValueError):
                pass

        try:
            if not result_path.is_file():
                return (False, None)
            if result_path.stat().st_size == 0:
                return (False, None)

            # mtime 新鲜度校验：mtime 早于锚点（宽限 1s 吸收 fs 写入滞后）
            if anchor_ts is not None:
                mtime = result_path.stat().st_mtime
                if mtime < anchor_ts - 1.0:
                    return (False, None)

            # JSON 解析
            try:
                data = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                # UnicodeDecodeError 非 OSError 子类（与本文件既有同族收口一致，
                # code-review item 1bba3286c4fb）：run 中途崩溃留下的多字节中截断
                # 产物按「产物非法」返回 (False, None) 走既有重试语义，不逃出本
                # 方法——dispatch_review 的 run 失败路径直调本方法且无兜底 try。
                return (False, None)

            if not isinstance(data, dict):
                return (False, None)

            # status 白名单校验（仅 approved/repaired 视为合法产物）
            status = data.get("status")
            if status not in ("approved", "repaired"):
                return (False, None)

            # 快照 spec 一致性校验（复用 _verify_snapshot；读取/解析抽公共助手
            # _load_snapshot_or_none 与 _check_write_boundary 共用，不再各复制
            # 一份——code-review item ade5d0dfdc2b）
            snapshot, snap_err_type, snap_err_msg = self._load_snapshot_or_none(spec_name)
            if snapshot is not None:
                try:
                    snapshot_err = self._verify_snapshot(spec_name, snapshot)
                    if snapshot_err:
                        return (False, None)
                except TypeError as e:
                    # 与读取失败同口径降级（沿用抽助手前 verify 位于读取 try 内
                    # 的防御行为，不逃出本方法）。
                    snap_err_type, snap_err_msg = type(e).__name__, str(e)
            if snap_err_type is not None:
                # 与 _check_write_boundary 同款：读取失败记 WARNING 而非静默
                # 放行（code-review item 5d38e8dd6478）。
                self.logger.warning(
                    "spec_review",
                    f"产物判定快照读取失败 '{spec_name}'（跳过一致性校验）: "
                    f"{snap_err_type}: {snap_err_msg}",
                )

            return (True, data)

        except (OSError, AttributeError):
            return (False, None)

    def _classify_run_failure(
        self,
        reason: str | None,
        spec_name: str | None = None,
        *,
        api_error_status=None,
        conn_error=None,
        content_failure: bool = False,
    ) -> str:
        """三类失败分类（evo-run-failure-classification-circuitbreaker D1）。

        扩展 evo-run-failure-artifact-first 的同名 `_classify_run_failure`（沿用同名，
        勿另开 `_classify_failure`）为三分 "artifact" | "infra" | "content"：

        - artifact：产物已落盘合法（调用 `_artifact_landed_valid`）；优先级最高；
        - infra：结构化归因命中（api_error_status ∈ {402,403,429} /
          conn_error 显式 True——evo-fix-spec-review-infra-attribution-bridge 1.3，
          优先于文本词表）或指纹匹配（403/402/429/quota/budget/余额/insufficient
          balance/ rate limit / 既有 provider 熔断信号 "provider circuit open" /
          "provider chain exhausted"——runner.py:2458/2473，供侧熔断同属 infra）
          或 CLI 进程级崩溃（error 含 "Exit code: N" 且 N 非 0/1——"Exit code: 1"
          不得一律判 infra，评审器内容失败同样 exit 1）；或 probe 标记
          model_chain_preflight_failed；
        - content：其余（含空白轮次）。

        Args:
            reason: run 失败原因文本（可为 None）。
            spec_name: 可选；给出时前置校验产物是否已合法落盘，命中则判 artifact。
            api_error_status: 可选结构化归因（单轮 API 错误状态码，来自
                AgentRunResult.api_error_status）；非 None 时优先消费，命中
                _STRUCTURED_INFRA_API_STATUS 即判 infra。
            conn_error: 可选结构化归因（连接类标记，来自
                AgentRunResult.conn_error）；仅显式 True 判 infra（`is True`
                严格等值，防 MagicMock 等替身对象误判，见实现处注释）。
            content_failure: 可选短路标记（code-review item 4a086cfce2e9）——
                本模块自产文案（硬门回显/结果文件读取失败/未知 status）内嵌
                不可信产物内容（解析器行号/回显 status），置 True 跳过文本指纹
                匹配恒归 content；结构化归因优先级不变。

        Returns: "artifact" | "infra" | "content"。
        """
        # artifact 分支优先级最高：产物已落盘合法 → 判别失败，直接消费不重试。
        if spec_name:
            try:
                landed = self._artifact_landed_valid(spec_name)
            except (AttributeError, TypeError, ValueError):
                landed = False
            # _artifact_landed_valid 返回 (bool, data) 元组；兼容测试替身返回裸 bool。
            artifact_ok = landed[0] if isinstance(landed, tuple) else bool(landed)
            if artifact_ok:
                return "artifact"
        # 结构化归因优先（evo-fix-spec-review-infra-attribution-bridge 1.3）：
        # stderr 降噪后文本指纹对限流类失败恒 False（只剩 "Exit code: 1"），
        # runner 层挂载的 api_error_status / conn_error 是供给瞬态的第一手证据。
        # 容错非 int 形态（防御性 int() 归一，脏值按未携带处理回退文本分类）。
        if api_error_status is not None:
            try:
                status_code = int(api_error_status)
            except (TypeError, ValueError):
                status_code = None
            if status_code in _STRUCTURED_INFRA_API_STATUS:
                return "infra"
        # 严格等值判定（对齐 :414 frozen_terminated `is True` 先例）：MagicMock
        # 等替身在属性访问时自动生成 truthy 子对象，裸布尔会把无结构化归因的
        # content 失败误判 infra——生产结果该字段为显式 bool/None，不受影响。
        if conn_error is True:
            return "infra"
        # 本模块自产文案短路（code-review item 4a086cfce2e9）：结果文件读取失败/
        # 硬门文案/未知 status 三个通道的 reason 由本模块拼接且内嵌不可信产物
        # 内容——JSON 解析器行号（"Expecting value: line 429 column 3"）与回显
        # 产物 status（"status='429' 不在白名单"）两侧为空格/引号，会被
        # _NUMERIC_INFRA_RE / _INFRA_FINGERPRINT_RE 判 infra，纯 content/格式类
        # 失败由此不递增 _review_attempts、重试预算被跳过并持续计入熔断。这些
        # 通道只反映产物落盘/格式/取值问题——真实链路失败走 run error 通路
        # （dispatch 侧带结构化归因，见上方两检查，优先级不变），不取道于此，
        # 故仅对文本词表短路归 content，infra 判定对真实网络错误文案语义保留。
        if content_failure:
            return "content"
        low = (reason or "").lower()
        # 监督超时前置排除（code-review item 4b0176280b0a）：须在指纹匹配之前——
        # "extension budget exhausted" 含裸指纹 "budget" 会被误判 infra；归 content
        # 走既有重试语义（递增 _review_attempts，挂死超时亦耗尝试预算）。
        for super_phrase in _SUPERVISION_TIMEOUT_PHRASES:
            if super_phrase in low:
                return "content"
        # 词形指纹：与数字指纹同款分隔符边界匹配（code-review item
        # 489d6071b236，见 _INFRA_FINGERPRINT_RE 注释），防 spec 名/路径内嵌
        # 词根被裸子串误判 infra。
        if _INFRA_FINGERPRINT_RE.search(low):
            return "infra"
        # 数字类指纹（402/403/429）：分隔符边界匹配（两侧不邻接 ASCII
        # 字母/数字/连字符），防任意数字串与 spec 名连字符形态误判 infra
        # （见 _NUMERIC_INFRA_RE 注释，code-review item b4ce03fd99c4 /
        # 80d45b2a5087）。
        if _NUMERIC_INFRA_RE.search(low):
            return "infra"
        # CLI 进程级崩溃：exit code 非 0/1（0 正常 / 1 内容失败）
        m = _CLI_EXIT_CODE_RE.search(reason or "")
        if m:
            try:
                code = int(m.group(1))
            except ValueError:
                code = None
            if code not in (None, 0, 1):
                return "infra"
        return "content"

    def _handle_review_failure(
        self, spec_name: str, reason: str, *, allow_artifact: bool = True,
        run_started_at: float | None = None,
        api_error_status=None, conn_error=None,
        content_failure: bool = False,
    ):
        """处理评审失败：按失败分类落点（D1/D2）。

        ``allow_artifact=False``（写入边界类失败调用）：禁止 artifact 分类回流
        ——否则 consume → 边界错误 → _handle_review_failure → artifact →
        consume 无限递归（code-review item 4b9f59b8717f）。``run_started_at``
        透传给回流消费，保持 mtime 新鲜度校验。

        ``api_error_status`` / ``conn_error``（evo-fix-spec-review-infra-
        attribution-bridge 1.3）：AgentRunResult 的结构化归因字段原样透传给
        ``_classify_run_failure``——归因桥接的最后一段，缺省 None 时分类走
        既有文本词表回退，既有调用形态（不传这两个关键字）行为不变。

        ``content_failure``（code-review item 4a086cfce2e9）：本模块自产文案
        （硬门回显/结果文件读取失败/未知 status）调用时置 True——reason 内嵌的
        解析器行号与回显产物 status 来自不可信产物内容，分类跳过文本指纹匹配
        恒归 content；真实链路失败（run error 通路，带结构化归因）不传该标志，
        infra 判定语义不受影响。

        - artifact：产物已落盘合法 → 直接消费（不重试，run-failure-artifact-first
          承接；`_artifact_landed_valid` 缺失时回退 content）；
        - infra：熔断计数 + 升级告警；清 reviewer_run、**不递增 _review_attempts**
          （熔断前与冷却期均不计入——infra 属链路级问题而非 spec 内容问题；若递增，
          第 3 次 infra 会同时触 MAX_REVIEW_ATTEMPTS=3 freeze 破坏「冷却后自动
          恢复」；若不清锚点，冷却到期后 dispatch_review 见 reviewer_run 非空拒派
          （spec_review.py:67-69），spec 永久卡 reviewing）；
        - content：维持既有重试语义（递增 _review_attempts，达上限转冻结转人工）。

        error 保留 ``spec-review-incomplete:`` 前缀不变（复用 re_review 的
        startswith 契约）。
        """
        failure_type = self._classify_run_failure(
            reason, spec_name if allow_artifact else None,
            api_error_status=api_error_status, conn_error=conn_error,
            content_failure=content_failure,
        )

        if failure_type == "artifact":
            # 判别失败：产物已落盘合法 → 直接消费收口，不重试。
            self.logger.info("spec_review", f"判别失败（产物已落盘）→ 直接消费: {spec_name}")
            # 仅在确有 run_started_at 时才透传该关键字——保持既有调用形态
            # （run_started_at=None 与「不传」语义等价：均跳过 mtime 新鲜度校验），
            # 避免为无意义的 None 改变调用签名（既有测试以位置参数断言）。
            if run_started_at is not None:
                self.consume_review_result(spec_name, run_started_at=run_started_at)
            else:
                self.consume_review_result(spec_name)
            return

        if failure_type == "infra":
            # infra 失败：熔断计数 + 升级告警（触发熔断时恰好落一条 critical）。
            breaker = getattr(self.pm_engine, "infra_breaker", None)
            if breaker is not None:
                triggered = breaker.record_failure("spec-review")
                # record_failure 内部消费掉的到期恢复（返回值只见 triggered
                # 布尔，未达阈值时为 False）经一次性标志补落 recovered 记录
                # （D3，恰好一条；code-review item c3dfbbd563f5）
                if breaker.take_recovery_flag("spec-review"):
                    self.pm_engine._emit_infra_breaker_event(
                        "recovered", spec_name, "", breaker.get_state("spec-review")
                    )
                if triggered:
                    self.pm_engine._emit_infra_breaker_event(
                        "triggered", spec_name, reason, breaker.get_state("spec-review")
                    )
            # 清 reviewer_run、不递增 _review_attempts（保持原值）
            self.state_machine.update_spec(
                spec_name,
                {
                    "reviewer_run": None,
                    "error": f"spec-review-incomplete: infra failure: {reason}",
                },
            )
            self.logger.warning(
                "spec_review", f"评审 infra 失败（熔断计数，不递增尝试）: {spec_name}: {reason}"
            )
            return

        # ── content 分支：重试改为入队（fix-spec-review-blocking-dispatch 2.5）──
        # 原：保持 reviewing + 清 reviewer_run → 由 `dispatch_review` 返回后
        # 调用方重试。改造后：清 reviewer_run → 入队 spec-review → 由队列接力
        # 在独立 worker 线程重试。重试入队前 MUST 已清除 reviewer_run（否则队列
        # 候选筛选判「reviewer_run 非空 + in_flight=True」→ 拒派；任务 2.5 约束）。
        # 本方法在 dispatch_review 栈内执行，worker 的 finally 会兜底调
        # `_process_queue`，所以不需要额外触发。CLI 场景 pm_engine=None 保持原语义
        # （记日志，由 daemon recovery 拾取）。
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            return
        # 尝试计数走锁内原子递增（bump_counters 返回写后值参与阈值判定，
        # code-review item 40842f773883，与 family._do_spec_bug_found /
        # dispatch/queue._merge_streak 的同型修复对齐）：原先「read_one 读
        # 旧值 → 内存 +1 → update_spec 整体写回」读与写分处两个 STATE 锁
        # 临界区，与并发写者（恢复扫描重置字段、人工面板写 error 的
        # update_spec）时间重叠时，读旧值写回会吞掉对方刚加的增量——少计
        # 多烧一轮重试；读到并发方刚写的更大值再 +1 落回则多计，提前达上限
        # 冻结转人工。
        attempts = self.state_machine.bump_counters(
            spec_name, {"_review_attempts": 1}
        ).get("_review_attempts", 0)
        # 严格小于：bump 后恰达 MAX 即落下方 else 就地冻结——终态同
        # dispatch_review 入口闸的 >= MAX 冻结（实际 run 次数不变：首次 +
        # MAX-1 次重试），省去空转一轮入队/出队与短退避等待
        # （code-review item e7bc76108f09）。
        if attempts < MAX_REVIEW_ATTEMPTS:
            # 重试：保持 reviewing 状态，清除 reviewer_run + 入队
            # （_review_attempts 已由上方 bump_counters 原子递增落盘，此处
            # 不再并写，防覆盖并发写者增量）
            self.state_machine.update_spec(
                spec_name,
                {
                    "reviewer_run": None,
                    "error": f"spec-review-incomplete: {reason}",
                },
            )
            self.logger.info("spec_review", f"评审失败重试: {spec_name} attempt={attempts}")
            if self.pm_engine is not None:
                # content 失败重派短退避（evo-fix-spec-review-infra-attribution-
                # bridge 3.1）：重派入队前加一档秒级短延迟（判重防重复定时器）。
                self._enqueue_review_retry(spec_name)
        else:
            # 达上限转冻结转人工（fix-blocked-freeze-classification 2.2）：
            # admin 对「评审器连续失败」无操作杠杆（模型链/配置问题），
            # 改走 freeze_for_human「冻结 + 告警」成对入口，使 admin_monitor
            # 的 blocked_stuck 豁免生效。_review_attempts 已由上方
            # bump_counters 写至恰达 MAX（严格小于判据下正常路径即冻结于此），
            # 随本次冻结 extra_updates 显式清零
            # （清零口径不变，不覆盖并发写者增量的问题在此不存在）。
            r_id = entry.get("reviewer_run")
            # 评审专用冻结前缀（4.1）：自动冻结不自称「用户指令冻结」；
            # 「原状态 reviewing」子串与 spec-review-incomplete 标记按红线保留。
            error_msg = (
                f"{REVIEW_ATTEMPTS_FREEZE_ERROR_PREFIX}原状态 reviewing · "
                f"spec-review-incomplete: {reason}"
            )
            self.state_machine.freeze_for_human(
                spec_name,
                error=error_msg,
                signal_type="spec-review-incomplete",
                severity="major",
                description=(
                    f"'{spec_name}' 评审器连续失败（模型链/配置问题）至"
                    f"尝试上限（{MAX_REVIEW_ATTEMPTS}），需人工排查"
                ),
                evidence=(f"spec={spec_name}; run_id={r_id or '无'}; reason={reason}"),
                recommended_action=(
                    "人工排查评审链路根因（模型链/配置/结果硬门/写入边界）；"
                    "排查后经 dashboard/CLI 解冻——解冻恢复原状态 reviewing，"
                    "daemon 自动重派评审；或直接撤销该 spec"
                ),
                # pm_engine None 守卫（code-review item a74a3c85dec1）：与本文件
                # dispatch_review 耗尽分支及 :480/:1182 先例同款——CLI 形态
                # pm_engine=None，缺守卫会在冻结前取属性抛 AttributeError。
                # freeze_for_human 对 None 回调按静默冻结处理（记 ERROR 审计）。
                alert_callback=(
                    self.pm_engine._send_human_escalation_alert
                    if self.pm_engine is not None
                    else None
                ),
                extra_updates={
                    "reviewer_run": None,
                    "_review_attempts": 0,
                    # 与否决冻结站点及四处通过收口对齐清零否决计数（code-review
                    # item 10592411f0b1）：同 dispatch_review 尝试耗尽冻结口径——
                    # 陈旧否决计数会使解冻重走评审时首次 rejected 即达上限冻结；
                    # _review_rejection_class 按既有清零口径保留作分类留痕。
                    "_review_rejections": 0,
                },
            )
            self.logger.warning("spec_review", f"评审失败达上限: {spec_name}")

    # ── content 重试短退避（evo-fix-spec-review-infra-attribution-bridge 3.1）──

    def _content_retry_backoff_seconds(self) -> float:
        """content 失败重派短退避秒数（``review.content_retry_delay_seconds``）。

        配置容错（对齐 backoff._transient_redispatch_delay 口径）：非法配置值
        回退缺省，不中断重试链路；0 = 关闭退避（立即重派，既有行为）。
        """
        getter = getattr(self.pm_engine, "_get_config", None)
        if not callable(getter):
            return REVIEW_CONTENT_RETRY_BACKOFF_SECONDS
        try:
            val = float(
                getter(
                    REVIEW_CONTENT_RETRY_DELAY_CONFIG_KEY,
                    REVIEW_CONTENT_RETRY_BACKOFF_SECONDS,
                )
            )
        except (TypeError, ValueError, OverflowError):
            # code-review item 851ba3eeed41：巨大 int（YAML 任意精度）送 float()
            # 抛 OverflowError，同按脏值回退缺省——不拦截会沿 _enqueue_review_retry
            # → _handle_review_failure（content 分支）→ consume_review_result
            # 上抛打断本轮评审失败收口（口径同 infra_breaker threshold，
            # item 8c2855513307）。
            return REVIEW_CONTENT_RETRY_BACKOFF_SECONDS
        # 负值/非有限浮点（.inf/.nan）按脏值回退缺省——同 backoff.py 对
        # transient_redispatch_delay 的守卫口径（item e2d87491cc64）。
        if not math.isfinite(val) or val < 0:
            return REVIEW_CONTENT_RETRY_BACKOFF_SECONDS
        return val

    def _enqueue_review_retry(self, spec_name: str) -> None:
        """content 失败重试入队：短退避延迟后入队（3.1）。

        - 退避关闭（delay <= 0）或 pm_engine 未初始化定时器机制（CLI 形态 /
          测试替身缺成员）：立即入队降级——退避属节奏优化非正确性依赖
          （design 风险段），MUST NOT 因退避机制缺失丢失重派；
        - 否则按 backoff._schedule_recovery_timer 范式排程一次性 Timer：
          判重集合 ``_review_content_backoff_timers``（pm_engine 门面持有、
          跨 SpecReviewManager 实例存续——本管理器每次派发重建，实例级集合
          判不住跨派发重复）防重复定时器；到期回调重入队 + 重扫队列。
          Timer 跨重启丢失即退回现状立即重派（recovery reviewing 分支兜底），
          可接受。
        """
        pm = self.pm_engine
        delay = self._content_retry_backoff_seconds()
        timers = getattr(pm, "_review_content_backoff_timers", None)
        scheduler = getattr(pm, "_schedule_recovery_timer", None)
        if delay <= 0 or not hasattr(timers, "discard") or not callable(scheduler):
            pm._enqueue(spec_name, "spec-review")
            return
        scheduler(
            spec_name,
            timers=timers,
            resolve_delay=lambda _spec: delay,
            min_delay=delay,
            callback=self._fire_content_backoff,
            scheduled_log=(
                "评审质量失败短退避：'{spec_name}' 将在 {delay}s 后重派评审"
                "（review.content_retry_delay_seconds）"
            ),
        )

    def _fire_content_backoff(self, spec_name: str) -> None:
        """短退避到期回调：摘判重标记 → 重入队评审 → 重扫队列。

        对齐 backoff._fire_recovery_callback 范式（摘标记须持 ``_queue_lock``
        ——与 ``_schedule_recovery_timer_locked`` 的锁内 add 同锁互斥）。
        """
        pm = self.pm_engine
        timers = getattr(pm, "_review_content_backoff_timers", None)
        lock = getattr(pm, "_queue_lock", None)
        if timers is not None and lock is not None:
            try:
                with lock:
                    timers.discard(spec_name)
            except Exception:  # noqa: BLE001 — 摘标记失败不得阻断重派
                self.logger.warning(
                    "spec_review", f"短退避判重标记摘除失败: {spec_name}"
                )
        pm._enqueue(spec_name, "spec-review")
        process_queue = getattr(pm, "_process_queue", None)
        if callable(process_queue):
            process_queue()

    # ── 人工恢复入口 ────────────────────────────────────────────

    def re_review(self, spec_name: str) -> Tuple[bool, str]:
        """重新评审入口：对符合开放条件的 blocked SPEC 执行 blocked → reviewing。

        Returns: (success, message)
        """
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            return False, "SPEC 不存在"
        if entry.get("status") != SpecStatus.BLOCKED:
            return False, "SPEC 状态不是 blocked"
        if entry.get(FROZEN_FIELD):
            return False, "SPEC 已冻结"
        error = entry.get("error") or ""
        if not (
            error.startswith("spec-review-rejected:") or error.startswith("spec-review-incomplete:")
        ):
            return False, "SPEC 未因评审进入 blocked"

        # 执行 blocked → reviewing（fix-observability-gaps 2.2：人工重评来源）
        success = self.state_machine.transition(
            spec_name, "reviewing",
            trigger_run_id=entry.get("reviewer_run") or None,
            agent_type="spec-review", channel="manual",
        )
        if not success:
            return False, "状态转移失败"

        # 清零遗留评审尝试计数（code-review item 95dc60d625f3）：经旧语义（尝试
        # 耗尽转 blocked，error=spec-review-incomplete）遗留、attempts 已达
        # MAX_REVIEW_ATTEMPTS 的 spec，人工重评后首次 dispatch_review 即在尝试闸
        # 再次 freeze_for_human，重评动作被吞掉一轮（冻结 extra_updates 会清零、
        # 解冻后自愈，但多一次冻结/解冻往返）。与 responsible_release 的
        # update_spec 清字段口径对齐；须先于下方入队落盘——派发闸按 STATE 计数
        # 判定。
        self.state_machine.update_spec(
            spec_name,
            {
                "_review_attempts": 0,
                # 与 responsible_release 口径对齐清零否决计数（code-review item
                # 8fcf35364432，同 10592411f0b1 各冻结/通过收口站点）：旧语义
                # 遗留的 blocked（error=spec-review-rejected）条目可能带陈旧
                # 否决计数，不清零则重评后首次 rejected 即达 MAX_REJECT_REDO
                # 冻结转人工，跳过「初次否决 + 自动复评确认」的有界契约。
                # _review_rejection_class 按既有口径保留作分类留痕。
                "_review_rejections": 0,
            },
        )

        # 派发新评审（fix-spec-review-blocking-dispatch 2.7：改投队列）——
        # agent_runner 为 None 的 CLI 场景跳过派发，由 daemon full_scan
        # recovery 的 reviewing 分支拾取。in-process（daemon 侧）场景：
        # 入队 spec-review 由队列接力在 worker 线程派发，re_review 立即返回。
        if self.agent_runner is not None and self.pm_engine is not None:
            self.pm_engine._enqueue(spec_name, "spec-review")

        return True, "重新评审已触发"

    def responsible_release(self, spec_name: str) -> Tuple[bool, str]:
        """担责放行入口：对 blocked SPEC 执行 blocked → ready（人工裁决）。

        Returns: (success, message)
        """
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            return False, "SPEC 不存在"
        if entry.get("status") != SpecStatus.BLOCKED:
            return False, "SPEC 状态不是 blocked"
        # 冻结前置检查（与 re_review 同款）：frozen-strip 语义下 frozen spec
        # 的 transition 必失败，须明确报冻结而非误导性的「状态转移失败」
        if entry.get(FROZEN_FIELD):
            return False, "SPEC 已冻结（请先解冻）"

        # 执行 blocked → ready（fix-observability-gaps 2.2：人工担责放行来源）
        success = self.state_machine.transition(
            spec_name, "ready",
            trigger_run_id=entry.get("reviewer_run") or None,
            agent_type="spec-review", channel="manual",
        )
        if not success:
            return False, "状态转移失败"

        # 清除评审相关字段
        self.state_machine.update_spec(
            spec_name,
            {
                "reviewer_run": None,
                "_review_attempts": 0,
                # 与本文件四处通过/收口站点对齐清零否决计数（code-review item
                # 10592411f0b1）：曾记录过否决的 spec 担责放行后再次走评审时，
                # 陈旧计数会使首次 rejected 即达 MAX_REJECT_REDO 冻结转人工，
                # 跳过「初次否决 + 复评确认」的有界自动复评契约。
                "_review_rejections": 0,
                "error": None,
            },
        )
        # 触发实现调度（pm_engine None 守卫，code-review item 5ee4abf84768）：
        # CLI（bin/fenix_cli.py: cmd_review）与 Dashboard
        # （core/dashboard/data/admin_actions.re_review_spec）均以
        # SpecReviewManager(proot, sm, None, None, {}, logger) 构造——与 re_review
        # 的 `if self.agent_runner is not None and self.pm_engine is not None` 同款
        # 守卫缺失时，blocked→ready 已提交成功后会在本行抛 AttributeError，调用方
        # 拿不到结果而状态已变更。此处按 None 跳过派发（状态已在 ready，由 daemon
        # full_scan recovery 兜底拾取）。
        if self.pm_engine is not None:
            self.pm_engine._on_spec_ready(spec_name)
        return True, "担责放行已触发"
