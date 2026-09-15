"""
admin_monitor.py — 轻量健康监视器（零 LLM 成本）。

daemon 内独立线程周期性读取本地数据（STATE.md、.fenix/runs/ 转录、fenixd.log），
按规则检测 Agent 无法自行脱困的困境信号。检测到困境且节流通过时，
回调 agent_runner 唤起 Administrator Agent（见 administrator-agent spec）。

检测规则（design D2 / admin-health-monitor spec）：
  - repeated_failures  窗口内同 spec 失败 run ≥ 阈值（默认 30 分钟 ≥3 次）
  - flapping           窗口内同 spec ready↔implementing 状态切换 ≥ 阈值（默认 10 分钟 ≥3 次）
  - stuck              implementing/testing 超 stuck_threshold_minutes 且无 run 进度
  - merge_streak       _merge_streak 已达熔断阈值仍滞留（merge-back 反复失败）
  - daemon_errors    10 分钟窗口内同指纹 ERROR 复现 ≥2 次且最近两次间隔 ≤5 分钟

节流（D2）：同 spec 同类信号在 admin.escalation_cooldown_minutes 内只唤起一次，
依据 .fenix/admin_alerts.json 中的 signal 记录与未处理升级告警。

纯本地数据、零 LLM：本模块任何路径都不调用 claude / LLM API。
"""

import hashlib
import json
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .admin_store import AdminStore, SIGNAL, ESCALATION, DISPOSITION
from .alert_lifecycle import attach_trigger, find_resolvable
# add-blocked-reverify-lane D2：env 阻塞复位判定与复位路径常量
from core.pm_engine.verification import (
    ENV_BLOCK_SIGNAL_TYPES,
    resolve_env_blocked_reset_path,
)

# frozen-scenario-schema-migration D3：处置后自动复位集合。
# blocked_stuck 与 env 阻塞族同语义加入自动复位：admin 处置成功
# （result=resolved/partially-resolved）且根因已修复 → 复用
# resolve_env_blocked_reset_path 既有复位路径（实现分支已合并→testing
# 直通重验，否则→ready），消除 blocked_stuck 处置成功后二次空转。
# MUST NOT 恢复任何错误业务判定——只复位阻塞态，复位守卫（frozen/
# 非 blocked）由 resolve_env_blocked_reset_path 判定。
DISPOSITION_AUTO_RESET_SIGNAL_TYPES = ENV_BLOCK_SIGNAL_TYPES + ("blocked_stuck",)

# admin-signal-consolidation D2：悬置强制升级的信号族（blocked_stuck + ENV 阻塞族）。
# 悬置类信号 = spec 保持 blocked 状态过久、自动处置通道已被冷却压制——此时
# 强制升级真人（突破 latest_signal 冷却）。其他信号类型（stuck/flapping/
# repeated_failures/daemon_errors…）维持既有 cooldown 节流，不得外溢。
STALLED_ESCALATION_SIGNAL_TYPES = DISPOSITION_AUTO_RESET_SIGNAL_TYPES

# 默认阈值（design D2）
REPEAT_FAILURE_WINDOW_MINUTES = 30
REPEAT_FAILURE_THRESHOLD = 3
FLAPPING_WINDOW_MINUTES = 10
FLAPPING_THRESHOLD = 3
# ── daemon-error-escalation D5/D7：daemon_errors 升级口径常量 ──────
# DAEMON_ERROR_THRESHOLD 语义从「尾部物理连续条数」改为「10 分钟窗口内同指纹
# 最少复现次数」；升级还需最近两次同指纹条目间隔 ≤ MAX_GAP。全部保持模块常量
# 不进 config（规避"新增配置项必须带 Dashboard UI"约束）。
DAEMON_ERROR_THRESHOLD = 2
DAEMON_ERROR_WINDOW_MINUTES = 10
DAEMON_ERROR_RECURRENCE_MAX_GAP_MINUTES = 5
STUCK_GRACE_MINUTES = 10  # run 文件 mtime 距现在小于此值视为"有进度"，不算卡死
RESTART_REQUEST_TIMEOUT_MINUTES = 10  # restart_request 超时未清除 → 重启失败 → 升级

# admin-signal-consolidation D2：blocked 悬置强制升级阈值（模块常量不入 config，
# 对齐本模块既有常量做法，规避"新增配置项必须带 Dashboard UI"约束）。
# 悬置时长口径 = now − spec.updated（spec 保持同一 blocked 状态的时长），
# 不是信号记录 first_seen（后者含 max(cooldown,15) 阈值延迟，会晚一小时余才触发）。
STALLED_ESCALATION_MINUTES = 120

# family_explosion 放行文本兜底：仅当处置文本表达「显式放行」语义时才写豁免位。
# 2026-08-28 实证（fix-fix-fix-add-spec-context-menu）：旧的「包含 _family_waiver/
# 放行/waive 令牌即放行」宽松匹配，把处置叙述中否定句里的字面令牌（如
# 「明确不发放 _family_waiver」）误判为放行动作，给未放行的父 SPEC 错误写入
# _family_waiver=true。改为：命中否定短语即不放行；否则须命中赋值型/明确动词型
# 放行模式才写位。
# 2026-08-28 二次实证（fix-fix-fix-improve-failover-model-mapping-ui，admin run
# 1787945929）：否定清单缺「未发放/未放行」等完成时否定，且赋值型模式命中了处置
# 叙述里对【另一族谱】豁免位的提及（「全库唯一的 _family_waiver=true 在另一族谱」
# ——与本困境无关），双重误判给已终态父 SPEC 错误写入 _family_waiver=true。
# 修正：a) 否定清单补完成时/委婉否定；b) 赋值型/动词型模式须与「放行」动词在同句
# 才算放行（单纯提及字段名/他族谱状态不构成放行）。
_WAIVER_NEGATION_PHRASES = (
    "未放行", "不放行", "拒绝放行", "不予放行", "不发放", "未发放",
    "不启用豁免", "未启用豁免", "不予豁免", "无须放行", "无需放行", "不必放行",
)
_WAIVER_GRANT_PATTERNS = (
    r"同意放行",
    r"放行一次",
    r"经评估放行",
    r"设置\s*_family_waiver\s*为?\s*true",  # 设置 _family_waiver 为 true
)
# 赋值型 _family_waiver=true 必须与放行动词同句（。！？\n 分句）才算显式放行，
# 防止叙述中对字段名/其他族谱豁免状态的提及被误判为本次处置的放行动作。
_WAIVER_ASSIGN_RE = re.compile(r"_family_waiver['\"]?\s*[=:：]\s*['\"]?true")

# 「写入即待唤起」信号的终态守卫：spec 已达这些状态时不再唤起 Administrator
# （done/pushed 之后族谱不可能再派生，困境实质已消失）。
_TERMINAL_SPEC_STATUSES = ("done", "pushed")

# 信号 → 严重度/建议处置
SIGNAL_SEVERITY = {
    "repeated_failures": "major",
    "flapping": "major",
    "stuck": "major",
    "merge_streak": "critical",
    "blocked_stuck": "critical",
    "daemon_errors": "critical",
    "family_explosion": "major",
    "dispatch_stalled": "major",
    "verify_contract_missing": "major",
    # add-verdict-credibility-gate / design D6：连续 blocked-env 达阈值唤起
    # Administrator 核查验证环境（repeated_failures/stuck/blocked_stuck 三层
    # 检测口径均实证错过该故障形态，独立升级通道不依赖它们）。
    "inconclusive_loop": "major",
    # fix-verify-contract-signal-semantics B：契约有效 + 用户显式覆盖确认的重起草信号
    "verify_contract_redraft": "major",
    # fix-mergeback-stashpop-silent-loss D1：pop 冲突自愈丢弃的用户改动，
    # 内容找回需人工核对（stash 栈 + 逐文件 git show），major 级。
    "stash_pop_conflict": "major",
    # fix-verify-uniform-failure-consumer：全场景同因失败（pass=0 且失败签名
    # 一致）——既可能是验证环境/夹具问题，也可能是场景本身缺陷；admin 需判类
    # 后走对应处置路径，不直接判 bug-found（同因哨有意不派生 fix）。
    "verify_uniform_failure": "major",
}
SIGNAL_RECOMMENDATION = {
    "repeated_failures": "检查重复失败的根因（如构建/测试命令错误），必要时重置 spec 状态或修复框架配置",
    "flapping": "检查 spec 状态机空转回路（ready↔implementing），修复派发/恢复逻辑或人工介入",
    "stuck": "检查卡死 Agent 子进程（kill 并按需重启），或重置 spec 状态重新调度",
    "merge_streak": "检查 merge-back 冲突根因（stash/分支冲突），清理 git 状态后重新 merge",
    "blocked_stuck": "检查 blocked 是否误置（误判派生的假 spec）或确需人工决策；清理假 spec 或重置后重新调度，必要时升级",
    "daemon_errors": "检查 fenixd 重复 ERROR 的根因（同错误 10 分钟窗口内复现 ≥2 次），必要时重启 daemon",
    "family_explosion": "检修根因环境（如验证报告互相咬合导致 fix 递归）；确认放行一次则对父 SPEC 设置 _family_waiver=true",
    "dispatch_stalled": "检查持锁进程是否为孤儿（ps/pgrep 确认后 kill），清理残留 worktree 锁后让 spec 重新派发",
    # add-verdict-credibility-gate / design D6：处置建议指向环境核查 + 恢复路径
    "inconclusive_loop": "验证环境核查清单：① 被测实例是否就绪（serve/start 命令与端口）；② 资源与并行度（max_parallel 是否挤爆实例）；③ mock+SSE 链路（mock_api 是否误拦推流、SSE 是否断流）；④ 探针摘要（见 evidence 末轮 blocked_env 数）。恢复路径：人工处置后解冻 spec（unfreeze）并清 `_inconclusive_attempts`，后续 blocked-env 轮次从 1 重新计数",
    "verify_contract_missing": "Administrator 起草 .fenix/verify.yaml 验证契约：检查项目构建命令、静态目录、服务启动方式；草稿写临时路径 → bin/fenix_verify_contract.py 自证 → 全通才落位 → git 提交 → spec 复位 ready 触发重验证",
    # fix-verify-contract-signal-semantics B：覆盖重起草指引——先复核现有契约有效性；
    # 有效契约按 D4 权限边界默认不碰，用户已显式授权覆盖（evidence 含「覆盖确认=是」）
    # 时方可重起草；重起草草稿同样须经 bin/fenix_verify_contract.py 三段自证全通才落位。
    "verify_contract_redraft": "复核现有契约有效性：若契约仍有效，Administrator 按权限边界默认不碰，仅当用户已显式授权覆盖（evidence 含「覆盖确认=是」）时方可重起草；重起草草稿写临时路径 → bin/fenix_verify_contract.py 自证 → 全通才落位 → git 提交 → spec 复位 ready 触发重验证",
    # fix-mergeback-stashpop-silent-loss D1：核对指引——查 stash 栈确认条目去向，
    # 按 sha / 逐文件 git show 找回被自愈丢弃的改动，确认无独有内容后可清理条目。
    "stash_pop_conflict": "merge-back stash pop 冲突已自愈，主树已恢复可写但部分未提交改动被丢弃：git stash list 查条目去向（保留/drop + sha）；按告警中逐文件 git show <sha>:<file> 命令核对内容，仍需要的改动手动落回工作区；确认零独有内容后 git stash drop 清理",
    # add-blocked-reverify-lane D2：env 阻塞处置建议同步复位收敛措辞——
    # 处置范围限于环境修复，result 写入后框架自动判定复位路径（实现分支已合并→
    # 直通道 testing 重验，否则→ready），无需手动 reset spec 状态。
    "verify_env_blocked": "验证环境阻塞（依赖/服务/端口问题）：Administrator 仅需修复环境；处置完成写 result 后框架自动判定复位路径（实现分支已合并→直通道 testing 重验；否则→ready 重实现），无需手动 reset spec 状态",
    # fix-verify-uniform-failure-consumer：全场景同因失败的分诊指引——先判失败
    # 类别再处置，勿直接当产品缺陷打回实现（同因哨有意不派生 fix）。
    "verify_uniform_failure": "全场景同因失败（pass=0 且失败签名一致），先判类别：① 验证夹具/环境缺失（如场景引用的辅助脚本/依赖在验证树不可达）→ 补齐验证基础设施后复位重验；② 场景本身缺陷（断言写错误、字段/协议不对）→ 修正场景文件 test_scenarios.json 与 scenarios.json 后复位重验；③ 确为产品缺陷（多场景同根因）→ 转人工决策是否打回实现。证据见本信号 evidence 的签名与 failed 计数，逐场景细节见 .fenix/verify-progress/<spec>/report.json",
}

# pm_engine 直接写入 store、由本监视器摄取唤起的信号类型（写入即待唤起型）。
# family_explosion 既有；dispatch_stalled 属 run 生命周期治理（锁冲突退避耗尽 /
# 恢复闭环复查未通过）；stash_pop_conflict 属 merge-back pop 冲突可视治理
# （fix-mergeback-stashpop-silent-loss D1）。
STORED_SIGNAL_TYPES = (
    "family_explosion", "dispatch_stalled", "verify_contract_missing",
    "stash_pop_conflict", "verify_contract_redraft",
    # add-verdict-credibility-gate / design D6：连续 blocked-env 达阈值时
    # pm_engine 写入、本监视器摄取唤起（写入即待唤起型，recovery 尊重暂停
    # 标记，人工处置是唯一出路）。
    "inconclusive_loop",
    # 2026-09-14 原地修复（未走 SPEC）：全场景同因失败哨
    # （verification.py `_detect_uniform_verify_failure`）在 pass=0 且失败签名
    # 一致时写入本信号，文案自称「已呼叫 admin 介入判断」——但此前本表不含该
    # 类型，记录落 store 后无人摄取，信号石沉大海。事故实证：evo-planner-
    # scenario-schema-alignment 09-14 两轮 13/13 同因失败（验证夹具随 worktree
    # 清理丢失，写端非产品缺陷），两条信号 handled=False 悬置十余小时，夹具
    # 从未恢复，直到人工介入。补入本表后由 _detect_family_explosion 摄取唤起。
    "verify_uniform_failure",
)

# run_id 前缀 → 计入"失败 run"的 agent 类型
# ⚠️ 与 core/agent_runner/run_files.py:run_spec_part 前缀元组同源互指，新增 run
# 前缀（如 add-deliverable-declaration-triage 的 dispute-judge-）两处必须同步。
_RUN_PREFIXES = ("impl-", "verify-", "planner-plan-", "planner-judge-",
                 "dispute-judge-", "spec-review-", "admin-")

# ── daemon-error-escalation D6：错误指纹归一化（保守集）────────────
# 只归一化四类：ISO-8601 时间戳→@、UUID→~、≥16 位 hex→~、纯数字序列→#。
# 不动路径与文字骨架——过度归一化会把不同错误误聚合，而"≥2 次才升级"已提供缓冲。
_ISO_TS_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_HEX16_RE = re.compile(r"[0-9a-fA-F]{16,}")
# 独立数字 token（不被字母/下划线包围）——run_id、attempt 计数、epoch、超时秒数等
_STANDALONE_NUMBER_RE = re.compile(r"(?<![0-9a-zA-Z_])\d+(?![0-9a-zA-Z_])")


def _normalize_error_message(message: str) -> str:
    """err message 归一化（improve-hot-reload-robustness D6 保守集）。

    顺序：先按 ISO 时间戳（含日期骨架）、UUID、hex 三类带字母形态替换，最后替换
    独立数字序列——防止 hex 中的数字被先行拆散。
    """
    msg = str(message)
    msg = _ISO_TS_RE.sub("@", msg)
    msg = _UUID_RE.sub("~", msg)
    msg = _HEX16_RE.sub("~", msg)
    msg = _STANDALONE_NUMBER_RE.sub("#", msg)
    return msg


def _error_fingerprint(component: str, message: str) -> str:
    """错误指纹 = sha1(component + "\\x00" + normalize(message))（D6）。

    同一 source 同一错误骨架（仅内嵌时间戳/UUID/数字不同）→ 同指纹复现成立；
    不同错误 message 骨架不同 → 指纹不同、不聚合升级。
    """
    raw = f"{component or ''}\x00{_normalize_error_message(message)}"
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()


# 尾部读上限：日志增长后每轮巡检只 seek 最近 256KB（3.5），避免全量 read_text
_TAIL_ERROR_READ_BYTES = 256 * 1024


class AdminMonitor:
    """困境信号检测 + 节流 + 唤起调度。run_once() 为单次检测入口。"""

    def __init__(self, config: dict, state_machine, project_root, logger,
                 store=None, agent_runner=None, pm_engine=None):
        from .config import ConfigLoader
        self.config = config
        self.admin_cfg = ConfigLoader.get_admin_config(config)
        self.state_machine = state_machine
        self.project_root = Path(project_root)
        self.logger = logger
        self.store = store if store is not None else AdminStore(self.project_root, logger)
        # agent_runner 提供 run_administrator(signal)；None 时只检测、不唤起（测试/禁用态）
        self.agent_runner = agent_runner
        # pm_engine 提供 handle_event/spec_implemented 入队（add-blocked-reverify-lane
        # D2）：env 阻塞处置收尾复位到 testing 后经此派发 verifier 重验；None 时
        # 仅复位状态、不派发（测试替身/独立组件最小上下文），重派由 recovery 兜底。
        self.pm_engine = pm_engine
        self._history_path = self.project_root / ".fenix" / "admin_state_history.json"
        # add-alert-auto-resolve D4：启动首轮扫描执行存量回填（仅一次）
        self._lifecycle_backfilled = False

    # ── 配置读取 ────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self.admin_cfg["enabled"])

    @property
    def interval_minutes(self) -> float:
        return float(self.admin_cfg["interval_minutes"])

    @property
    def cooldown_minutes(self) -> float:
        return float(self.admin_cfg["escalation_cooldown_minutes"])

    def _get_config(self, key: str, default=None):
        from .config import ConfigLoader
        return ConfigLoader.get(self.config, key, default)

    # ── 主入口 ──────────────────────────────────────────────────

    def has_in_progress_specs(self) -> bool:
        """是否存在进行中 spec（implementing/testing）——检测前置条件。"""
        for entry in self.state_machine.read_all().values():
            if entry.get("status") in ("implementing", "testing"):
                return True
        return False

    def run_once(self) -> list:
        """执行一次完整检测：识别信号 → 记录 → 节流判定 → 唤起 Administrator。

        返回本次检测到的信号列表（供测试/审计）。
        """
        if not self.enabled:
            return []

        # 族谱爆炸信号由 pm_engine 在拦截时直接写入 store（父 SPEC 保持 bug-found，
        # 不满足 has_in_progress_specs 门控，却同样需要送达 Administrator）。
        # 该摄取在门控之前完成：_detect_family_explosion 内部直接唤起 Administrator
        # 并把源记录标记 escalated，返回仅供审计/测试（不再经 _handle_signal 节流，
        # 否则 pm_engine 刚写入的 SIGNAL 记录会被 latest_signal 误判为「已唤起」）。
        family_signals = self._detect_family_explosion()

        if not self.has_in_progress_specs():
            # 假就绪盲区修复（improve-run-lifecycle-governance D6）：无 in-progress
            # spec 只说明没有运行态任务，MUST NOT 成为跳过整轮巡检的理由——
            # ready 滞留（假就绪）、blocked_stuck、daemon_errors 等非运行态检查
            # 仍然必须执行（2026-08-27 事故：假 ready 滞留近 1 小时无人发现）。
            self.logger.debug(
                "admin_monitor",
                "No in-progress SPECs — continuing non-running-state scans",
            )

        specs = self.state_machine.read_all()
        now = time.time()
        regular = self._detect(specs, now)

        for signal in regular:
            self._handle_signal(signal)

        # fix-admin-self-heal：孤儿处置与重启失败的兜底升级（非 per-spec 信号）
        self._recover_orphaned_dispositions()
        self._detect_restart_failure(now)

        # admin-signal-consolidation D2：blocked 悬置 ≥2h 强制升级真人
        # （突破节流、受未处理告警约束；不重新唤起 Administrator）
        self._force_escalate_stalled(specs, now)

        # add-alert-auto-resolve D1：告警自动闭环扫描内联本巡检执行（不新增
        # 线程/定时器），复用当轮已读取的 STATE.md 状态表（design D3）
        try:
            self._run_alert_lifecycle(specs)
        except Exception as e:
            self.logger.error(
                "admin_monitor", f"Alert lifecycle scan failed: {e}")

        # add-daily-self-review：每日自省调度检查点（design D1，挂在既有巡检
        # 循环，不新增线程/定时器）。enabled && 本地时间 ≥ run_at && 今日未执行
        # → 触发；enabled=false 全链路零动作。任何异常只记日志不阻断巡检。
        try:
            self._run_self_review_checkpoint()
        except Exception as e:
            self.logger.error(
                "admin_monitor", f"Self-review checkpoint failed: {e}")
        return family_signals + regular

    def _run_self_review_checkpoint(self) -> dict:
        """每日自省调度检查点（add-daily-self-review）。

        延迟构造 SelfReviewScheduler（避免启动时导入链副作用），把 config/
        state_machine/agent_runner 透传进去，由 scheduler.check_and_run 完成
        判定与执行。返回调度结果 dict（供测试断言；巡检本身不消费返回值）。
        """
        from .self_review import SelfReviewScheduler
        scheduler = SelfReviewScheduler(
            config=self.config,
            project_root=self.project_root,
            logger=self.logger,
            state_machine=self.state_machine,
            agent_runner=self.agent_runner,
            store=self.store,
        )
        return scheduler.check_and_run()

    def _run_alert_lifecycle(self, specs: dict) -> int:
        """告警自动闭环扫描（add-alert-auto-resolve design D1/D3/D4）。

        判定为纯函数（alert_lifecycle.find_resolvable）：输入未闭环告警 +
        当轮 STATE.md 状态表，输出可闭环条目；写回经 AdminStore.auto_resolve
        在其排他锁内完成（不绕锁）。无未闭环告警时不做写回、无可闭环条目时
        零写回（admin_alerts.json mtime 不变）。返回实际闭环数量。

        daemon 启动首轮扫描（_lifecycle_backfilled=False）附带存量回填：
        无 trigger 字段的 verify_fail_escalation / blocked_stuck 告警按
        signal_type 推断 condition 走同一判定路径，resolve_note 注明
        「存量回填」。
        """
        records = self.store.read_all()
        pending = [
            r for r in records
            if r.get("kind") == ESCALATION and not r.get("handled")
        ]
        if not pending:
            self._lifecycle_backfilled = True
            return 0  # 无待闭环告警：零写回
        backfill = not self._lifecycle_backfilled
        self._lifecycle_backfilled = True
        resolvable = find_resolvable(pending, specs, backfill=backfill)
        if not resolvable:
            return 0
        resolved = self.store.auto_resolve(resolvable)
        for item in resolvable:
            self.logger.info(
                "admin_monitor",
                f"alert auto-resolved: id={item.get('id')} "
                f"spec='{item.get('spec')}' — {item.get('resolve_note')}",
            )
        if resolved:
            self.logger.warning(
                "admin_monitor",
                f"alert lifecycle: auto-resolved {resolved}/{len(resolvable)} "
                f"stale alert(s)"
                + ("（存量回填）" if backfill else ""),
            )
        return resolved

    # ── 检测规则 ────────────────────────────────────────────────

    def _detect(self, specs: dict, now: float) -> list:
        """运行全部检测规则，返回信号列表。"""
        signals = []
        signals.extend(self._detect_repeated_failures(specs, now))
        signals.extend(self._detect_flapping(specs, now))
        signals.extend(self._detect_stuck(specs, now))
        signals.extend(self._detect_merge_streak(specs))
        signals.extend(self._detect_blocked_stuck(specs, now))
        signals.extend(self._detect_daemon_errors(now))
        return signals

    def _detect_blocked_stuck(self, specs: dict, now: float) -> list:
        """blocked 状态超时未处理 → 唤起 admin 处置（fix-admin-self-heal）。

        熔断把 spec 置 blocked 后等待人工；但部分 blocked 是误置（如误判派生的
        假 spec），且人工未必及时看到。超过阈值仍滞留 → 交给 admin 判定是清理
        还是升级。
        """
        signals = []
        threshold = max(self.cooldown_minutes, 15)
        for name, entry in specs.items():
            if entry.get("status") != "blocked":
                continue
            # 人工冻结豁免（fix-restart-dual-dispatch S4）：结构化 frozen 字段是
            # 首要判定——freeze_spec() 统一入口写入，不依赖文案。文本匹配保留为
            # 存量 spec 的兼容回退（历史 error 未迁移）。
            # 冻结豁免：Administrator 为去重/家族收敛而人为冻结的 spec（error 前缀
            # 'frozen:'），其 blocked 是有意保持的等待态，updated 不会推进——按超时
            # 唤起只会形成每轮重复误报。真实停滞仍由 stuck/repeated_failures/
            # family_explosion 等规则覆盖。
            # 用户指令暂停/冻结（2026-08-30 v2-acceptance-suite 误报）：人工直接
            # 写入的「用户指令暂停：…」「用户指令冻结：…」同样是有意等待态，等价
            # 于 frozen——人工历史文案未必带 frozen: 前缀，且用词在暂停/冻结间
            # 漂移，故按「用户指令」子串识别，双保险。
            err = str(entry.get("error") or "")
            if entry.get("frozen") or err.startswith("frozen:") or "用户指令" in err:
                self.logger.debug(
                    "admin_monitor",
                    f"Skipping blocked_stuck for intentionally-paused SPEC '{name}'",
                )
                continue
            updated_str = entry.get("updated") or entry.get("created") or ""
            try:
                updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            elapsed = (now - updated.timestamp()) / 60
            if elapsed <= threshold:
                continue
            signals.append(self._make_signal(
                "blocked_stuck", name,
                f"'{name}' 处于 blocked 超过 {int(elapsed)} 分钟未处理",
                f"updated={updated_str}，阈值 {threshold} 分钟",
            ))
        return signals

    def _detect_family_explosion(self) -> list:
        """摄取 pm_engine 直接写入 store 的「写入即待唤起」信号并唤起 Administrator。

        pm_engine 在族谱越界拦截时（design D4）与锁冲突退避耗尽 / 恢复闭环复查
        未通过时（improve-run-lifecycle-governance D5/D6）向 admin store 写入
        kind=SIGNAL 记录（family_explosion / dispatch_stalled），但常规检测规则
        只读 STATE/runs，不会发现它们；且 pm_engine 没有 agent_runner，无法自唤起。
        本规则在 run_once 中摄取这批记录（STORED_SIGNAL_TYPES）：
        - 每条未 escalated 的记录 → 转为信号、标记 escalated、直接唤起 Administrator
          （family_explosion 处置可对父 SPEC 放行一次 → _family_waiver）。
        - 已 escalated 的记录跳过（同记录不反复唤起）。

        返回本次摄取的信号列表（仅审计/测试用；唤起动作在内部完成）。
        """
        signals = []
        for rec in self.store.read_all():
            if rec.get("kind") != SIGNAL:
                continue
            if rec.get("signal_type") not in STORED_SIGNAL_TYPES:
                continue
            if rec.get("escalated"):
                continue  # 已唤起过，跳过
            stype = rec.get("signal_type")
            # 手动触发信号（source=ui-manual）无关联 spec，项目名从 evidence 携带
            spec = rec.get("spec")
            if not spec and stype in ("verify_contract_missing", "verify_contract_redraft"):
                # 从 evidence 提取项目名（格式: "项目名=<name>; ..."）
                evidence = rec.get("evidence") or ""
                for part in evidence.split(";"):
                    part = part.strip()
                    if part.startswith("项目名="):
                        spec = part.split("=", 1)[1].strip()
                        break
            if not spec:
                continue
            stype = rec.get("signal_type")
            # 终态守卫（fix-family-explosion-loop 2026-08-28）：信号指向的 spec 若已
            # 终态（done/pushed），困境实质已消失——族谱成员均已合并推送、无派生口子
            # 可开，唤起 Administrator 只会得到「已收敛」的重复处置（实证：同一天
            # fix-fix-fix-improve-failover 族谱因一条陈旧未 escalated 的 SIGNAL 记录
            # 被连续唤起 4 次）。直接标记 escalated 跳过，下一 tick 不再重捞。
            try:
                spec_entry = self.state_machine.read_one(spec) or {}
            except Exception:
                spec_entry = {}
            if (spec_entry.get("status") or "") in _TERMINAL_SPEC_STATUSES:
                marked = self.store.mark_escalated(rec.get("id"))
                self.logger.info(
                    "admin_monitor",
                    f"{stype}: spec '{spec}' 已终态"
                    f"（status={spec_entry.get('status')}），跳过唤起"
                    f"（mark_escalated={'ok' if marked else '未命中'}）",
                )
                continue
            signal = self._make_signal(
                stype, spec,
                rec.get("description") or (
                    "fix 族谱越界派生被拦截" if stype == "family_explosion"
                    else "派发长期被 worktree 锁冲突滞留" if stype == "dispatch_stalled"
                    else "连续多轮验证全部为环境性失联（blocked-env）"
                        if stype == "inconclusive_loop"
                    else "AI 起草验证契约请求（UI 手动触发）"
                ),
                rec.get("evidence") or "拦截详情见 pm_engine 日志",
            )
            signals.append(signal)
            # 先落 escalated 再唤起：即使唤起过程异常中止，下一 tick 也会跳过该记录
            marked = self.store.mark_escalated(rec.get("id"))
            if not marked:
                # 留痕：mark 未命中意味着该记录下一 tick 会被重捞，可能形成重复唤起
                self.logger.warning(
                    "admin_monitor",
                    f"{stype}: mark_escalated 未命中记录 id={rec.get('id')}"
                    f"（spec={spec}），该记录可能被反复摄取",
                )
            self.logger.warning(
                "admin_monitor",
                f"{stype}: invoking Administrator for '{spec}'",
                {"signal": signal},
            )
            self._invoke_administrator(signal, rec)
        return signals

    def _make_signal(self, signal_type: str, spec, description: str, evidence: str) -> dict:
        return {
            "signal_type": signal_type,
            "spec": spec,
            "severity": SIGNAL_SEVERITY.get(signal_type, "major"),
            "description": description,
            "evidence": evidence,
            "recommended_action": SIGNAL_RECOMMENDATION.get(signal_type, ""),
        }

    def _detect_repeated_failures(self, specs: dict, now: float) -> list:
        """窗口内同 spec 失败 run ≥ 阈值。"""
        signals = []
        window = REPEAT_FAILURE_WINDOW_MINUTES * 60
        cutoff = now - window
        runs_dir = self.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return signals
        try:
            files = list(runs_dir.glob("*.jsonl"))
        except OSError:
            return signals

        per_spec: dict = {}
        for p in files:
            mtime = p.stat().st_mtime
            if mtime < cutoff:
                continue
            spec = self._spec_from_run_id(p.stem)
            if not spec:
                continue
            if self._run_terminal_status(p) != "error":
                continue
            per_spec.setdefault(spec, 0)
            per_spec[spec] += 1

        for spec, count in per_spec.items():
            if count >= REPEAT_FAILURE_THRESHOLD:
                signals.append(self._make_signal(
                    "repeated_failures", spec,
                    f"'{spec}' 在 {REPEAT_FAILURE_WINDOW_MINUTES} 分钟内出现 {count} 次失败 run",
                    f"最近失败 run ≥{REPEAT_FAILURE_THRESHOLD}（{count} 次），窗口 {REPEAT_FAILURE_WINDOW_MINUTES} 分钟",
                ))
        return signals

    def _detect_flapping(self, specs: dict, now: float) -> list:
        """窗口内 ready↔implementing 切换 ≥ 阈值。

        依赖 .fenix/admin_state_history.json 中本监视器各周期记录的状态变更历史
        （每次检测把当前快照与上次对比，状态变化才追加一条）。
        """
        self._update_history(specs, now)
        history = self._load_history()
        window = FLAPPING_WINDOW_MINUTES * 60
        cutoff = now - window
        signals = []
        for spec, rec in history.items():
            changes = rec.get("changes") if isinstance(rec, dict) else None
            if not changes:
                continue
            in_window = [c for c in changes if c[0] >= cutoff]
            if len(in_window) < 2:
                continue
            transitions = len(in_window) - 1
            if transitions >= FLAPPING_THRESHOLD:
                seq = " → ".join(c[1] for c in in_window[-FLAPPING_THRESHOLD:])
                signals.append(self._make_signal(
                    "flapping", spec,
                    f"'{spec}' 在 {FLAPPING_WINDOW_MINUTES} 分钟内 ready↔implementing 切换 {transitions} 次",
                    f"状态序列: {seq}",
                ))
        return signals

    def _detect_stuck(self, specs: dict, now: float) -> list:
        """implementing/testing 超阈值无 run 进度。"""
        signals = []
        threshold_minutes = self.admin_cfg["stuck_threshold_minutes"]
        grace_minutes = max(STUCK_GRACE_MINUTES, self.interval_minutes * 2)
        runs_dir = self.project_root / ".fenix" / "runs"
        for name, entry in specs.items():
            status = entry.get("status")
            if status not in ("implementing", "testing"):
                continue
            # 取消保持豁免（fix-cancel-holdstate-recovery D5）：人工取消的
            # hold spec 是有意等待态，不产生 stuck 信号、不自动升级
            # Administrator（自动升级可能自行复位，破坏「我来决定何时重派」
            # 的人工决策）。唯一出路是显式复位（update_spec 携带 status）。
            if entry.get("_cancelled_hold"):
                continue
            updated_str = entry.get("updated") or entry.get("created") or ""
            try:
                updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            elapsed_minutes = (now - updated.timestamp()) / 60
            if elapsed_minutes <= threshold_minutes:
                continue
            if self._has_recent_progress(name, runs_dir, now, grace_minutes * 60):
                continue
            signals.append(self._make_signal(
                "stuck", name,
                f"'{name}' 卡在 {status} 超过 {int(elapsed_minutes)} 分钟且无 run 进度",
                f"updated={updated_str}，阈值 {int(threshold_minutes)} 分钟",
            ))
        return signals

    def _detect_merge_streak(self, specs: dict) -> list:
        """_merge_streak 已达熔断阈值仍滞留（merge-back 反复失败）。"""
        signals = []
        threshold = int(self.admin_cfg["merge_breaker_threshold"])
        for name, entry in specs.items():
            try:
                streak = int(entry.get("_merge_streak", 0) or 0)
            except (TypeError, ValueError):
                continue
            if streak < threshold:
                continue
            status = entry.get("status")
            if status not in ("ready", "implementing", "blocked"):
                continue
            fp = entry.get("_merge_fp") or "unknown"
            signals.append(self._make_signal(
                "merge_streak", name,
                f"'{name}' merge-back 连续失败 {streak} 次已达熔断阈值仍滞留（{status}）",
                f"_merge_streak={streak}，指纹={fp}",
            ))
        return signals

    def _detect_daemon_errors(self, now: float) -> list:
        """fenixd.log：10 分钟窗口内同指纹 ERROR 复现 ≥2 次且最近两次间隔 ≤5 分钟
        → daemon_errors critical signal（daemon-error-escalation D5）。

        无状态每轮巡检重算（读尾部即得，不持久化计数器、daemon 重启安全）；恢复
        靠窗口滑动自然过期（重载成功不写 ERROR，10 分钟后自动归零）。中间被
        INFO/WARNING/其他错误打断不影响同指纹复现计数；单条瞬时错误不升级；
        两条不同错误各 1 次不聚合（指纹不同）。
        """
        log_file = self.project_root / ".fenix" / "logs" / "fenixd.log"
        if not log_file.exists():
            return []
        window = DAEMON_ERROR_WINDOW_MINUTES * 60
        max_gap = DAEMON_ERROR_RECURRENCE_MAX_GAP_MINUTES * 60

        by_fp: dict = {}
        for ts, component, message in self._read_tail_error_entries(log_file):
            by_fp.setdefault(_error_fingerprint(component, message), []).append(ts)

        signals = []
        for fp, stamps in by_fp.items():
            in_window = [t for t in stamps if t is None or (now - window <= t <= now)]
            if len(in_window) < DAEMON_ERROR_THRESHOLD:
                continue
            ts_ok = sorted(t for t in in_window if t is not None)
            if len(ts_ok) >= 2 and (ts_ok[-1] - ts_ok[-2]) > max_gap:
                continue
            count = len(in_window)
            last_ts = ts_ok[-1] if ts_ok else None
            last_str = (
                datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat()
                if last_ts else "无可用时间戳"
            )
            missing_ts = sum(1 for t in in_window if t is None)
            sig = self._make_signal(
                "daemon_errors", None,
                f"fenixd 日志同错误（指纹 {fp[:8]}）在 {DAEMON_ERROR_WINDOW_MINUTES} 分钟"
                f"窗口内复现 {count} 次，建议检查根因并重启 daemon",
                f"同指纹 ERROR 复现 {count} 次（最近一次 {last_str}"
                + (f"；{missing_ts} 条缺时间戳按窗口内计入" if missing_ts else "")
                + f"）；升级条件：同指纹 ≥{DAEMON_ERROR_THRESHOLD} 次且最近两次间隔"
                f" ≤{DAEMON_ERROR_RECURRENCE_MAX_GAP_MINUTES} 分钟",
            )
            # admin-signal-consolidation D1：daemon 级信号（spec=None）的
            # status_hash 回退判据 = 稳定错误指纹（_signal_status_hash 消费，
            # 不落库——signal 字典仅作本次检测的传递载体）。
            sig["_fp"] = fp
            signals.append(sig)
        return signals

    @staticmethod
    def _parse_error_line(line: str):
        """解析单行日志为 (ts_epoch|None, component, message)；非 ERROR JSON 行返回 None。

        逐行 JSON 解析（logger 保证单行 JSON、\\n 已转义，多行 traceback 安全）；
        非 JSON 行（旧格式/fixture/traceback 原文）回退 raw 归一化且 timestamp 置
        None——fail-closed 仍计入指纹桶（D6：宁可多告警不漏告警）。timestamp
        缺失/解析失败同样置 None。
        """
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return None, "raw", line
        if not isinstance(entry, dict) or entry.get("level") != "ERROR":
            return None
        ts_epoch = None
        ts = entry.get("timestamp")
        if ts:
            try:
                ts_epoch = datetime.fromisoformat(
                    str(ts).replace("Z", "+00:00")
                ).timestamp()
            except (ValueError, TypeError):
                ts_epoch = None
        component = entry.get("component") or "unknown"
        message = entry.get("message") or line
        return ts_epoch, component, message

    def _read_tail_error_entries(self, log_file: Path) -> list:
        """seek 尾部回退读 ≤256KB（tasks 3.5），逐行解析 ERROR 条目。

        返回 [(ts_epoch|None, component, message)]（日志时序序）。seek 截断的首行
        丢弃；读取/解码失败返回空列表（检测静默跳过）。
        """
        try:
            size = log_file.stat().st_size
            with log_file.open("rb") as f:
                if size > _TAIL_ERROR_READ_BYTES:
                    f.seek(size - _TAIL_ERROR_READ_BYTES)
                    f.readline()  # 丢弃 seek 可能截断的首行
                data = f.read().decode("utf-8", "replace")
        except OSError:
            return []
        entries = []
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = self._parse_error_line(line)
            if parsed is None:
                continue
            entries.append(parsed)
        return entries

    # ── 信号处理：记录（状态沉淀）+ 节流 + 唤起 ────────────────

    def _signal_status_hash(self, signal: dict) -> str:
        """计算信号的 status_hash（admin-signal-consolidation D1）。

        spec 信号：sha1(spec + status + error + updated)——spec 状态/内容均未变
        即判定「状态未变」→ 沉淀合并；spec 状态/内容变化 → 新 hash → 新建记录。
        spec=None 的 daemon 级信号无 spec 状态可判，status_hash 回退为
        daemon 级判据：sha1("daemon:" + signal_type + 错误指纹)。指纹取自
        _detect_daemon_errors 在信号上携带的稳定 `_fp`（同一错误骨架复现
        指纹稳定）；无 _fp 时回退归一化 evidence/description（仅换行/数字
        /时间戳差异不破坏稳定性）。「显式声明」：daemon 级信号纳入沉淀，
        不以时间桶切割——同 (None, signal_type, 指纹) 仅维护一条记录，
        first_seen 跨多次复发保留首次语义、last_seen 每轮刷新。
        """
        spec = signal.get("spec")
        if spec:
            try:
                entry = self.state_machine.read_one(spec) or {}
            except Exception:  # noqa: BLE001 — 状态读取失败按无状态计算
                entry = {}
            raw = "{}\x00{}\x00{}\x00{}".format(
                spec,
                entry.get("status") or "",
                entry.get("error") or "",
                entry.get("updated") or entry.get("created") or "",
            )
        else:
            fp = signal.get("_fp")
            if not fp:
                fp = _normalize_error_message(
                    signal.get("evidence") or signal.get("description") or ""
                )
            raw = "daemon:{}\x00{}".format(
                signal.get("signal_type") or "", fp
            )
        return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()

    @staticmethod
    def _signal_record(signal: dict, escalated: bool) -> dict:
        """构造待落库的 signal 记录（_handle_signal 两处 append 共用的字段集）。"""
        return {
            "kind": SIGNAL,
            "signal_type": signal.get("signal_type"),
            "spec": signal.get("spec"),
            "severity": signal.get("severity"),
            "description": signal.get("description"),
            "evidence": signal.get("evidence"),
            "recommended_action": signal.get("recommended_action"),
            "escalated": escalated,
        }

    def _handle_signal(self, signal: dict):
        """处理单条信号：状态沉淀记录 + 节流判定 + 唤起 Administrator。"""
        spec = signal.get("spec")
        signal_type = signal.get("signal_type")
        status_hash = self._signal_status_hash(signal)

        # 节流：冷却窗口内同 spec 同类信号已唤起过 / 已有未处理升级告警 → 跳过唤起
        if self._throttled(spec, signal_type):
            record, is_new = self.store.merge_signal(
                self._signal_record(signal, escalated=False), status_hash)
            if is_new:
                # 新记录：状态变化后首次节流（冷却期内重触发），保留既有文案
                self.logger.info(
                    "admin_monitor",
                    f"Signal throttled: {signal_type} for '{spec or 'daemon'}' "
                    f"(cooldown {int(self.cooldown_minutes)}m)",
                    {"signal": signal},
                )
            else:
                # 状态未变：仅刷 last_seen，不新增记录、不重复刷 info 日志
                # （admin-signal-consolidation D1：替代逐轮「Signal throttled」刷屏）
                self.logger.debug(
                    "admin_monitor",
                    f"Signal consolidated: {signal_type} for '{spec or 'daemon'}' "
                    f"(first_seen={record.get('created')}, "
                    f"last_seen={record.get('last_seen')})",
                )
            return

        # 人工冻结复查（fix-restart-dual-dispatch S4）：frozen spec 不产生自动
        # 唤起、不落冷却锚点记录——自动巡检对人工决策的每一次探查都是纯 token
        # 浪费，冻结本身即是「等待人工」的显式表达。手动呼叫（invoke_manual）
        # 不经此处，始终响应。
        if spec:
            try:
                _entry = self.state_machine.read_one(spec) or {}
            except Exception:
                _entry = {}
            if _entry.get("frozen"):
                self.logger.info(
                    "admin_monitor",
                    f"Skipping auto-invocation for manually-frozen SPEC "
                    f"'{spec}' (frozen field set) — signal '{signal_type}' "
                    f"dropped, not anchored",
                )
                return

        # 节流通过：先记录 signal（作为本次唤起的冷却锚点），再唤起
        signal_rec, _ = self.store.merge_signal(
            self._signal_record(signal, escalated=True), status_hash)
        self.logger.warning(
            "admin_monitor",
            f"Distress detected, invoking Administrator: {signal_type} for '{spec or 'daemon'}'",
            {"signal": signal},
        )
        self._invoke_administrator(signal, signal_rec)

    def _throttled(self, spec, signal_type: str) -> bool:
        """冷却窗口内已有同信号记录，或已存在未处理升级告警 → 节流。"""
        if self.store.latest_signal(spec, signal_type, self.cooldown_minutes) is not None:
            return True
        if self.store.unhandled_for(spec, signal_type) is not None:
            return True
        return False

    # ── 悬置强制升级（admin-signal-consolidation D2） ──────────

    def _force_escalate_stalled(self, specs: dict, now: float) -> list:
        """blocked 悬置 ≥ STALLED_ESCALATION_MINUTES → 强制升级真人（突破节流）。

        范围仅限悬置类信号（STALLED_ESCALATION_SIGNAL_TYPES = blocked_stuck +
        ENV 阻塞族）：spec 保持 blocked 状态过久、自动处置通道已被冷却压制——
        冷却意味着「同类信号不重复升级」，完全相同的 blocked 状态在数小时内无
        任何实质处置推进（add-web-ui 悬置 9.5h 事故实证）。其他信号类型维持
        既有 cooldown 节流，不得外溢。

        触发动作 = 直接写一条 kind=escalation（severity critical，注明悬置
        时长与信号首见时间），**不重新唤起 Administrator**（重唤起即重复烧钱，
        正是 cooldown 要防的）。绕过 latest_signal 冷却，但 MUST 仍受
        unhandled_for 约束：同 spec 已有任一悬置类信号类型的**未处理**人工
        告警时不再重复写，否则每轮巡检新增一条 ESCALATION = 升级风暴。人工
        把告警标 handled 后、状态仍悬置且 ≥2h → 可再次升级（每次人工处理后
        至多一条）。

        悬置时长口径 = now − spec.updated（spec 保持同一 blocked 状态的时长，
        对齐 proposal「blocked 悬置 9.5h」），**不是**信号记录 first_seen
        （后者含 max(cooldown,15) 阈值延迟）。冻结/用户指令暂停豁免与
        _detect_blocked_stuck 同判据（有意等待态不反复催办）。

        返回本次强制升级的 spec 列表（供审计；巡检不消费）。
        """
        escalated_specs = []
        for name, entry in specs.items():
            if entry.get("status") != "blocked":
                continue
            err = str(entry.get("error") or "")
            if entry.get("frozen") or err.startswith("frozen:") or "用户指令" in err:
                continue
            updated_str = entry.get("updated") or entry.get("created") or ""
            try:
                updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            stalled_minutes = (now - updated.timestamp()) / 60
            if stalled_minutes < STALLED_ESCALATION_MINUTES:
                continue
            # 未处理约束：同 spec 已有任一悬置类信号类型的未处理人工告警 → 跳过
            if any(
                self.store.unhandled_for(name, st) is not None
                for st in STALLED_ESCALATION_SIGNAL_TYPES
            ):
                continue
            first_seen = self._first_signal_time(name) or updated_str
            self.store.append(attach_trigger({
                "kind": ESCALATION,
                "signal_type": "blocked_stuck",
                "spec": name,
                "severity": "critical",
                "description": (
                    f"'{name}' 已 blocked 悬置 {int(stalled_minutes)} 分钟"
                    f"（≥{STALLED_ESCALATION_MINUTES} 分钟）未处置，自动通道已被"
                    f"冷却压制，强制升级人工介入"
                ),
                "evidence": (
                    f"updated={updated_str}；悬置时长 {int(stalled_minutes)} 分钟；"
                    f"信号首见 {first_seen}；阈值 {STALLED_ESCALATION_MINUTES} 分钟"
                ),
                "action_taken": (
                    "AdminMonitor 强制升级：blocked 悬置超阈值自动转人工"
                    "（突破 cooldown 节流，受未处理告警约束）"
                ),
                "recommended_action": (
                    "人工检查该 spec 的 blocked 原因：误置假 spec 则清理/重置；"
                    "确需人工决策则处置后复位或手动更新状态"
                ),
            }))
            self.logger.warning(
                "admin_monitor",
                f"Stalled block force-escalated to human: '{name}' "
                f"(stalled {int(stalled_minutes)}m ≥ {STALLED_ESCALATION_MINUTES}m)",
            )
            escalated_specs.append(name)
        return escalated_specs

    def _first_signal_time(self, spec: str) -> Optional[str]:
        """返回 spec 最早的悬置类信号记录 created（首见时间），无则 None。

        状态沉淀后 created 保留首次语义（first_seen），多轮续报只刷 last_seen
        ——取最早一条即「信号首见」；跨状态变化的多个记录中取最早的仍能反映
        「该 spec 最早因悬置被监视器关注」的时间。
        """
        earliest = None
        for rec in self.store.read_all():
            if (rec.get("kind") != SIGNAL
                    or rec.get("spec") != spec
                    or rec.get("signal_type") not in STALLED_ESCALATION_SIGNAL_TYPES):
                continue
            created = rec.get("created")
            if created and (earliest is None or created < earliest):
                earliest = created
        return earliest

    # ── 兜底升级（fix-admin-self-heal） ──────────────────────────

    def _recover_orphaned_dispositions(self):
        """检测「admin 被唤起但未完成处置」（pending 无最终结果）→ 升级人工。

        admin 是 daemon 子进程，若其在处置中被 kill（daemon 重启/崩溃），不会留下
        最终 disposition、也不会走升级分支。此方法每次巡检兜底：pending 记录超时
        无最终结果 → 转为人工升级告警，保证「admin 死了也有告警」。
        """
        records = self.store.read_all()
        grace = max(self.cooldown_minutes, 1) * 60
        now = time.time()
        by_run: dict = {}
        for rec in records:
            if rec.get("kind") != DISPOSITION:
                continue
            rid = rec.get("admin_run_id")
            if not rid:
                continue
            status = rec.get("status") or rec.get("result")
            by_run.setdefault(rid, {"final": False, "rec": rec})
            if status != "pending":
                by_run[rid]["final"] = True

        for rid, info in by_run.items():
            if info["final"]:
                continue
            pending = info["rec"]
            try:
                created = datetime.fromisoformat(
                    (pending.get("created") or "").replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                continue
            if now - created.timestamp() < grace:
                continue
            spec = pending.get("spec")
            sig_type = pending.get("signal_type")
            if self.store.unhandled_for(spec, sig_type) is not None:
                continue

            # fix-graceful-shutdown-agents：先验 run 文件是否含 interrupted 标记（daemon
            # 优雅退出所致已知中断）。含标记 → 判定已知中断：终结 pending disposition 且
            # 不产生人工升级告警；无标记/文件缺失 → 维持现有"疑似 daemon 崩溃"升级兜底
            # （保守方向：宁可多告警不漏告警，files 被 prune 删除也按无标记处理）。
            if self._run_has_interrupted_marker(rid):
                self.store.append({
                    "kind": DISPOSITION,
                    "status": "interrupted",
                    "signal_type": sig_type,
                    "spec": spec,
                    "admin_run_id": rid,
                    "result": "interrupted",
                    "actions_taken": (
                        "AdminMonitor 孤儿检测：run 文件含 interrupted 标记，"
                        "判定为 daemon 优雅退出已知中断，终结该 run 且不升级人工"
                    ),
                    "description": f"Administrator 处置因 daemon 关闭被中断（run {rid}），已知中断已终结",
                })
                self.logger.info(
                    "admin_monitor",
                    f"Orphaned admin disposition marked interrupted (known shutdown): {rid}",
                )
                continue

            self.store.append(attach_trigger({
                "kind": ESCALATION,
                "signal_type": sig_type,
                "spec": spec,
                "severity": "critical",
                "description": (
                    f"Administrator 处置中断（run {rid}）：被唤起后未在 "
                    f"{int(grace / 60)} 分钟内完成处置，疑似 daemon 重启/崩溃连带杀死 "
                    f"admin，需人工介入"
                ),
                "evidence": f"pending disposition 超时无最终结果（admin_run_id={rid}）",
                "action_taken": "AdminMonitor 孤儿检测：pending 超时自动升级",
                "admin_run_id": rid,
                "recommended_action": (
                    "人工检查 daemon/AdminMonitor 状态与 .fenix/logs/supervisor.log，"
                    "确认框架是否健康运行"
                ),
            }))
            # 升级即终结：补非 pending 记录，避免 escalation 被 handled 后 unhandled_for
            # 节流失效、同一孤儿在下轮巡检再次升级造成循环告警
            self.store.append({
                "kind": DISPOSITION,
                "status": "escalated",
                "signal_type": sig_type,
                "spec": spec,
                "admin_run_id": rid,
                "result": "escalated",
                "actions_taken": "AdminMonitor 孤儿检测：pending 超时升级人工并终结该 run",
                "description": f"Administrator 处置中断已升级人工（run {rid}），pending 终结",
            })
            self.logger.warning(
                "admin_monitor",
                f"Orphaned admin disposition escalated to human: {rid}",
            )

    def _run_has_interrupted_marker(self, admin_run_id: str) -> bool:
        """检查 admin_run_id 对应的 run 产物是否含 interrupted 标记（已知 daemon 中断）。

        fix-graceful-shutdown-agents：admin agent 被 daemon 优雅退出终止时，agent_runner
        会向 `.fenix/runs/<admin_run_id>.jsonl` 追加 `{"type": "interrupted"}` 记录。孤儿
        检测据此区分"已知中断"（与 run 共存）与"疑似崩溃"（run 无标记）。run 文件被 prune
        删除或读不到标记，一律按 False（无证据 → 升级兜底，保守方向）。

        Args:
            admin_run_id: admin disposition 的 admin_run_id（形如 admin-<spec>-<ts>）。
        """
        run_file = self.project_root / ".fenix" / "runs" / f"{admin_run_id}.jsonl"
        if not run_file.is_file():
            return False
        try:
            with run_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict) and entry.get("type") == "interrupted":
                        return True
        except OSError:
            return False
        return False

    def _detect_restart_failure(self, now: float):
        """restart_request 存在且过期 → 重启未完成 → 升级人工。

        admin 请求重启后由 supervisor 负责实际重启并清除 restart_request。
        若文件一直存在，说明 supervisor 未运行或重启失败，需人工介入。
        fix-supervisor-hosting-chain D5：recommended_action 按托管态分支——
        unmanaged/stopped 时指引经 Dashboard「安装托管」或 /fenix-setup 恢复
        托管（MUST NOT 出现「手动启动 .fenix/bin/fenixd_supervisor.py」这类
        会绑定到框架主树的直接命令）；managed 时指引检查 supervisor 进程与
        daemon 排水状态。
        """
        rr = self.project_root / ".fenix" / "restart_request"
        if not rr.exists():
            return []
        try:
            mtime = rr.stat().st_mtime
        except OSError:
            return []
        if now - mtime < RESTART_REQUEST_TIMEOUT_MINUTES * 60:
            return []  # 刚请求，窗口内不升级
        if self.store.unhandled_for(None, "restart_failed") is not None:
            return []
        # 托管态分支（D5）：不直接调 .fenix/bin/fenixd_supervisor.py
        try:
            from core.fenix_session import hosting_state
            state = hosting_state(self.project_root)
        except Exception:
            state = "stopped"
        if state == "managed":
            rec_action = (
                "检查 supervisor 进程与 daemon 排水状态：确认 supervisor 存活、"
                "daemon 未卡在排水（admin.shutdown_drain_seconds 窗口内仍有关闭中"
                "的 run），必要时重启 supervisor 使配置生效"
            )
        else:
            rec_action = (
                "本项目未受 supervisor 托管：经 Dashboard 项目页「安装托管」或 "
                "/fenix-setup 恢复 supervisor 托管，恢复后该 restart_request 会被"
                "supervisor 消费并重启 daemon"
            )
        self.store.append({
            "kind": ESCALATION,
            "signal_type": "restart_failed",
            "spec": None,
            "severity": "critical",
            "description": (
                "daemon 重启请求未完成：.fenix/restart_request 存在超过 "
                f"{RESTART_REQUEST_TIMEOUT_MINUTES} 分钟，supervisor 未重启 daemon"
            ),
            "evidence": f"restart_request mtime={mtime}，supervisor 应清除该文件",
            "action_taken": "AdminMonitor 重启验证：请求未完成自动升级",
            "recommended_action": rec_action,
        })
        return ["restart_failed"]

    def invoke_manual(self, signal: dict):
        """手动唤起入口（fenixd 主循环拾取 .fenix/admin_invoke_request.json）。

        与自动检测共用 _invoke_administrator 的唤起+落痕路径：run_administrator
        返回后落最终 DISPOSITION（终结 run_administrator 开头落的 pending 记录），
        escalate 时落升级告警。此前手动路径直接调 run_administrator 并丢弃返回值，
        pending 永无终态、处置叙述从不入告警时间线，dashboard 上显示「处置中」
        导致用户反复手动重呼（2026-08-29 v2-cutover-main-entry 三连呼实证）。

        不检查 enabled：用户显式呼叫应始终响应（enabled 只约束自动巡检）。
        """
        self._invoke_administrator(signal, None)

    def _invoke_administrator(self, signal: dict, signal_rec: dict):
        """唤起 Administrator 处置；失败或升级时落升级告警。"""
        if self.agent_runner is None:
            self.logger.warning(
                "admin_monitor",
                "No agent_runner available, cannot invoke Administrator; escalating to human",
            )
            self.store.append(attach_trigger({
                "kind": ESCALATION,
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec"),
                "severity": signal.get("severity"),
                "description": signal.get("description"),
                "evidence": signal.get("evidence"),
                "action_taken": "Administrator 不可用（未配置 agent_runner），未能自动处置",
                "recommended_action": signal.get("recommended_action"),
            }))
            return

        try:
            disp = self.agent_runner.run_administrator(signal)
        except Exception as e:
            self.logger.error(
                "admin_monitor",
                f"Administrator invocation failed: {e}",
                {"signal": signal},
            )
            self.store.append(attach_trigger({
                "kind": ESCALATION,
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec"),
                "severity": signal.get("severity"),
                "description": signal.get("description"),
                "evidence": signal.get("evidence"),
                "action_taken": f"Administrator 唤起失败: {e}",
                "recommended_action": signal.get("recommended_action"),
            }))
            return

        # 处置记录（任何情况下都留痕）；落盘失败不能丢 final 判定（否则该 run
        # 的 pending 会变孤儿触发人工升级），记日志后继续
        # fix-admin-disposition-empty-shell：失败记录自解释——error 携带 CLI 失败
        # 原因；failed 时 recommended_action 回退到信号侧（disp 空串不再覆盖信号值）。
        try:
            self.store.append({
                "kind": DISPOSITION,
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec") or disp.spec,
                "severity": signal.get("severity"),
                "description": disp.problem or signal.get("description"),
                "action_taken": disp.actions_taken,
                "result": disp.result,
                "recommended_action": (
                    disp.recommended_action or signal.get("recommended_action") or ""
                ) if disp.result == "failed" else disp.recommended_action,
                "summary": disp.summary,
                "admin_run_id": disp.run_id,
                "escalate": bool(disp.escalate),
                "error": disp.error or "",
            })
        except Exception as e:
            self.logger.error(
                "admin_monitor",
                f"Failed to persist administrator disposition for run {disp.run_id}: {e}",
            )

        # family_explosion 处置：Administrator「放行一次」→ 设置父 SPEC 豁免位
        # （fix-family-convergence-governor / design D4）。结构字段优先级最高；
        # 文本动作（放行 / _family_waiver / waive）兜底，兼容自由文本处置。
        self._apply_family_waiver(signal, disp)

        # env 阻塞 / blocked_stuck 处置收尾复位（add-blocked-reverify-lane D2 +
        # frozen-scenario-schema-migration D3）：result 为 resolved/
        # partially-resolved 且信号属复位集合（env 族 + blocked_stuck）时，
        # 框架机械判定复位路径——实现分支已合并 → transition_gate(testing)
        # 直通道重验（跳过全量重实现）；否则 → 既有 transition(ready)。
        # 两条路径均保留阻塞轮次（不清零，生命周期累计语义），仅清 error。
        # escalated 表示 admin 升级人工，不触发自动复位（人工处置是唯一出路）。
        if disp.result in ("resolved", "partially-resolved"):
            sig_type = signal.get("signal_type")
            if sig_type in DISPOSITION_AUTO_RESET_SIGNAL_TYPES:
                self._reset_env_blocked_after_disposition(signal, disp)

        # fix-stale-escalation-close：run 有最终结果即关闭其名下旧 escalation
        # （孤儿看护在处置进行中误判 pending 超时的残留）。不关闭则 dashboard
        # 处置卡片永久「需人工决策」、与 result=resolved 矛盾，且 unhandled_for
        # 节流会压制该 spec 后续同型告警。failed/interrupted 保守保留——处置
        # 未成功闭环，人工仍需知情。escalated 的接棒告警在其后落盘，不受影响。
        if disp.result in ("resolved", "partially-resolved", "escalated"):
            try:
                closed = self.store.close_escalations_for_run(
                    disp.run_id,
                    f"随处置最终记录闭环（run {disp.run_id} 最终 result={disp.result}）",
                )
            except Exception as e:  # noqa: BLE001 — 闭环失败不阻塞处置落痕
                closed = 0
                self.logger.error(
                    "admin_monitor",
                    f"Failed to close stale escalations for run {disp.run_id}: {e}",
                )
            if closed:
                self.logger.info(
                    "admin_monitor",
                    f"Closed {closed} stale escalation(s) for run {disp.run_id} "
                    f"(final result={disp.result})",
                )

        if disp.escalate:
            # Administrator 判定无法自主处置 → 升级人工
            self.store.append(attach_trigger({
                "kind": ESCALATION,
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec") or disp.spec,
                "severity": signal.get("severity"),
                "description": signal.get("description"),
                "evidence": signal.get("evidence"),
                "action_taken": disp.actions_taken,
                "recommended_action": disp.recommended_action or signal.get("recommended_action"),
                "admin_run_id": disp.run_id,
            }))
            self.logger.warning(
                "admin_monitor",
                f"Administrator escalated to human: {signal.get('signal_type')} "
                f"for '{signal.get('spec') or 'daemon'}'",
            )

    # ── 辅助 ────────────────────────────────────────────────────

    def _reset_env_blocked_after_disposition(self, signal: dict, disp) -> None:
        """阻塞处置收尾自动复位（add-blocked-reverify-lane D2 +
        frozen-scenario-schema-migration D3）。

        result=resolved/partially-resolved + signal_type∈自动复位集合
        （env 族 + blocked_stuck）→ 框架机械判定：branch 已合并 →
        transition_gate(testing) 直通道 + verifier 入队重验；未合并/无
        branch → transition(ready) + implementer 重派。两条路径均保留
        阻塞轮次（不清零，生命周期累计语义），仅清 error。

        blocked_stuck 复用同一路径（D3）：处置根因修复后状态悬置是纯闭环
        缺口，无独立语义——复位守卫由 resolve_env_blocked_reset_path 判定
        （人工冻结/非 blocked 不触发），只复位阻塞态，MUST NOT 恢复任何
        错误业务判定（merge-breaker 计数等业务侧车字段一律不清零）。

        自身异常不得阻塞处置落痕（右关联设计：处置记录永远先落盘）。
        """
        # 防御：result 非 resolved/partially-resolved（如 escalated/failed）不触发
        # 自动复位——消费点已前置检查，此处再兜底，杜绝调用路径遗漏。
        if getattr(disp, "result", None) not in ("resolved", "partially-resolved"):
            return
        spec = signal.get("spec")
        if not spec:
            return
        sm = self.state_machine
        if not hasattr(sm, "read_one") or not hasattr(sm, "update_spec"):
            return
        spec_entry = sm.read_one(spec)
        if not spec_entry:
            return
        reset_path = resolve_env_blocked_reset_path(spec_entry, self.project_root)
        if reset_path is None:
            return

        try:
            if reset_path == "testing":
                # 直通道：gate transition 不走 VALID_TRANSITIONS，仅门禁白名单放行
                sm.transition_gate(spec, "testing")
                sm.update_spec(spec, {"error": None})
                # verifier 入队：pm_engine 存在时最小侵入调用 handle_event；
                # pm_engine 缺失时仅靠 daemon recovery 的 implemented 分支兜底
                # （testing 态在 INTERRUPTED_STATES 中，重启回退 ready 重新检测）
                if self.pm_engine is not None:
                    self.pm_engine.handle_event("spec_implemented", spec)
                self.logger.info(
                    "admin_monitor",
                    f"env 阻塞处置复位（直通道）：'{spec}' transition_gate(testing)"
                    f" + verifier 入队重验",
                )
            else:
                # 既有路径：VALID_TRANSITIONS 允许 BLOCKED→READY
                sm.transition(spec, "ready")
                sm.update_spec(spec, {"error": None})
                self.logger.info(
                    "admin_monitor",
                    f"env 阻塞处置复位：'{spec}' → ready（实现阶段熔断/未合并）",
                )
        except Exception as e:
            self.logger.warning(
                "admin_monitor",
                f"env 阻塞处置复位失败 '{spec}'（reset_path={reset_path}）: {e}",
            )

    def _apply_family_waiver(self, signal: dict, disp) -> None:
        """family_explosion 处置「放行一次」→ 设置父 SPEC 豁免位 _family_waiver=true。

        判定：结构字段 disp.family_waiver 为 True；或自由文本
        actions_taken/recommended_action 含显式放行语义（赋值型 _family_waiver=true、
        「设置 _family_waiver 为 true」「放行一次」等），且不含否定短语
        （未放行/不发放/不予放行…）。仅在叙述中提及豁免位字面令牌不构成放行。
        豁免位由 pm_engine 族谱门在下一轮实际创建工作开始时消费并复位（单次）。

        Args:
            signal: 本次唤起信号 dict（含 signal_type/spec）。
            disp: AdminDisposition 处置结果。
        """
        if signal.get("signal_type") != "family_explosion":
            return
        spec = signal.get("spec")
        if not spec:
            return
        text = (
            f"{(disp.actions_taken or '')}\n{(getattr(disp, 'summary', '') or '')}\n"
            f"{(disp.recommended_action or '')}"
        )
        # 否定语义优先：任何位置出现否定短语即不放行（保守方向：宁可漏放行、
        # 不可给未放行的父 SPEC 错开派生口子）。结构字段 family_waiver=True
        # 优先级最高（Administrator 结构化回填不受文本兜底影响）。
        if bool(getattr(disp, "family_waiver", False)):
            waived = True
        else:
            negated = any(n in text for n in _WAIVER_NEGATION_PHRASES)
            if negated:
                waived = False
            else:
                waived = any(
                    re.search(pattern, text) for pattern in _WAIVER_GRANT_PATTERNS
                )
                if not waived:
                    # 赋值型兜底：_family_waiver=true 须与「放行」动词同句才算
                    # 显式放行——叙述中对他族谱豁免状态的提及不构成放行。
                    waived = any(
                        _WAIVER_ASSIGN_RE.search(sent) and "放行" in sent
                        for sent in re.split(r"[。！？\n]", text)
                    )
        if not waived:
            return
        sm = self.state_machine
        if not hasattr(sm, "update_spec"):
            # 测试替身等最小状态机：仅能检测，无法落位（放行仍判定为本次已放行）
            self.logger.warning("admin_monitor", f"family_explosion 放行但状态机不支持写豁免位（spec={spec}）")
            return
        try:
            sm.update_spec(spec, {"_family_waiver": "true"})
            self.logger.info(
                "admin_monitor",
                f"family_explosion 人工放行: '{spec}' 已设置 _family_waiver=true（单次豁免）",
            )
        except Exception as e:
            self.logger.warning("admin_monitor", f"family_explosion 豁免位设置失败: {e}")

    @staticmethod
    def _spec_from_run_id(run_id: str):
        """从 run_id 还原 spec 名：匹配 <prefix><spec>-<ts> 结构。

        如 impl-myspec-1735... → myspec；planner-plan-myspec-1735... → myspec。
        无法识别返回 None。
        """
        for prefix in _RUN_PREFIXES:
            if not run_id.startswith(prefix):
                continue
            rest = run_id[len(prefix):]
            m = re.match(r"^(.*)-\d{9,10}(-a\d+)?$", rest)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def _run_terminal_status(run_file: Path) -> str:
        """读取产物尾部判定终态：error / done / running / empty。

        与 dashboard.data.classify_run 同语义，避免跨层 import dashboard。
        """
        try:
            size = run_file.stat().st_size
            with run_file.open("rb") as f:
                if size > 4096:
                    f.seek(size - 4096)
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            return "empty"
        last = None
        for line in tail.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                last = entry
        if not last:
            return "empty"
        t = last.get("type")
        if t == "result":
            return "done"
        if t == "error":
            return "error"
        return "running"

    def _has_recent_progress(self, spec: str, runs_dir: Path, now: float, window: float) -> bool:
        """该 spec 是否存在窗口内有写活动的 run 文件（有进度）。"""
        if not runs_dir.is_dir():
            return False
        try:
            files = list(runs_dir.glob("*.jsonl"))
        except OSError:
            return False
        for p in files:
            if self._spec_from_run_id(p.stem) != spec:
                continue
            try:
                if now - p.stat().st_mtime < window:
                    return True
            except OSError:
                continue
        return False

    # ── 状态变更历史（抖动检测） ────────────────────────────────

    def _load_history(self) -> dict:
        try:
            data = json.loads(self._history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_history(self, history: dict):
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=".admin_state_history.",
            suffix=".tmp",
            dir=str(self._history_path.parent),
        )
        tmp_path = Path(tmp)
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False)
            tmp_path.replace(self._history_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _update_history(self, specs: dict, now: float):
        """把当前快照与上次记录对比，状态变化则追加变更事件；裁剪过期条目。"""
        history = self._load_history()
        cutoff = now - 60 * 60  # 只保留最近 1 小时
        changed = False
        for name, entry in specs.items():
            status = entry.get("status")
            if status not in ("ready", "implementing"):
                continue
            rec = history.get(name)
            last_status = rec.get("last_status") if isinstance(rec, dict) else None
            changes = rec.get("changes") if isinstance(rec, dict) else []
            if last_status is not None and last_status != status:
                changes.append([now, status])
                changes = [c for c in changes if c[0] >= cutoff]
                changed = True
            elif not rec:
                changed = True
            history[name] = {"last_status": status, "changes": changes}
        # 清理不在进行中的 spec 的历史（避免文件无限膨胀）
        active = {n for n, e in specs.items() if e.get("status") in ("ready", "implementing")}
        for name in list(history.keys()):
            if name not in active:
                del history[name]
                changed = True
        if changed:
            self._save_history(history)
