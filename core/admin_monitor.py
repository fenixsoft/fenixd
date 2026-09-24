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
  - orphaned_state    implementing/testing 无活动 run + 无存活子进程 + 无待派发
                       超 orphaned_state_threshold_minutes（缺省 15 分钟，远短于
                       stuck 的 ~160 分钟）；与 stuck 在 stuck 阈值处交接（hand-off）。
                       description 描述的是 signal 阶段；disposition pending/
                       failed/escalated 阶段由处置/升级记录承载（orphaned-state-
                       probe-calibration 1.6 阶段语义，见 _detect_orphaned_state）

节流（D2）：同 spec 同类信号在 admin.escalation_cooldown_minutes 内只唤起一次，
依据 .fenix/admin_alerts.json 中的 signal 记录与未处理升级告警。

纯本地数据、零 LLM：本模块任何路径都不调用 claude / LLM API。
"""

import hashlib
import json
import re
import subprocess
import tempfile
import threading
import time
import traceback
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

# evo-add-wip-defer-merge-retry-consumer 2.3：WIP 等待豁免的上限口径与周期
# 消费者（queue.py）共用同一常量——超限即「降级人工 + 豁免自动失效」单源。
from core.pm_engine.dispatch.queue import WIP_DEFER_WINDOW_MINUTES, WIP_DEFER_MAX_ROUNDS

# frozen-scenario-schema-migration D3：处置后自动复位集合。
# blocked_stuck 与 env 阻塞族同语义加入自动复位：admin 处置成功
# （result=resolved/partially-resolved）且根因已修复 → 复用
# resolve_env_blocked_reset_path 既有复位路径（实现分支已合并→testing
# 直通重验，否则→ready），消除 blocked_stuck 处置成功后二次空转。
# MUST NOT 恢复任何错误业务判定——只复位阻塞态，复位守卫（frozen/
# 非 blocked）由 resolve_env_blocked_reset_path 判定。
DISPOSITION_AUTO_RESET_SIGNAL_TYPES = ENV_BLOCK_SIGNAL_TYPES + ("blocked_stuck",)


def disposition_signal_hits_auto_reset(signal) -> bool:
    """处置信号是否命中自动复位集合（fix-manual-invoke-signal-type-passthrough 2.1）。

    `signal_type` 或 `underlying_signal_type` 任一命中
    DISPOSITION_AUTO_RESET_SIGNAL_TYPES 即触发：手动唤起通道顶层恒为
    manual-intervention（store 记录/节流锚点/活动区展示语义），底层类型经
    underlying_signal_type 透传（fenixd._check_admin_invoke_requests 写入：
    请求文件 payload 直传优先——env 阻塞自动呼叫路径的升级记录 warning 级
    降噪即被标 handled、反查不可见——store 未处置记录反查兜底），复位门须
    同时感知两个字段；自动检测通道仅携带 signal_type，行为不变。
    """
    if not isinstance(signal, dict):
        return False
    return (
        signal.get("signal_type") in DISPOSITION_AUTO_RESET_SIGNAL_TYPES
        or signal.get("underlying_signal_type") in DISPOSITION_AUTO_RESET_SIGNAL_TYPES
    )

# admin-dispatch-failure-escalation D1：派发期编程错误异常类型集合——
# TypeError/AttributeError/NameError/ValueError 是代码缺陷的典型签名
# （实参不符/属性缺失/未定义名/参数构造错误），Administrator 无法修复，
# 落专用信号 admin_dispatch_programming_error（critical）供归类统计。
# ValueError 子类（JSONDecodeError/UnicodeDecodeError 等数据类瞬时问题）
# 会被归为编程错误——保守可见方向（升级总比静默原类型好），evidence 保留
# 完整异常消息供甄别。
_PROGRAMMING_ERROR_TYPES = (TypeError, AttributeError, NameError, ValueError)

# admin-dispatch-failure-escalation D2：派发失败自动重试上限（模块常量不入
# config，对齐本模块既有常量做法）。既有升级记录 retry_count 单调递增至该
# 上限后 _retry_due_dispatch_failures 不再选中，不无限重试。
DISPATCH_RETRY_MAX = 1

# admin-disposition-reschedule：中断-重派累计上限（模块常量，config
# `admin.reschedule_max` 可覆盖，非法值回落 2）。同 (spec, signal_type)
# 信号族的累计重派次数（reschedule_count，落库在 DISPOSITION 记录）超限后
# 不再自动重派、转人工升级——防止停机循环无限重派烧钱。
MAX_RESCHEDULE = 2

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
# alert-noise-governance 3.1：指纹级重启冷却窗（模块常量不入 config，对齐本
# 层既有做法，规避「新增配置项必须带 Dashboard UI」约束）。
# 治理目标 = 重启后首扫回放：daemon 重启不清日志，首扫即命中与停机前相同
# 指纹的 ERROR——重启前已召唤过一次（记账在案），同批指纹重启后短期重复召
# 唤收益趋零（design D5）。窗内已知指纹不计满升级阈值、不召唤（INFO 留痕冷
# 却决策）；窗后复现或全新指纹照常升级（3.3）。
# 与既有节流的关系（3.3）：_throttled 按 (spec, signal_type) 做「冷却窗口内
# 已唤起 / 已有未处理升级告警」判定——它是**信号级**节流，覆盖同信号重唤起；
# 本冷却是**指纹级**补口而非替代：孪生指纹各算各的时会绕开单条信号记录的锚
# 定（同轮 3 笔 admin-global 召唤实证），且跨重启首扫的已知指纹不应再次点燃
# 召唤。两道判定并存，_throttled 语义不变。
DAEMON_ERROR_RESTART_COOLDOWN_MINUTES = 30
STUCK_GRACE_MINUTES = 10  # run 文件 mtime 距现在小于此值视为"有进度"，不算卡死
RESTART_REQUEST_TIMEOUT_MINUTES = 10  # restart_request 超时未清除 → 重启失败 → 升级

# admin-signal-consolidation D2：blocked 悬置强制升级阈值（模块常量不入 config，
# 对齐本模块既有常量做法，规避"新增配置项必须带 Dashboard UI"约束）。
# 悬置时长口径 = now − spec.updated（spec 保持同一 blocked 状态的时长），
# 不是信号记录 first_seen（后者含 max(cooldown,15) 阈值延迟，会晚一小时余才触发）。
STALLED_ESCALATION_MINUTES = 120

# ── 孤儿状态探测（add-control-plane-silent-failure-guards D5）──────────
# 无驱动判定中「run 文件 mtime 距现在小于此值视为有活动」的宽限窗：120s 与
# event_bus._ready_has_live_child 的 120s 存活探测口径一致——长 run 一定在
# 持续写 run 文件（有进度），mtime 超宽限 + 无存活子进程才是真无驱动。
ORPHANED_RUN_GRACE_SECONDS = 120
# 阈值缺省：15 分钟 = 3 个 admin.interval_minutes(5) 巡检周期（design D5，
# 与巡检周期整数倍对齐避免漏检），远短于 stuck（run_timeout+600s ≈ 160 分钟）。
DEFAULT_ORPHANED_STATE_THRESHOLD_MINUTES = 15

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
    "未放行",
    "不放行",
    "拒绝放行",
    "不予放行",
    "不发放",
    "未发放",
    "不启用豁免",
    "未启用豁免",
    "不予豁免",
    "无须放行",
    "无需放行",
    "不必放行",
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

# ── infra 回拨文本识别（evo-infra-failure-budget-exempt R3）──────────
# Administrator 处置文本显式声明「回拨 N 轮」（实为 infra 却计入 _verify_fail_rounds
# 的历史轮次减回 + 解冻）。与 _apply_family_waiver 同范式：结构字段
# disp.infra_reclassify_rounds 优先级最高，文本模式兜底。
# 匹配组 (?P<n>\d+) 给出减回轮次。
_RECLASSIFY_GRANT_PATTERNS = (
    r"回拨\s*(?P<n>\d+)\s*轮",
    r"reclassify\s*(?P<n>\d+)\s*(?:infra)?\s*rounds?",
    r"infra\s*回拨\s*(?P<n>\d+)\s*轮",
)
# 否定短语（保守方向：命中即不触发回拨，宁可漏回拨不可误扣 fail_rounds）
_RECLASSIFY_NEGATION_PHRASES = (
    "不回拨",
    "不应回拨",
    "不能回拨",
    "不予回拨",
    "not reclassify",
    "不适用回拨",
)

# 「写入即待唤起」信号的终态守卫：spec 已达这些状态时不再唤起 Administrator
# （done/pushed 之后族谱不可能再派生，困境实质已消失）。
_TERMINAL_SPEC_STATUSES = ("done", "pushed")


def _is_fixture_project(project_root) -> bool:
    """项目是否带 fixture:true 标记（alert-noise-governance 5）。

    权威源 = dashboard.yaml 项目条目（fix-fixture-project-alert-noise 落地，
    core/dashboard/registry.py Registry.discover 只读消费，本模块不改动该文
    件）。函数内延迟导入：registry 仅依赖 stdlib+yaml，无反向依赖环，延迟
    是为避免加载序副作用（对齐本模块 ConfigLoader 的延迟导入风格）。

    fail-open（design D4）：registry 读取异常 / 项目不在册 / 标记非布尔真，
    一律按非夹具处理——MUST NOT 因标记异常让召唤/摘要失效。
    """
    try:
        from core.dashboard.registry import Registry

        root = str(Path(project_root).resolve())
        for p in Registry().discover():
            if p.get("path") == root:
                return p.get("fixture") is True
    except Exception:
        return False
    return False


# fixture 判定实例级备忘的 TTL 秒（code-review item 9427d41c85ef）：夹具标记
# 实践中静态（dashboard.yaml 项目条目），TTL 内同项目根复用首次解析结果；
# 配置改动最多延迟一个 TTL 生效（巡检周期分钟级，可接受）。
_FIXTURE_PROJECT_MEMO_TTL = 300.0

# ── dispatch_stalled 前提复核（陈旧快照守卫，2026-09-17 事故）────────────
# dispatch_stalled 是**快照式**信号：pm_engine 在巡检瞬间把「ready 滞留」这一
# 事实写进 store，AdminMonitor 在后续巡检里逐条摄取兑现。二者之间存在最长一个
# 巡检周期（admin.interval_minutes）的滞后，且一旦 store 内积压多条，滞后期还会
# 被串行摄取的阻塞时长叠加。若该 spec 在窗口内已被正常派发／推进，积压记录携带
# 的「ready 滞留」前提就已被事实推翻——照旧唤起只会得到一个「已恢复、无需处置」
# 的空转 admin run（每次数美元 + 占据 admin worker 槽）。
#
# 实证（2026-09-17）：'evo-orphaned-state-probe-calibration' 的 dispatch_stalled
# 记录写于 18:25:31Z（队列老化窗口内的假就绪滞留误报），spec 已于 19:52:22Z 被
# 正常派发、20:16:20Z 该积压记录才被兑现唤起（此时 implementer run 正在产流），
# 20:26:00Z run 成功收工——唤起时刻前提已被推翻 24 分钟，处置结论只能是空转。
#
# 守卫口径：仅在「该信号的困境前提 = spec 处于 ready」时复核——spec 当前状态
# 已非 ready（implementing/testing/implemented/blocked/…）即视为前提被覆盖，
# 标记 escalated 跳过（与终态守卫同款「核销而非丢弃」，记录保留可审计）。
# ready 当且仅当 status 字段字面等于 "ready"：未知/缺失一律按前提未被推翻处理
# （fail-open，宁多唤起一次也不掩真阳性）。
_STALL_PREMISE_READY = "ready"
# 前提复核适用的信号类型：仅 dispatch_stalled。其余「写入即待唤起」类信号
# （family_explosion / verify_contract_* / inconclusive_loop / stash_pop_conflict /
# verify_uniform_failure）的困境前提与 ready 状态无关，各有自身的守卫逻辑，
# 一律不参与本复核。
_STALL_PREMISE_SIGNAL_TYPES = ("dispatch_stalled",)

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
    # add-test-regression-tab 增强：契约有效但缺 regression 段时，UI 请求 AI 仅补段
    # （区别于 verify_contract_missing 的整契约起草——该场景契约本身有效，只缺段）。
    "verify_regression_missing": "major",
    # fix-artifact-paths-hardcoded-default D3：merge-back WIP 重叠闸门检出产物
    # 配置未裁决（has_build_artifacts 缺省或 true 配空路径），呼叫 Administrator
    # 起草产物路径配置——与 verify_contract_missing 同级（配置缺口，需人工/起草
    # 落地，未裁决时产物会被当语义内容处理）。
    "build_artifact_paths_missing": "major",
    # fix-mergeback-stashpop-silent-loss D1：pop 冲突自愈丢弃的用户改动，
    # 内容找回需人工核对（stash 栈 + 逐文件 git show），major 级。
    "stash_pop_conflict": "major",
    # evo-merge-back-wip-overlap-gate D1：merge-back 前主树 WIP 与分支改动重叠，
    # 按显式配置的阻塞策略中止合并（主树零污染）——需人工处置重叠改动后放行，
    # major 级（阻塞是前置拦截、非 merge 失败，低于 critical）。
    "mergeback_wip_overlap": "major",
    # evo-merge-back-spec-dir-inflight-guard D1a/D2：spec 目录在飞编辑顺延超限——
    # 停止自动重试（有界顺延耗尽），等待人工提交 spec 目录后复位放行。
    # 等同 WIP 重叠阻塞（major）：非 critical（非全链路瘫痪）、非 minor（阻塞
    # 单 spec merge-back）。由上述 STORED_SIGNAL_TYPES 收录，admin_monitor
    # 摄取唤起 Administrator。
    "mergeback_spec_dir_inflight_stuck": "major",
    # evo-add-wip-defer-merge-retry-consumer 2.1：WIP 延迟合回等待超限降级——
    # 周期消费者停止自动 merge-only 重试后的人工处置出口（窗口 90 分钟/轮数
    # 6 次任一超限）。major：与 WIP 重叠阻塞同级（阻塞单 spec merge-back，
    # 非 critical）。
    "mergeback_wip_defer_stuck": "major",
    # fix-verify-uniform-failure-consumer：全场景同因失败（pass=0 且失败签名
    # 一致）——既可能是验证环境/夹具问题，也可能是场景本身缺陷；admin 需判类
    # 后走对应处置路径，不直接判 bug-found（同因哨有意不派生 fix）。
    "verify_uniform_failure": "major",
    # add-control-plane-silent-failure-guards D3：复位路径编程错误升级——
    # TypeError/AttributeError/NameError 是代码缺陷（实参不符/属性缺失/
    # 未定义名），重试无意义，Administrator 无法修复（非环境问题），须工程侧
    # 定位修正调用点/签名后人工处置闭环。
    "admin_reset_programming_error": "critical",
    # add-control-plane-silent-failure-guards D5：状态无驱动（implementing/
    # testing 无活动 run + 无存活子进程 + 无待派发超短阈值）——控制平面某条
    # 路径把 spec 留在运行态却没人驱动（本 SPEC 事故悬置 1h12m 正是此类），
    # 分钟级可发现、早于 stuck（160 分钟）。
    "orphaned_state": "major",
    # evo-run-failure-classification-circuitbreaker D3：评审链路连续 infra 失败
    # （403/402/429/quota/budget/余额/rate limit/provider 熔断/CLI 进程级崩溃）
    # 触发链路熔断——停止派发 + 冷却，critical 级（批量失败 = 全链路瘫痪窗口）。
    "run_infra_failure": "critical",
    # admin-dispatch-failure-escalation D1：Administrator 派发期编程错误——
    # 提示词构造/序列化/参数错误（TypeError/AttributeError/NameError/
    # ValueError）是框架代码缺陷（2026-09-14 20:26 stash_pop_conflict dict
    # evidence 穿透 str.replace 实证：prompt_builder.py:204），Administrator
    # 无法修复、重试无意义，须工程侧定位修正派发链后人工处置闭环。
    "admin_dispatch_programming_error": "critical",
}
SIGNAL_RECOMMENDATION = {
    "repeated_failures": "检查重复失败的根因（如构建/测试命令错误），必要时重置 spec 状态或修复框架配置",
    "flapping": "检查 spec 状态机空转回路（ready↔implementing），修复派发/恢复逻辑或人工介入",
    "stuck": "检查卡死 Agent 子进程（kill 并按需重启），或重置 spec 状态重新调度",
    "merge_streak": "检查 merge-back 冲突根因（stash/分支冲突），清理 git 状态后重新 merge",
    "blocked_stuck": "检查 blocked 是否误置（误判派生的假 spec）或确需人工决策；清理假 spec 或重置后重新调度，必要时升级",
    "daemon_errors": "检查 fenixd 重复 ERROR 的根因（同错误 10 分钟窗口内复现 ≥2 次），必要时重启 daemon",
    "family_explosion": "检修根因环境（如验证报告互相咬合导致 fix 递归）；确认放行一次则对父 SPEC 设置 _family_waiver=true",
    # 处置建议三源同表（锁冲突退避耗尽 / 恢复闭环复查未通过 / 假就绪滞留）：
    # 首句为锁冲突路径（历史主因），后两句覆盖「锁冲突前提为假」的形态
    # ——2026-09-17 refactor-facade-delegation 事故里 spec 从未获得过 worktree
    # 锁（依赖未满足），旧文案把处置引向「清理残留锁」这一无关方向。
    "dispatch_stalled": "先按 evidence 判来源：① 确为锁冲突（evidence 含 backoff schedule/锁冲突计数）→ 检查持锁进程是否为孤儿（ps/pgrep 确认后 kill），清理残留 worktree 锁后让 spec 重新派发；② 依赖未满足（evidence 含 dependencies not satisfied 或原因含依赖）→ 无需处置，等待依赖转入接受态后事件定向唤醒自动派发；③ 恢复闭环复查未通过 → 核查该 spec 卡死根因（run/进程/闸门）",
    # add-verdict-credibility-gate / design D6：处置建议指向环境核查 + 恢复路径
    "inconclusive_loop": "验证环境核查清单：① 被测实例是否就绪（serve/start 命令与端口）；② 资源与并行度（max_parallel 是否挤爆实例）；③ mock+SSE 链路（mock_api 是否误拦推流、SSE 是否断流）；④ 探针摘要（见 evidence 末轮 blocked_env 数）。恢复路径：人工处置后解冻 spec（unfreeze）并清 `_inconclusive_attempts`，后续 blocked-env 轮次从 1 重新计数",
    "verify_contract_missing": "Administrator 起草 .fenix/verify.yaml 验证契约：检查项目构建命令、静态目录、服务启动方式；草稿写临时路径 → bin/fenix_verify_contract.py 自证 → 全通才落位 → git 提交 → spec 复位 ready 触发重验证",
    # fix-verify-contract-signal-semantics B：覆盖重起草指引——先复核现有契约有效性；
    # 有效契约按 D4 权限边界默认不碰，用户已显式授权覆盖（evidence 含「覆盖确认=是」）
    # 时方可重起草；重起草草稿同样须经 bin/fenix_verify_contract.py 三段自证全通才落位。
    "verify_contract_redraft": "复核现有契约有效性：若契约仍有效，Administrator 按权限边界默认不碰，仅当用户已显式授权覆盖（evidence 含「覆盖确认=是」）时方可重起草；重起草草稿写临时路径 → bin/fenix_verify_contract.py 自证 → 全通才落位 → git 提交 → spec 复位 ready 触发重验证",
    # add-test-regression-tab 增强：仅补 regression 段（不动其余顶层键）。指引与
    # agents/administrator.md「仅补 regression 段」小节同源。
    "verify_regression_missing": "Administrator 仅补 regression 段（MUST NOT 改动 verify.yaml 的 prepare/serve/ready 与其它顶层键）：读现有契约 → 探测测试体系（package.json scripts.test / pyproject.toml pytest / go.mod / pom.xml surefire）→ 生成可产出 JUnit XML 的 cmd/output（模板见 agents/administrator.md）→ 把 regression 段追加/替换进 .fenix/verify.yaml → bin/fenix_verify_contract.py 自证 regression 行 → git 提交 → 处置记录留痕；无测试体系或探测不出可产出 JUnit XML 的命令时 MUST 省略该段并结案说明（不得臆造命令）",
    # fix-artifact-paths-hardcoded-default D3：产物路径起草手册指引——探测输入源、
    # 校验口径、确无产物的结案方式均见 agents/administrator.md「构建产物路径起草
    # 手册」小节；探测脚本 bin/fenix_detect_artifacts.py 输出候选路径（纯本地）。
    "build_artifact_paths_missing": "Administrator 起草 .fenix/config.yaml 的产物路径配置：bin/fenix_detect_artifacts.py 探测候选路径（输入源：package.json scripts / pyproject.toml / 目录结构 / project.type）→ 路径经 validate_build_artifact_paths 同口径校验 → 写 worktree.has_build_artifacts + build_artifact_paths → git 提交 → 处置记录留痕；确无产物写 has_build_artifacts=false 结案（不得用路径留空冒充已裁决）",
    # fix-mergeback-stashpop-silent-loss D1：核对指引——查 stash 栈确认条目去向，
    # 按 sha / 逐文件 git show 找回被自愈丢弃的改动，确认无独有内容后可清理条目。
    "stash_pop_conflict": "merge-back stash pop 冲突已自愈，主树已恢复可写但部分未提交改动被丢弃：git stash list 查条目去向（保留/drop + sha）；按告警中逐文件 git show <sha>:<file> 命令核对内容，仍需要的改动手动落回工作区；确认零独有内容后 git stash drop 清理",
    # evo-merge-back-wip-overlap-gate D1：阻塞策略下主树 WIP 与分支改动重叠导致
    # merge-back 中止的核对指引——重叠 ≠ 冲突，主树零污染，处置后重新放行即可。
    "mergeback_wip_overlap": "merge-back 被 WIP 重叠闸门阻塞（策略=block，主树零污染，未 stash/merge/pop）：提交（git add/commit）或 stash（git stash push）主树与分支重叠的未提交改动后，重新放行该 spec（ready 重派）继续 merge-back；改动找回用 git stash list 与逐文件 git show <sha>:<file>",
    # evo-add-wip-defer-merge-retry-consumer 2.1：等待超限降级处置指引——周期
    # 消费者已停止自动重试，人工是唯一出路（勿复位 ready 后干等：自动通道已关）。
    "mergeback_wip_defer_stuck": "WIP 延迟合回等待超限（窗口/轮数上限已到，自动重试已停止）：人工核对主树与分支改动路径重叠的未提交改动归属后，提交（git add/commit）或 stash（git stash push）主树重叠改动，再把该 spec 复位 ready 重新放行 merge-back；或人工完成该分支向主树的合并",
    # add-blocked-reverify-lane D2：env 阻塞处置建议同步复位收敛措辞——
    # 处置范围限于环境修复，result 写入后框架自动判定复位路径（实现分支已合并→
    # 直通道 testing 重验，否则→ready），无需手动 reset spec 状态。
    "verify_env_blocked": "验证环境阻塞（依赖/服务/端口问题）：Administrator 仅需修复环境；处置完成写 result 后框架自动判定复位路径（实现分支已合并→直通道 testing 重验；否则→ready 重实现），无需手动 reset spec 状态",
    # fix-verify-uniform-failure-consumer：全场景同因失败的分诊指引——先判失败
    # 类别再处置，勿直接当产品缺陷打回实现（同因哨有意不派生 fix）。
    "verify_uniform_failure": "全场景同因失败（pass=0 且失败签名一致），先判类别：① 验证夹具/环境缺失（如场景引用的辅助脚本/依赖在验证树不可达）→ 补齐验证基础设施后复位重验；② 场景本身缺陷（断言写错误、字段/协议不对）→ 修正场景文件 test_scenarios.json 与 scenarios.json 后复位重验；③ 确为产品缺陷（多场景同根因）→ 转人工决策是否打回实现。证据见本信号 evidence 的签名与 failed 计数，逐场景细节见 .fenix/verify-progress/<spec>/report.json",
    # add-control-plane-silent-failure-guards D3：代码缺陷处置指引——明确
    # Administrator 无法修复、勿派子 fix 反复重跑（缺陷在框架工程侧）。
    "admin_reset_programming_error": "代码缺陷（TypeError/AttributeError/NameError，调用点见 evidence）：Administrator 无法修复，勿派子 fix 反复重跑；须工程侧定位修正复位路径的调用点/签名后，由人工处置闭环该告警",
    # add-control-plane-silent-failure-guards D5：孤儿处置指引——经既有
    # Administrator 通道唤起；处置完成（resolved）后框架自动走复位直通道
    # （testing→verifier 重验入队 / implementing→ready 重实现），无需手动
    # reset spec 状态。
    "orphaned_state": "状态无驱动（implementing/testing 无活动 run/无存活子进程/无待派发，signal 阶段）：Administrator 核查驱动链路（派发/recovery 是否空转）并确认是否人工干预；处置完成写 result 后框架自动走复位直通道（testing→verifier 重验入队；implementing→ready 重实现），无需手动 reset spec 状态。pending/failed/escalated 后续阶段由处置记录 status/result 与升级告警承载；冷却过期后同信号可再次成条（_throttled 既有节流语义）",
    # evo-run-failure-classification-circuitbreaker D3：评审链路 infra 熔断处置指引。
    # 熔断是链路级自动保护（停止派发 + 冷却 + 冷却后自动恢复），Administrator 对
    # provider 配额/余额无操作杠杆，不唤起（design D3）；本表仅登记严重度/建议供
    # 审计与 Dashboard 展示。
    "run_infra_failure": "spec-review 链路连续 infra 失败触发熔断（403/402/429/quota/budget/余额/rate limit/provider 熔断/CLI 进程级崩溃）：冷却（默认 30 分钟）到期自动恢复重试；若反复熔断请检查 provider 配额/余额、模型链配置与 CLI 环境。Administrator 无操作杠杆，本信号不唤起",
    # admin-dispatch-failure-escalation D1：派发期编程错误处置指引——沿用
    # add-control-plane-silent-failure-guards 3.3 的文案模式：代码缺陷须
    # 工程侧定位、Administrator 无法修复、勿派子 fix 反复重跑。
    "admin_dispatch_programming_error": "代码缺陷（TypeError/AttributeError/NameError/ValueError，调用点与异常消息见 evidence）：Administrator 无法修复，勿派子 fix 反复重跑；须工程侧定位修正派发链（prompt_builder 提示词构造/序列化/参数）后，由人工处置闭环该告警",
}

# pm_engine 直接写入 store、由本监视器摄取唤起的信号类型（写入即待唤起型）。
# family_explosion 既有；dispatch_stalled 属 run 生命周期治理（锁冲突退避耗尽 /
# 恢复闭环复查未通过）；stash_pop_conflict 属 merge-back pop 冲突可视治理
# （fix-mergeback-stashpop-silent-loss D1）。
STORED_SIGNAL_TYPES = (
    "family_explosion",
    "dispatch_stalled",
    "verify_contract_missing",
    "stash_pop_conflict",
    # evo-merge-back-wip-overlap-gate D8：merge-back 前 WIP 重叠闸门阻塞
    # （mergeback_wip_overlap）由 pm_engine 在 merge 结果处理失败分支直发、
    # 本监视器摄取唤起——未收录则摄取循环 :691 continue 跳过、记录落 store
    # 后无人摄取、Administrator 不唤起（即「显式告警」目标落空）。
    "mergeback_wip_overlap",
    # evo-merge-back-spec-dir-inflight-guard D1a/D2：spec 目录在飞编辑顺延
    # 超限（窗口/轮数上限）回落「告警 + 等待人工处置」通道时由 pm_engine
    # 直发——未收录则记录落 store 后无人摄取、Administrator 不唤起，顺延
    # 超限的 spec 会「永远不再被处理」（比事故更差）。注意该形态 spec 保持
    # implementing（不降级 ready），周期巡检（admin_monitor orphaned_state
    # 只扫 implementing/testing、event_bus recover_orphan_ready 只扫 ready）
    # 无法单独兜底其可见性，本信号是本 SPEC 自有的告警出口（D1a 点名）。
    "mergeback_spec_dir_inflight_stuck",
    # evo-add-wip-defer-merge-retry-consumer 2.1：WIP 等待超限降级告警由
    # pm_engine 周期消费者直发——未收录则记录落 store 后无人摄取、
    # Administrator 不唤起，超限 spec 的「人工处置出口」落空。
    "mergeback_wip_defer_stuck",
    "verify_contract_redraft",
    # add-test-regression-tab 增强：UI 手动请求「仅补 regression 段」——未收录则
    # 记录落 store 后无人摄取（信号石沉大海）。证据含「项目名=」供无 spec 形态解析。
    "verify_regression_missing",
    # add-verdict-credibility-gate / design D6：连续 blocked-env 达阈值时
    # pm_engine 写入、本监视器摄取唤起（写入即待唤起型，recovery 尊重暂停
    # 标记，人工处置是唯一出路）。
    "inconclusive_loop",
    # fix-artifact-paths-hardcoded-default D3：merge-back WIP 重叠闸门写入的
    # 产物配置未裁决起草信号——未收录则记录落 store 后无人摄取，Administrator
    # 不唤起（「立即呼叫起草」目标落空）。证据含「项目名=」供无 spec 形态解析。
    "build_artifact_paths_missing",
    # 2026-09-14 原地修复（未走 SPEC）：全场景同因失败哨
    # （verification.py `_detect_uniform_verify_failure`）在 pass=0 且失败签名
    # 一致时写入本信号，文案自称「已呼叫 admin 介入判断」——但此前本表不含该
    # 类型，记录落 store 后无人摄取，信号石沉大海。事故实证：evo-planner-
    # scenario-schema-alignment 09-14 两轮 13/13 同因失败（验证夹具随 worktree
    # 清理丢失，写端非产品缺陷），两条信号 handled=False 悬置十余小时，夹具
    # 从未恢复，直到人工介入。补入本表后由 _detect_family_explosion 摄取唤起。
    "verify_uniform_failure",
)

# run_id 前缀 → 计入"失败 run"的 agent 类型（失败计数专用子集）
# ⚠️ 真源 = core/agent_runner/run_files.py:RUN_ID_AGENT_PREFIXES（新增 run 前缀
# 只改那里）；本表是它的**子集**——只列计入失败统计的前缀（planner-/test- 不计）。
# orphaned-state-probe-calibration：前缀归一（_spec_from_run_id）已改用真源全量
# 前缀表，本表**只**服务失败计数（_detect_repeated_failures 显式传入），不再服务
# 活跃度/归属判定。`repair-` 属实现通道（失败即实现失败）已补入；`planner-`/
# `test-` 仍不计入（不得随归一扩大计数口径——design 1 拆分约束）。
_RUN_PREFIXES = (
    "impl-",
    "verify-",
    "repair-",
    "planner-plan-",
    "planner-judge-",
    "dispute-judge-",
    "spec-review-",
    "admin-",
)

# ── daemon-error-escalation D6：错误指纹归一化（保守集）────────────
# 只归一化四类：ISO-8601 时间戳→@、UUID→~、≥16 位 hex→~、纯数字序列→#。
# 不动路径与文字骨架——过度归一化会把不同错误误聚合，而"≥2 次才升级"已提供缓冲。
_ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
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


# ── 无驱动判定（orphaned-state-signal R1 共用口径）──────────────────────
# admin_monitor._detect_orphaned_state 与 event_bus._recover_one 的 testing
# 恢复出口共用同一「无驱动」判定，防止双路径重复触发/口径漂移（design D6）。


def _pgrep_live_worktree(spec_name: str) -> bool:
    """pgrep 匹配 ``.claude/worktrees/{impl,verify,repair}-<spec>-*`` 的 claude 进程。

    与 event_bus.EventBus._pgrep_live_worktree 同语义（fix-dispatch-orphan
    D4 存活探测）；抽为模块级供 admin 检测与 event_bus 恢复共用同一口径。

    orphaned-state-probe-calibration 1.4：匹配集补入 ``repair``（worktree 目录
    名 ``repair-<spec>-<ts>``，core/worktree_manager.py:3479）——修复 repair 通道
    进程存活失明（2026-09-15 误报根因②）；事件间隙大于 ORPHANED_RUN_GRACE_SECONDS
    =120s 的残留窗口由本判据兜住。

    处置记录（fix-robustness-edge-cases 1.1，书面 defer）：``pgrep -f
    "{prefix}-{spec}-"`` 是 cmdline 子串匹配，spec 名互为前缀（fix-x vs
    fix-x-y）时 fix-x-y 的活跃进程会误证 fix-x 存活。判定对象是 worktree
    目录名而非 run 流文件，不在本 SPEC「run 流文件」字面范围内；误判方向
    为 fail-open（多做「存活」判定，不会误报 stuck/误杀），修复需先枚举
    worktree 目录再精确匹配，机制不同。承接方：待后续 worktree 活性相关
    SPEC 处理，本 SPEC 不引入。
    """
    try:
        for prefix in ("impl", "verify", "repair"):
            pattern = f"{prefix}-{spec_name}-"
            res = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0 and res.stdout.strip():
                return True
    except (subprocess.SubprocessError, OSError):
        return False
    return False


def _is_admin_run_id(stem: str) -> bool:
    """run 文件 stem 是否属于 Administrator 处置 run（admin- 前缀）。

    单点定义，两处委托（模块级 ``_has_recent_spec_run`` 与
    ``AdminMonitor._has_recent_progress``），勿二次漂移。admin run
    是**处置者**的活动，不是被处置 SPEC 的验证/实现驱动证据
    （fix-recovery-path-blockers D1）——驱动判定 MUST 排除它，否则
    Administrator 处置全过程该 spec 永恒满足「有近期写活动」→恢复路径
    永不推进（2026-09-18 add-spec-manual-activation 事故：预算耗尽停
    testing 后 75 分钟无任何恢复动作）。前缀取用 ``RUN_ID_AGENT_PREFIXES``
    真源（run_files.py，admin- 排首），禁硬编码散落。
    """
    from core.agent_runner.run_files import RUN_ID_AGENT_PREFIXES

    for prefix, _agent_type in RUN_ID_AGENT_PREFIXES:
        if stem.startswith(prefix):
            return prefix == "admin-"
    return False


def _spec_has_active_admin_run(store, spec: str, logger=None) -> bool:
    """该 spec 是否存在在飞/待派发的 Administrator run（任意 signal_type）。

    fix-recovery-path-blockers D2：按 ``(spec)`` 单键聚合 store 中
    ``kind == DISPOSITION`` 的记录，复用 ``_has_active_admin_run_for`` 的
    by_run 归并口径（某 ``admin_run_id`` 组 ``has_pending`` 且无终结兄弟
    记录才算在飞——已终结 run 含 superseded/interrupted/escalated 终结后
    仍滞留 store 的 pending 记录均不算）——但**去掉 signal_type 过滤**：
    admin 处置的 signal_type 可能是 ``verify_env_blocked`` /
    ``manual-intervention`` / ``stuck``，不只有 ``orphaned_state``，
    按 ``(spec, signal_type)`` 精确匹配会漏。

    模块级单一实现：``AdminMonitor._has_active_admin_run_for_spec`` 与
    ``event_bus`` 的两个守卫调用点都委托本函数（store 作为入参），勿复制
    第二份归并实现。判定异常 fail-open 返回 False（守卫故障不阻断恢复路径），
    异常记 WARNING（logger 可选注入）。
    """
    try:
        records = store.read_all()
    except Exception as e:
        if logger is not None:
            logger.warning(
                "admin_monitor",
                f"_spec_has_active_admin_run 判定异常 fail-open（{spec}）: "
                f"{type(e).__name__}: {e}",
            )
        return False
    by_run: dict = {}
    for rec in records:
        if rec.get("kind") != DISPOSITION:
            continue
        if rec.get("spec") != spec:
            continue
        rid = rec.get("admin_run_id")
        if not rid:
            continue
        status = rec.get("status") or rec.get("result")
        info = by_run.setdefault(rid, {"final": False, "has_pending": False})
        if status == "pending":
            info["has_pending"] = True
        else:
            info["final"] = True
    return any(info["has_pending"] and not info["final"] for info in by_run.values())


def _has_recent_spec_run(project_root, spec: str, now: float, window: float) -> bool:
    """该 spec 是否存在窗口内有写活动的 run 文件（有进度）——非 admin 前缀。

    与 ``AdminMonitor._has_recent_progress`` 同语义（impl/verify/planner/repair
    等非 admin 前缀经 ``_spec_from_run_id`` 归一），模块级供
    ``_detect_orphaned_state`` 与 ``event_bus`` 恢复共用。

    fix-recovery-path-blockers D1：Administrator 的处置 run（admin- 前缀）
    是处置者的活动，不是被处置 SPEC 的驱动证据——判定口径改为「是否存在
    **非 admin 前缀**的、写活动在宽限窗内的 run 文件」。仅有 admin run 时
    MUST 返回 False，使 spec_is_undriven 条件①成立、恢复路径可推进
    （2026-09-18 事故根因：旧判定把处置者活动误判为被处置 SPEC 的驱动，
    导致恢复判定全跳过）。

    两处实现共用 ``_is_admin_run_id``（单点定义），禁二次漂移。
    """
    if project_root is None:
        return False
    runs_dir = Path(project_root) / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return False
    try:
        files = list(runs_dir.glob("*.jsonl"))
    except OSError:
        return False
    for p in files:
        # fix-recovery-path-blockers D1：admin run 是处置者活动，不是被处置
        # SPEC 的驱动证据——排除 admin- 前缀（单点判定 _is_admin_run_id）。
        if _is_admin_run_id(p.stem):
            continue
        if AdminMonitor._spec_from_run_id(p.stem) != spec:
            continue
        try:
            if now - p.stat().st_mtime < window:
                return True
        except OSError:
            continue
    return False


def spec_is_undriven(
    project_root,
    spec_name: str,
    entry: dict,
    *,
    run_grace_seconds: float = ORPHANED_RUN_GRACE_SECONDS,
    pm_engine=None,
) -> bool:
    """「无驱动」判定（orphaned-state-signal R1 三条件，同一判定口径）。

    返回 True 当且仅当四者同时成立：
      ① 无活动 run 文件：该 spec 的 run 文件 mtime 均超出 run_grace_seconds
         （任意 run 前缀，含 repair-，orphaned-state-probe-calibration 1.3）；
      ② 无存活 agent 子进程：不存在 impl-<spec>- / verify-<spec>- /
         repair-<spec>- 模式进程（orphaned-state-probe-calibration 1.4）；
      ③ 无待派发：无 _cancelled_hold / start_after 未到 / 派发退避
         （_dispatch_backoff_until）未到期；
      ④ 无排队中的派发条目：pm_engine 给出时，该 spec 无待派发队列条目
         （见下）。
    任一不成立（长 run 仍在跑 / 进程仍存活 / 有意等待中 / 已入队等待槽位）
    → False——避免把正常长 run 或有意等待误判为孤儿。

    ④ 的由来（2026-09-18 取证，实证误报）：条件 ③ 只覆盖「结构化的有意等待」
    （start_after / 退避 / 取消保持），**不覆盖「已入队、正在等并发槽」**。
    派发成立的判据是 `_enqueue` 成功（引擎对「已入队」与「未派发」两种状态
    不做结构化区分），条目可在队列中等待数十分钟——排队等待时长由
    `agents.max_concurrent` 与优先级窗口共同决定，最坏 = 队列老化开窗
    （initial_wait + floor_levels × step_down，本项目 10+4×10 = 50 分钟）加上
    当前在飞 run 的剩余时长，而这些 run 的吞吐实测为小时级（`run_timeout_seconds`
    缺省 15000s，长 run 常以万秒计）。同一盲区已在假就绪巡检处以
    `PMEngine._queued_for_dispatch`（core/pm_engine/engine.py）豁免，
    本次把它按依赖倒置（注入 pm_engine，不在本模块读引擎状态）补到孤儿探测。

    实证（本 SPEC 'fix-verify-serving-disk-reclaim'）：07:55:24Z 处置直通道
    `transition_gate(testing) + verifier 入队`，条目此后一直在队列（并发槽被
    三个 P5 run 占满），08:07:23Z 与 23 分钟后 08:30Z 两轮巡检均判「无驱动」并
    各唤起一次 Administrator——两次都为误报，40 分钟后该 verifier 才实际起 run。

    保留 `pm_engine=None`（不判定 ④）：本函数是模块级工具，既有单元测试与
    外部调用只传三参；缺省行为与引入 ④ 之前逐位一致，调用点按需注入。

    admin_monitor 检测在此之上叠加「状态停留超短阈值」；event_bus 恢复在此
    之上叠加 _inconclusive_attempts 暂停守卫。二者共用本函数 → 同一判定口径。
    """
    if not isinstance(entry, dict):
        return False
    # ③ 有意等待族：人工取消保持 / start_after 定时 / 派发退避
    if entry.get("_cancelled_hold"):
        return False
    try:
        from core.state_machine import start_after_pending

        if start_after_pending(entry):
            return False
    except Exception:
        pass  # 判定失败不阻塞（fail-open，与既有恢复路径同容错）
    try:
        from core.pm_engine.dispatch import Dispatcher

        if Dispatcher._dispatch_backoffed(entry):
            return False
    except Exception:
        pass  # 同上 fail-open
    # ② 无存活 agent 子进程
    if _pgrep_live_worktree(spec_name):
        return False
    # ① 无活动 run 文件
    if _has_recent_spec_run(project_root, spec_name, time.time(), run_grace_seconds):
        return False
    # ④ 无排队中的派发条目（调用方注入 pm_engine 时判定；见 docstring）
    if pm_engine is not None and _queued_for_dispatch(pm_engine, spec_name):
        return False
    return True


def _queued_for_dispatch(pm_engine, spec_name: str) -> bool:
    """spec 是否有待派发条目（孤儿探测豁免用）。

    复用引擎既有的 `_queued_for_dispatch` 豁免实现（core/pm_engine/engine.py，
    假就绪巡检专用），使「已入队等待并发槽」在孤儿探测侧得到同一结论；接口
    不可用 / 判定异常一律 fail-open 返回 False（保持既有上报行为，不因本豁免
    故障掩掉真阳性）。

    行为核对（本 SPEC 实施时以代码为准）：引擎侧读取自己的 `_run_queue`，
    **不触发 `_process_queue`**（无副作用、不改队列、不派发），与 `_enqueue`
    的非阻塞语义一致——故本判定可在任意线程安全调用。
    """
    probe = getattr(pm_engine, "_queued_for_dispatch", None)
    if not callable(probe):
        return False
    try:
        return probe(spec_name) is True
    except Exception:
        return False


class AdminMonitor:
    """困境信号检测 + 节流 + 唤起调度。run_once() 为单次检测入口。"""

    def __init__(
        self,
        config: dict,
        state_machine,
        project_root,
        logger,
        store=None,
        agent_runner=None,
        pm_engine=None,
        code_review_executor=None,
    ):
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
        # add-code-review-agent-and-quality-tab：code-review 后台派发 executor
        # （对齐 fenixd._admin_executor 形态）——None 时回退同步执行（测试/禁用态）。
        self._code_review_executor = code_review_executor
        # code-review 在途标记（对齐 _evolution_in_flight 形态）：投递即置位、
        # worker 收尾复位。有在途 run 则本轮跳过（D3「单飞」）。
        # 锁定：检查点（admin 巡检线程）与手动信号消费（fenixd 主循环线程）
        # 双线程读-改-写，GIL 不保证「读 False→写 True」原子（check-then-set
        # 竞态：两线程同时通过单飞判定、各自派发同一 run_id 覆盖产物文件），
        # 用锁把判定+置位压成临界区（fix-ocr finding low）。
        self._code_review_in_flight = False
        self._code_review_lock = threading.Lock()
        # 429 限流重派（add-code-review-concurrency-and-429-resilience D4）：
        # _code_review_ratelimit_redispatches：本生命周期内已执行的重派次数
        # （上限 RATELIMIT_REDISPATCH_MAX=1，防限流期重派风暴——重派仍 429 按
        # 既有失败路径收场升级人工）；_code_review_redispatch_timer：冷却到期
        # 延迟重投递的 threading.Timer（同时存在至多一个，防重复排队）。
        self._code_review_ratelimit_redispatches = 0
        self._code_review_redispatch_timer: threading.Timer | None = None
        # add-test-regression-tab：regression 在途标记（对齐 _code_review_in_flight
        # 形态）：投递即置位、worker 收尾复位。锁定：检查点（admin 巡检线程）与
        # 手动信号消费（fenixd 主循环线程）双线程读-改-写，GIL 不保证原子，
        # 用锁把判定+置位压成临界区（同 code_review 同款处理）。
        self._regression_in_flight = False
        self._regression_lock = threading.Lock()
        # alert-noise-governance 3.1：daemon_errors 指纹级冷却状态。
        # _started_at：进程启动锚点（重启后冷却窗 = now − _started_at）；
        # _daemon_fp_escalated_at：fp → 本生命周期内最近一次产生升级信号的时刻
        # （生命周期内用内存时间戳；跨重启识别经 _daemon_fp_known 对账 admin
        # store 既有 daemon_errors 记录的 description 内嵌指纹前缀）。
        self._started_at = time.time()
        self._daemon_fp_escalated_at = {}
        # code-review item 9427d41c85ef：fixture 判定实例级 TTL 备忘。
        # _fixture_invocation_suppressed 每条信号都走一次 _is_fixture_project
        # （Registry.discover = YAML 读 + 扫描根目录级遍历）；夹具标记实践中
        # 静态，TTL 300s 内同项目只做一次真实解析（条目 (monotonic, bool)）。
        self._fixture_project_memo: dict = {}

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

    @property
    def reschedule_max(self) -> int:
        """中断-重派累计上限，config admin.reschedule_max 可覆盖，非法值回落 2。"""
        raw = self._get_config("admin.reschedule_max", MAX_RESCHEDULE)
        try:
            val = int(raw)
            return val if val >= 0 else MAX_RESCHEDULE
        except (TypeError, ValueError):
            return MAX_RESCHEDULE

    def _get_config(self, key: str, default=None):
        from .config import ConfigLoader

        return ConfigLoader.get(self.config, key, default)

    def _cfg_float(self, key: str, default: float) -> float:
        """配置 float 读取容错（code-review item 05dd3957faf7）。

        非法/缺类型值回落缺省，与 ``reschedule_max`` 的容错风格一致——
        巡检路径不得因单个配置键非法（如 "120m"）抛 ValueError 而中断
        整轮检测（_detect/_detect_orphaned_state 均无兜底）。
        """
        raw = self.admin_cfg.get(key, default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

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

        # admin-dispatch-failure-escalation D2：派发失败升级记录到期重试巡检
        # （挂在既有巡检循环，不新增线程/定时器；任何异常只记日志不阻断巡检）
        try:
            self._retry_due_dispatch_failures(now)
        except Exception as e:
            self.logger.error("admin_monitor", f"Dispatch-failure retry scan failed: {e}")

        # add-alert-auto-resolve D1：告警自动闭环扫描内联本巡检执行（不新增
        # 线程/定时器），复用当轮已读取的 STATE.md 状态表（design D3）
        try:
            self._run_alert_lifecycle(specs)
        except Exception as e:
            self.logger.error("admin_monitor", f"Alert lifecycle scan failed: {e}")

        # add-daily-self-review：每日自省调度检查点（design D1，挂在既有巡检
        # 循环，不新增线程/定时器）。enabled && 本地时间 ≥ run_at && 今日未执行
        # → 触发；enabled=false 全链路零动作。任何异常只记日志不阻断巡检。
        # add-code-review-agent-and-quality-tab：code-review 检查点 MUST 排在
        # self_review 之前——后者 _save_state 会在收尾把 self_review_state.json 的
        # last_run_at 覆写为「此刻」，而 window_start 正读该字段。若先跑自省再跑
        # 本检查点，窗口退化为 [now, now] → manifest 恒空 → 周期审查每天以
        # no_files 空转（design D3 时序）。
        try:
            self._run_code_review_checkpoint()
        except Exception as e:
            self.logger.error("admin_monitor", f"Code-review checkpoint failed: {e}")
        # add-code-review-sharded-out 3.1：code-review 事中零进度停滞告警
        # （复用巡检节拍，不新增线程/定时器；任何异常只记日志不阻断巡检）。
        try:
            self._check_code_review_stall()
        except Exception as e:
            self.logger.error("admin_monitor", f"Code-review stall check failed: {e}")
        # add-test-regression-tab：回归检查点（独立于 code-review/self_review 的
        # 防重状态文件；守卫链 = enabled → run_at 时点 → 同自然日防重 → 单飞 →
        # 有 regression 段）。放 code_review 之后：与自省时点同频，但不依赖
        # self_review_state 字段，顺序不敏感。
        try:
            self._run_regression_checkpoint()
        except Exception as e:
            self.logger.error("admin_monitor", f"Regression checkpoint failed: {e}")
        try:
            self._run_self_review_checkpoint()
        except Exception as e:
            self.logger.error("admin_monitor", f"Self-review checkpoint failed: {e}")
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

    def _run_code_review_checkpoint(self) -> dict:
        """周期性代码审查调度检查点（add-code-review-agent-and-quality-tab）。

        守卫与自省同源：``admin.code_review.enabled``、同自然日防重、
        ``run_at`` 未到不跑；manifest 为空则跳过（不派发空 run）；已有
        code-review run 在跑则跳过（单飞）。

        派发经 ``_code_review_executor`` 投递后台 worker 执行完整 run（对齐
        fenixd._evolution_worker 形态），MUST NOT 在巡检线程内同步跑完整
        审查——整轮审查（数十文件 LLM 调用）若照搬会让 admin 巡检停摆整个
        审查时长。单飞标记在投递即置位、worker 收尾复位（对齐
        ``_evolution_in_flight``）。``admin.code_review.enabled`` 为 false
        时全链路零动作（不派发、不写产物）。

        返回调度结果 dict（供测试断言；巡检本身不消费返回值）。
        """
        from .config import ConfigLoader
        from .self_review import _parse_run_at, local_today_str

        from core.code_review import (
            compute_window,
            collect_manifest,
            save_code_review_state,
            read_code_review_state,
        )

        cr_cfg = ConfigLoader.get_code_review_config(self.config)
        if not cr_cfg.get("enabled"):
            return {"triggered": False, "reason": "disabled"}

        sr_cfg = ConfigLoader.get_self_review_config(self.config)
        now = datetime.now()

        # run_at 未到不触发（与自省同口径）
        if now < _parse_run_at(sr_cfg["run_at"], now.date()):
            return {"triggered": False, "reason": "before_run_at"}

        # 同自然日防重（独立状态文件，MUST NOT 复用 self_review_state.json 的
        # last_run_date——后者会被同轮自省写为今天导致本车道永不派发）
        state = read_code_review_state(self.project_root)
        if state.get("last_run_date") == local_today_str():
            return {"triggered": False, "reason": "already_ran_today"}

        # 单飞：已有 code-review run 在跑 → 跳过
        # （判定+置位在锁内原子完成，防双线程同时通过单飞判定派发同一 run_id）
        with self._code_review_lock:
            if self._code_review_in_flight:
                return {"triggered": False, "reason": "already_running"}
            if self.agent_runner is not None:
                running = getattr(self.agent_runner, "_running_agents", None) or {}
                if any(str(rid).startswith("code-review-") for rid in running):
                    self._code_review_in_flight = True
                    return {"triggered": False, "reason": "already_running_agent"}
            self._code_review_in_flight = True

        # 审查范围（add-code-review-scope-config task 2.1）：读配置缺省回退已由
        # get_code_review_config 统一兜底（此处恒拿到 "window"/"full" 二值）。
        # scope 只改变「收集什么」（full 档 window_start=None），不改变「何时
        # 触发、算谁跑的」——review_kind 恒为 scheduled（见下方投递处）。
        review_scope = cr_cfg.get("scope") if cr_cfg.get("scope") == "full" else "window"

        # 窗口 + manifest（与自省同源窗口口径，task 3.3 MUST 在 self_review 之前
        # 调用，保证 window_start 读到上一次自省时刻而非本轮自省刚写入的 now）。
        # window 档：窗口收集（window_start 同源自省）；full 档：全仓收集
        # （window_start=None，对齐 manual_full 形态；不消费自省窗口，但自省
        # 本身不受影响——两者只是共享触发时点）。
        window_start, window_kind = compute_window(self.project_root)
        if review_scope == "full":
            manifest = collect_manifest(self.project_root, scope="full", window_start=None)
        else:
            manifest = collect_manifest(self.project_root, scope="window", window_start=window_start)
        if not manifest:
            # manifest 为空：记录并跳过（不派发空 run——design Risk「空场景
            # 白洗」），同日防重仍然写入（当日不重试，与自省零活动跳过同口径）。
            # 复位单飞标志（上方锁内已置位）——否则本车道永久被「已运行」挡住。
            #
            # add-code-review-scope-config task 2.2：本分支对 full 档实际不可达
            # ——full 档走 git ls-files 全仓受控文件，受控仓必有文件；真为空只
            # 可能是仓已非受控态（异常态），按既有 no_files 路径记录并跳过即可，
            # 不新增分支。日志文案按档位区分：full 档 window_start=None，既有
            # 「窗口内无文件变更…window_start=…」措辞失真（误导排障判别），改带
            # scope 标注；window 档日志保持逐字节不变。
            with self._code_review_lock:
                self._code_review_in_flight = False
            save_code_review_state(self.project_root, local_today_str())
            if review_scope == "full":
                self.logger.info(
                    "admin_monitor",
                    "code-review: 全仓 manifest 为空（异常态，受控仓不应出现），"
                    f"跳过本次周期审查（scope={review_scope}）",
                )
            else:
                self.logger.info(
                    "admin_monitor",
                    "code-review: 窗口内无文件变更，跳过本次周期审查"
                    f"（window_start={window_start.isoformat()}, kind={window_kind}）",
                )
            return {"triggered": True, "ok": True, "reason": "no_files", "date": local_today_str()}

        # 上限截断
        max_files = cr_cfg.get("max_files", 500)
        if max_files > 0 and len(manifest) > max_files:
            manifest = manifest[:max_files]

        # 防重状态写入（投递前即写——投递成功/失败均不重试，与自省同口径）
        save_code_review_state(self.project_root, local_today_str())

        # 投递后台 worker（对齐 _evolution_worker 形态）
        review_kind = "scheduled"

        ratelimit_intent: dict | None = None

        def _worker():
            nonlocal ratelimit_intent
            try:
                result = self.agent_runner.run_code_review(
                    manifest,
                    review_kind=review_kind,
                    window_start=window_start if review_scope == "window" else None,
                    scope=review_scope,
                )
                self.logger.info(
                    "admin_monitor",
                    f"code-review 周期审查完成：run_id={result.run_id}, "
                    f"inserted={result.inserted}, updated={result.updated}, "
                    f"resolved={result.resolved}, shards={result.shards}"
                    + (f", error={result.error}" if result.error else ""),
                )
                # 429 打死 run 的自动重派消费侧（add-code-review-concurrency-
                # and-429-resilience D4，task 5.3）：终态结果携带
                # ratelimit_redispatch 意图（含最早冷却到期时刻）→ 收场复位
                # 单飞后经 threading.Timer 延迟重投递（冷却期内 MUST NOT 重派）。
                ratelimit_intent = getattr(result, "ratelimit_redispatch", None)
            except Exception as e:
                self.logger.error("admin_monitor", f"code-review 周期审查异常: {e}")
            finally:
                with self._code_review_lock:
                    self._code_review_in_flight = False
            if ratelimit_intent:
                self._schedule_ratelimit_redispatch(
                    manifest=manifest,
                    review_kind=review_kind,
                    window_start=window_start if review_scope == "window" else None,
                    scope=review_scope,
                    intent=ratelimit_intent,
                )

        try:
            if self._code_review_executor is not None:
                self._code_review_executor.submit(_worker)
            else:
                # executor 不可用（测试/禁用态）：同步执行（行为不变，保逃生门）
                _worker()
            return {"triggered": True, "ok": True, "reason": "scheduled", "date": local_today_str()}
        except Exception as e:
            with self._code_review_lock:
                self._code_review_in_flight = False
            self.logger.error("admin_monitor", f"code-review 周期审查派发失败: {e}")
            return {"triggered": True, "ok": False, "reason": f"exception: {e}", "date": local_today_str()}

    # ── 429 限流重派消费侧（add-code-review-concurrency-and-429-resilience D4，task 5.3）──
    def _schedule_ratelimit_redispatch(self, manifest, review_kind, window_start,
                                       scope, intent: dict) -> None:
        """登记 429 重派意图并经延迟投递在冷却到期后重调 ``run_code_review`` 一次。

        ``run_code_review`` 唯一生产调用方（本文件 ``_run_code_review_checkpoint``
        的 ``_worker``）观测到终态结果携带 ``ratelimit_redispatch`` 意图（含最早
        冷却到期时刻）时进入本方法。守卫：
        - 重派上限常量 ``RATELIMIT_REDISPATCH_MAX = 1``：本 monitor 生命周期内
          已重派过即不再重派（重派仍 429 按既有失败路径收场，MUST NOT 无限重派）；
        - 至多一个待发 Timer（重复意图不重复排队）；
        - 冷却到期前 MUST NOT 重派：延迟 = max(0, cooldown_until_epoch − now)。
        重派以**原 manifest/参数**复调（幂等保障既有：聚合读侧按 file 去重 +
        提示词「不重审」纪律），并携带 ``redispatch_of`` 供运行记录标注重派缘由。
        """
        from core.agent_runner.provider_circuit import RATELIMIT_REDISPATCH_MAX

        run_id = str(intent.get("run_id") or "")
        with self._code_review_lock:
            if self._code_review_ratelimit_redispatches >= RATELIMIT_REDISPATCH_MAX:
                self.logger.warning(
                    "admin_monitor",
                    f"code-review 429 重派跳过：已达上限 {RATELIMIT_REDISPATCH_MAX}"
                    f"（原 run {run_id}，按既有失败路径收场）",
                )
                return
            if self._code_review_redispatch_timer is not None:
                self.logger.info(
                    "admin_monitor",
                    f"code-review 429 重派跳过：已有待发重派 Timer（原 run {run_id}）",
                )
                return
            # 登记即占额（防并发意图重复消耗/重复排队）；消费侧若因单飞放弃
            # 不退额——防风暴优先。
            self._code_review_ratelimit_redispatches += 1
            delay = max(0.0, float(intent.get("cooldown_until_epoch") or 0.0) - time.time())
            timer = threading.Timer(
                delay,
                self._consume_ratelimit_redispatch,
                args=(manifest, review_kind, window_start, scope, run_id),
            )
            timer.daemon = True
            self._code_review_redispatch_timer = timer
        try:
            self.logger.info(
                "admin_monitor",
                f"code-review 429 重派已排程：原 run {run_id}，{int(delay)}s 后"
                f"（provider 限流冷却到期）以原 manifest 重派一次",
            )
            timer.start()
        except Exception as e:
            # code-review item 7e5fbd614cdd：投递失败回滚，对齐下方
            # _consume_ratelimit_redispatch 的 submit 失败回滚口径——配额占用与
            # 句柄登记已在锁内完成，start 失败若不回滚，句柄唯一清零点（冷却回调）
            # 永不触发 → 幽灵 Timer 句柄 + 配额已消耗，本生命周期唯一一次重派
            # 机会被永久占用（后续意图只会命中误导性的「已达上限」跳过日志）。
            with self._code_review_lock:
                self._code_review_ratelimit_redispatches -= 1
                if self._code_review_redispatch_timer is timer:
                    self._code_review_redispatch_timer = None
            timer.cancel()
            self.logger.error(
                "admin_monitor",
                f"code-review 429 重派排程失败: {e}（原 run {run_id}，"
                f"已回滚重派配额与 Timer 句柄）",
            )

    def _consume_ratelimit_redispatch(self, manifest, review_kind, window_start,
                                      scope, original_run_id: str) -> None:
        """冷却到期回调：以原 manifest/参数重调 ``run_code_review`` 一次（task 5.3）。

        单飞守卫：车道忙（新周期/手动 run 在跑）时放弃本次重派（原 run 的
        分片产物仍被 error 收场抢救落账，不因放弃而丢失）。
        """
        # Timer 已触发：先摘句柄（允许后续新意图再排程——上限计数仍守卫）
        with self._code_review_lock:
            self._code_review_redispatch_timer = None
            if self._code_review_in_flight:
                self.logger.warning(
                    "admin_monitor",
                    f"code-review 429 重派放弃：车道单飞中有在途 run"
                    f"（原 run {original_run_id}）",
                )
                return
            self._code_review_in_flight = True

        def _worker():
            try:
                result = self.agent_runner.run_code_review(
                    manifest,
                    review_kind=review_kind,
                    window_start=window_start,
                    scope=scope,
                    redispatch_of=original_run_id or None,
                )
                self.logger.info(
                    "admin_monitor",
                    f"code-review 429 重派完成：redispatch_of={original_run_id}, "
                    f"run_id={result.run_id}, inserted={result.inserted}, "
                    f"updated={result.updated}, shards={result.shards}"
                    + (f", error={result.error}" if result.error else ""),
                )
            except Exception as e:
                self.logger.error("admin_monitor", f"code-review 429 重派异常: {e}")
            finally:
                with self._code_review_lock:
                    self._code_review_in_flight = False

        try:
            if self._code_review_executor is not None:
                self._code_review_executor.submit(_worker)
            else:
                _worker()
        except Exception as e:
            with self._code_review_lock:
                self._code_review_in_flight = False
            self.logger.error("admin_monitor", f"code-review 429 重派投递失败: {e}")

    def _check_code_review_stall(self) -> None:
        """code-review 事中零进度停滞告警（add-code-review-sharded-out 3.1/D4）。

        检测逻辑在 ``core.code_review.check_progress_stall``（复用
        ``read_progress`` 聚合口径 + manifest ``requested_at`` 算已运行时长；
        run 终态 running=false 短路）。本方法只负责落告警：经 AdminStore
        ``append_if_absent``（单次排他锁内查重+追加，对齐 UI 信号写入同款
        防 check-then-act 竞态）以 ``code-review-stall-<run_id>`` 为去重键——
        单 run 至多一条。kind=ESCALATION（人工告警，未处理时 Dashboard 横幅
        展示），文案含 run_id / 已运行分钟 / 聚合 done=0 事实与「疑似子代理
        等待收工模式」归因提示，供人工直接判断是否取消该 run。
        """
        from core.code_review import check_progress_stall

        hit = check_progress_stall(self.project_root, datetime.now())
        if hit is None:
            return
        run_id = str(hit.get("run_id") or "")
        minutes = int(hit.get("minutes") or 0)
        if not run_id:
            return
        dedup_key = f"code-review-stall-{run_id}"

        def _inflight(rec: dict) -> bool:
            return (
                rec.get("kind") == ESCALATION
                and rec.get("signal_type") == "code_review_stall"
                and rec.get("dedup_key") == dedup_key
            )

        rec = self.store.append_if_absent(
            {
                "kind": ESCALATION,
                "signal_type": "code_review_stall",
                "dedup_key": dedup_key,
                "spec": None,
                "severity": "major",
                "description": (
                    f"code-review 审查零进度：run {run_id} 已运行 {minutes} 分钟，"
                    f"主产物与分片聚合 done=0（零文件落盘），疑似「async 子代理"
                    f"等待收工模式」——非交互模式下 turn 结束即进程退出，"
                    f"异步批次结果永不回收"
                ),
                "evidence": (
                    f"check_progress_stall: run_id={run_id}, minutes={minutes}, "
                    f"done=0（聚合主产物与分片）"
                ),
                "action_taken": f"AdminMonitor 周期节拍检测（去重键 {dedup_key}，单 run 至多一条）",
                "recommended_action": (
                    "人工判断是否取消该 run：可在项目页「代码审查」分面对照 "
                    "manifest 与已落盘分片；取消后重派前建议复核 agents/code-review.md "
                    "的分片直写纪律是否生效"
                ),
            },
            _inflight,
        )
        if rec is not None:
            self.logger.info(
                "admin_monitor",
                f"code-review 停滞告警已落：run_id={run_id}, minutes={minutes}"
                f"（去重键 {dedup_key}）",
            )

    def _run_regression_checkpoint(self) -> dict:
        """周期性全量回归调度检查点（add-test-regression-tab）。

        守卫链与 code-review 检查点同源：
        ``admin.regression.enabled`` → ``run_at`` 时点 → 同自然日防重（独立
        状态文件 .fenix/regression/state.json 的 last_run_date，MUST NOT
        复用自省/code-review 的防重状态）→ 单飞（_regression_in_flight）→
        项目 verify.yaml 有有效 regression 段（无则跳过并记日志）。

        派发经 ``_code_review_executor`` 同款 executor（_admin_executor）
        投递后台 worker，MUST NOT 在巡检线程内同步跑完整回归——回归可跑
        1800s，照搬会让 admin 巡检停摆整个回归时长。单飞标记在投递即置位、
        worker 收尾复位（对齐 _code_review_in_flight）。

        返回调度结果 dict（供测试断言；巡检本身不消费返回值）。
        """
        from .config import ConfigLoader
        from .self_review import _parse_run_at, local_today_str

        from core.regression import read_state, save_state
        from core.verify_contract import load_verify_contract

        reg_cfg = ConfigLoader.get_regression_config(self.config)
        if not reg_cfg.get("enabled"):
            return {"triggered": False, "reason": "disabled"}

        sr_cfg = ConfigLoader.get_self_review_config(self.config)
        now = datetime.now()

        # run_at 未到不触发（与自省同口径：与每日自省同周期）
        if now < _parse_run_at(sr_cfg["run_at"], now.date()):
            return {"triggered": False, "reason": "before_run_at"}

        # 同自然日防重（独立状态文件，MUST NOT 复用 self_review/code_review
        # 的 last_run_date——code-review 当年踩过的坑）
        state = read_state(self.project_root)
        if state.get("last_run_date") == local_today_str():
            return {"triggered": False, "reason": "already_ran_today"}

        # 单飞：已有回归在跑 → 跳过
        with self._regression_lock:
            if self._regression_in_flight:
                return {"triggered": False, "reason": "already_running"}
            if self.agent_runner is not None:
                running = getattr(self.agent_runner, "_running_agents", None) or {}
                if any(str(rid).startswith("regression-") for rid in running):
                    self._regression_in_flight = True
                    return {"triggered": False, "reason": "already_running_agent"}
            self._regression_in_flight = True

        # 无有效 regression 段 → 跳过并复位单飞标志
        contract = load_verify_contract(self.project_root, logger=self.logger)
        if contract is None or contract.regression is None:
            with self._regression_lock:
                self._regression_in_flight = False
            self.logger.info(
                "admin_monitor",
                "regression: 项目未配置全量回归（verify.yaml regression 段缺失），"
                "跳过周期回归",
            )
            return {"triggered": False, "reason": "not_configured"}

        spec = contract.regression
        # 防重状态写入（投递前即写——投递成功/失败均不重试，与自省同口径）
        save_state(self.project_root, local_today_str())

        def _worker():
            try:
                result = self.agent_runner.run_regression(spec, reason="scheduled")
                self.logger.info(
                    "admin_monitor",
                    f"regression 周期回归完成：run_id={result.run_id}, "
                    f"status={result.status}"
                    + (f", error={result.error}" if result.error else ""),
                )
            except Exception as e:
                self.logger.error("admin_monitor", f"regression 周期回归异常: {e}")
            finally:
                with self._regression_lock:
                    self._regression_in_flight = False

        try:
            if self._code_review_executor is not None:
                self._code_review_executor.submit(_worker)
            else:
                # executor 不可用（测试/禁用态）：同步执行（行为不变，保逃生门）
                _worker()
            return {"triggered": True, "ok": True, "reason": "scheduled", "date": local_today_str()}
        except Exception as e:
            with self._regression_lock:
                self._regression_in_flight = False
            self.logger.error("admin_monitor", f"regression 周期回归派发失败: {e}")
            return {"triggered": True, "ok": False, "reason": f"exception: {e}", "date": local_today_str()}

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
        pending = [r for r in records if r.get("kind") == ESCALATION and not r.get("handled")]
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
                f"stale alert(s)" + ("（存量回填）" if backfill else ""),
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
        signals.extend(self._detect_orphaned_state(specs, now))
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
            signals.append(
                self._make_signal(
                    "blocked_stuck",
                    name,
                    f"'{name}' 处于 blocked 超过 {int(elapsed)} 分钟未处理",
                    f"updated={updated_str}，阈值 {threshold} 分钟",
                )
            )
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
            if not spec and stype in (
                "verify_contract_missing",
                "verify_contract_redraft",
                # add-test-regression-tab 增强：UI 手动「仅补 regression 段」信号同
                # 无 spec，按「项目名=」解析（未加入则 spec=None → 被丢弃）。
                "verify_regression_missing",
                # fix-artifact-paths-hardcoded-default D3：WIP 闸门信号无 spec
                # （非常规分支名退化为仅靠 evidence）时同样从「项目名=」解析。
                "build_artifact_paths_missing",
            ):
                # 从 evidence 提取项目名（格式: "项目名=<name>; ..."）
                evidence = rec.get("evidence") or ""
                for part in evidence.split(";"):
                    part = part.strip()
                    if part.startswith("项目名="):
                        spec = part.split("=", 1)[1].strip()
                        break
            if not spec:
                continue
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
            # 前提复核守卫（陈旧快照，2026-09-17 事故；常量注释见文件头
            # _STALL_PREMISE_SIGNAL_TYPES）：dispatch_stalled 的困境前提是
            # 「spec 处于 ready 且派发未成立」。记录从写入到被本方法摄取之间
            # 存在一个巡检周期以上的滞后，期间 spec 可能已被正常派发／推进——
            # 此时记录里的「ready 滞留」已被事实推翻，唤起只会得到空转 admin
            # run。spec 当前状态「存在且已非 ready」→ 标记 escalated 核销跳过
            # （记录保留可审计，下一 tick 不再重捞；与上方终态守卫同范式）。
            #
            # 只读得到 status 为前提复核的适用条件：status 缺失（spec 条目不存在
            # 或未写 status 字段）时前提不可推翻，fail-open 照常摄取——宁多唤起
            # 一次也不掩真阳性。
            _stall_status = spec_entry.get("status")
            if (
                stype in _STALL_PREMISE_SIGNAL_TYPES
                and _stall_status
                and _stall_status != _STALL_PREMISE_READY
            ):
                marked = self.store.mark_escalated(rec.get("id"))
                self.logger.info(
                    "admin_monitor",
                    f"{stype}: spec '{spec}' 已非 ready"
                    f"（status={_stall_status}）——记录快照的"
                    f"「ready 滞留」前提已被事实推翻，跳过唤起",
                    {"mark_escalated": bool(marked), "record_id": rec.get("id")},
                )
                continue
            # code-review 9e031d3e7c7f：缺 description 的兜底文案不再用三元链
            # 硬编码——三元链仅覆盖 family_explosion/dispatch_stalled/
            # inconclusive_loop，其余存储型信号（mergeback_wip_overlap/
            # stash_pop_conflict/verify_uniform_failure 等）会误落
            # 「AI 起草验证契约请求（UI 手动触发）」文案，与信号语义完全不符。
            # 改按 SIGNAL_RECOMMENDATION 表推导；表外类型（如
            # mergeback_spec_dir_inflight_stuck）用中性兜底。
            signal = self._make_signal(
                stype,
                spec,
                rec.get("description")
                or SIGNAL_RECOMMENDATION.get(stype)
                or f"存储信号 {stype}（记录缺 description，处置方向见 evidence）",
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
            # fixture 项目抑制（alert-noise-governance 5.1）：记录已 mark
            # escalated（消费掉「写入即待唤起」语义，防每轮重复摄取与重复
            # INFO），但不创建 admin run；记录本身保留可查（5.2 不删除）。
            if self._fixture_invocation_suppressed(signal):
                continue
            self.logger.warning(
                "admin_monitor",
                f"{stype}: invoking Administrator for '{spec}'",
                {"signal": signal},
            )
            self._invoke_administrator(signal, rec)
        return signals

    def _make_signal(self, signal_type: str, spec, description: str, evidence) -> dict:
        # add-human-adjudication-choices 2.7 桶 0 确认：本监视器发射的
        # stale_code / transient_break_storm / run_infra_failure / run_cancelled
        # 属桶 0（系统级/自动收敛信号， Administrator 无操作杠杆或走内部处置），
        # 裁决注册表（core.dashboard.data.adjudication_choices）不覆盖——
        # 本构造器不注入 ``choices`` 键，前端告警区对其保持「知道了」形态。
        # 桶 2 信号的 choices 注入在各发射点（family._send_human_escalation_alert
        # 中心接线 / token_budget / mergeback），不经本路径。
        # 归一：多路径复用 _make_signal 注入 evidence，结构化值（dict/list）会在
        # 此处直接进 prompt（str.replace）→ TypeError，故在信号构造点先序列化为
        # JSON 串（与 admin_store._coerce_evidence 同口径，双保险）。
        if evidence is not None and not isinstance(evidence, str):
            try:
                evidence = json.dumps(evidence, ensure_ascii=False)
            except (TypeError, ValueError):
                evidence = str(evidence)
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
            # stat 守卫（code-review item 57cb3554af55）：glob 与 stat 之间
            # .fenix/runs 会被 runs 保留清理并发删除/归档（archive/），文件被
            # 移走时 p.stat() 抛 FileNotFoundError/OSError——run_once 对
            # _detect 规则链无兜底 try，任一异常即中断当轮全部信号检测与后续
            # code-review/self-review 检查点。跳过消失的文件，与同文件
            # _has_recent_spec_run / _has_recent_progress 的既有保护对齐。
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                continue
            # orphaned-state-probe-calibration：失败计数 MUST 用失败前缀子集
            # （_RUN_PREFIXES），不能随归一默认改用全量前缀——否则 planner-/
            # test- 失败 run 会被纳入 3 次/30 分钟计数、产生新告警类别
            # （design 1 拆分：计数口径除 repair- 的显式补入外不得变化）。
            spec = self._spec_from_run_id(p.stem, _RUN_PREFIXES)
            if not spec:
                continue
            if self._run_terminal_status(p) != "error":
                continue
            per_spec.setdefault(spec, 0)
            per_spec[spec] += 1

        for spec, count in per_spec.items():
            if count >= REPEAT_FAILURE_THRESHOLD:
                signals.append(
                    self._make_signal(
                        "repeated_failures",
                        spec,
                        f"'{spec}' 在 {REPEAT_FAILURE_WINDOW_MINUTES} 分钟内出现 {count} 次失败 run",
                        f"最近失败 run ≥{REPEAT_FAILURE_THRESHOLD}（{count} 次），窗口 {REPEAT_FAILURE_WINDOW_MINUTES} 分钟",
                    )
                )
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
                signals.append(
                    self._make_signal(
                        "flapping",
                        spec,
                        f"'{spec}' 在 {FLAPPING_WINDOW_MINUTES} 分钟内 ready↔implementing 切换 {transitions} 次",
                        f"状态序列: {seq}",
                    )
                )
        return signals

    def _detect_stuck(self, specs: dict, now: float) -> list:
        """implementing/testing 超阈值无 run 进度。

        stuck-signal-hygiene：在既有「文件 mtime 判据」上叠加两道反证——
          D1 进程存活反证：该 spec 存在登记在跑且进程存活的 run
            （AgentRunner.running_run_ids()，进程表为真相）→ 直接跳过。
            转录文件停止增长（mtime 超出宽限）但 agent 子进程仍存活的边界
            场景不再误报；hang 场景（进程存活但无输出）由 run_timeout_seconds
            超时兜底，不判 stuck。
          D3 处置后静默期：最近一条 result∈{resolved, partially-resolved}
            处置距 now < stuck_silence_minutes → 跳过（处置成功后的短期
            复发不产信号）；result=escalated 不静默（人工处置是唯一出路）。
        """
        signals = []
        # 容错读取与 _cfg_float 风格统一（同 _detect_orphaned_state）：值由
        # get_admin_config 预归一，此处防直读脏配置时巡检中断。
        threshold_minutes = self._cfg_float("stuck_threshold_minutes", 0)
        grace_minutes = max(STUCK_GRACE_MINUTES, self.interval_minutes * 2)
        silence_minutes = self._cfg_float("stuck_silence_minutes", 120)
        runs_dir = self.project_root / ".fenix" / "runs"
        # D1：进程存活反证数据源——agent_runner 存在时取「进程仍存活」的
        # run_id 集（_running_agents 进程表为真相）；None（CLI/测试态）→
        # 跳过本检查、退回文件活跃度判据。延迟获取：轮内只算一次。
        running_ids = None
        if self.agent_runner is not None:
            try:
                running_ids = set(self.agent_runner.running_run_ids() or [])
            except Exception as e:
                # 进程表读取异常不阻断巡检：退回文件判据（与其余检测路径同容错）
                self.logger.warning(
                    "admin_monitor",
                    f"running_run_ids() 读取失败，退回文件判据: {e}",
                )
                running_ids = None
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
            # D1 进程存活反证：run_id → spec 归属必须用 _spec_from_run_id
            # （本模块既有方法，正则 -(?:a|r)\d+ 同时覆盖 attempt 与 -r<n> 瞬态
            # 重试后缀）。禁止 run_spec_part（run_files.py:66）：它只剥离 -a\d+，
            # 对 <base>-a1-r1 返回 <base>-a1-r1 归属失败——正是 8e510a87 修复的
            # -r<n> 根因形态，沿用会让「进程存活反证」在瞬态重试期间重新失效。
            if running_ids is not None and any(
                self._spec_from_run_id(rid) == name for rid in running_ids
            ):
                self.logger.debug(
                    "admin_monitor",
                    f"Skipping stuck for '{name}': alive run process(es) registered",
                )
                continue
            if self._has_recent_progress(name, runs_dir, now, grace_minutes * 60):
                continue
            # D3 处置后静默期：最近一条成功处置距 now < silence 窗口 → 跳过。
            # result=escalated（升级人工）不匹配 resolved/partially-resolved，
            # 天然不触发静默——人工处置是唯一出路，不得被静默吞掉。
            if silence_minutes > 0:
                disp = self.store.latest_resolved_disposition(name, "stuck")
                if disp is not None:
                    disp_created_str = disp.get("created") or ""
                    try:
                        disp_created = datetime.fromisoformat(
                            disp_created_str.replace("Z", "+00:00")
                        )
                        disp_age_minutes = (now - disp_created.timestamp()) / 60
                    except (ValueError, TypeError):
                        disp_age_minutes = None
                    if disp_age_minutes is not None and disp_age_minutes < silence_minutes:
                        self.logger.debug(
                            "admin_monitor",
                            f"Skipping stuck for '{name}': resolved disposition "
                            f"{int(disp_age_minutes)}m ago < silence "
                            f"{int(silence_minutes)}m",
                        )
                        continue
            signals.append(
                self._make_signal(
                    "stuck",
                    name,
                    f"'{name}' 卡在 {status} 超过 {int(elapsed_minutes)} 分钟且无 run 进度",
                    f"updated={updated_str}，阈值 {int(threshold_minutes)} 分钟",
                )
            )
        return signals

    def _detect_merge_streak(self, specs: dict) -> list:
        """_merge_streak 已达熔断阈值仍滞留（merge-back 反复失败）。"""
        signals = []
        threshold = int(self._cfg_float("merge_breaker_threshold", 2))
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
            signals.append(
                self._make_signal(
                    "merge_streak",
                    name,
                    f"'{name}' merge-back 连续失败 {streak} 次已达熔断阈值仍滞留（{status}）",
                    f"_merge_streak={streak}，指纹={fp}",
                )
            )
        return signals

    def _detect_orphaned_state(self, specs: dict, now: float) -> list:
        """implementing/testing 状态无驱动探测（add-control-plane-silent-failure-guards 4.1）。

        三条件（无活动 run 文件 + 无存活 agent 子进程 + 无待派发）由模块级
        ``spec_is_undriven`` 判定（与 event_bus 恢复出口共用同一口径）；本方法
        在其上叠加「状态停留时长 > admin.orphaned_state_threshold_minutes」
        （缺省 15 分钟，远短于 stuck 的 160 分钟）——状态悬置必须持续超过
        短阈值才判无驱动，避免把刚 reset 的 spec 误报。

        人工冻结（frozen）是有意等待态，与 blocked_stuck 同豁免。

        生命周期阶段（orphaned-state-probe-calibration 1.6 语义澄清）：
          - signal：本方法生成信号即 signal 阶段——description 描述的是检测
            时刻三条件成立 + 状态超短阈值这一**信号阶段**事实；
          - disposition pending / disposition failed / escalated：后续阶段由
            AdminStore 处置记录（kind=disposition 的 status/result 字段）与
            升级告警（kind=escalation）承载，不回写本信号 description——
            阶段差异看记录状态，**不得**声称「同一信号仅一条记录」：冷却
            （_throttled，AdminStore.latest_signal）过期后同信号可再次成条，
            属既有节流语义而非重复告警缺陷（实证 .fenix/logs/fenixd.log:17224
            Signal throttled: orphaned_state … (cooldown 15m)）。
        """
        signals = []
        threshold_minutes = self._cfg_float(
            "orphaned_state_threshold_minutes", DEFAULT_ORPHANED_STATE_THRESHOLD_MINUTES
        )
        for name, entry in specs.items():
            status = entry.get("status")
            if status not in ("implementing", "testing"):
                continue
            # 人工冻结豁免：冻结即「等待人工」的显式表达（与 blocked_stuck 同款）
            if entry.get("frozen"):
                continue
            # 待 re-merge 载体的豁免（2026-09-17 事故，铁律 4 同款「误判以 ctx 声明
            # 为准」）：``_repair_awaiting_remerge=True`` 的 implementing spec 是
            # **有意等待态**——分支已完整交付、仅剩合并，其唯一消费者是 daemon
            # 重启时的 boot recovery（``recover_interrupted`` 的
            # ``_recovery_remerge_pending``，core/state_machine.py:1143-1151），
            # 该通路是**时间点事件**而非「有待派发」：在 daemon 不重启的正常稳态
            # 下，该 spec 必然满足「无活动 run 文件 + 无存活子进程 + 无待派发」
            # 三条件（本就按此设计），与真正的「无驱动」（控制平面某条路径把 spec
            # 留在运行态却没人驱动）语义相反。若不豁免，每次状态写入后
            # orphaned_state_threshold_minutes（缺省 8 分钟）即复发一次告警，且
            # 处置侧对该载体无正确出口（复位 ready 会清空待合并标记、白废已完成的
            # 实现；复位 testing 会把未合并分支的 committed 态当合并态直通验证）、
            # 自动复位 resolve_env_blocked_reset_path 亦因其非 blocked 而不触发，
            # 只能反复空转升级人工。
            # 实证：'evo-merge-back-wip-overlap-gate-575976'（前任 admin 于
            # 2026-09-17T22:59:31Z 置入该载体）在 8 分钟后的 23:07:30Z 即被本巡检
            # 判为「无驱动」唤起 Administrator 空转。
            # 载体自身「不重启即不被消费」的收敛通道（stale_code_selfheal 仅对
            # 陈旧代码触发，已非普适出口）有待后续 SPEC 补，本处只消除误报。
            if entry.get("_repair_awaiting_remerge"):
                self.logger.debug(
                    "admin_monitor",
                    f"跳过 orphaned_state 探测：'{name}' 为待 re-merge 载体"
                    f"（_repair_awaiting_remerge=True，仅剩合并的有意等待态，"
                    f"由 daemon 重启恢复消费）",
                )
                continue
            # WIP 延迟合回等待载体的豁免（evo-add-wip-defer-merge-retry-consumer
            # 2.3，与上方 _repair_awaiting_remerge 同型）：implementing +
            # _wip_gate_deferred=True 是周期消费者的**有意等待态**——唯一消费者
            # 是 daemon 主循环的 merge-only 自动重试（120 秒节拍，远短于本探测
            # 的 15 分钟缺省阈值，「WIP 清了自动合回」是默认路径）。等待期内
            # （未超限：计数 < WIP_DEFER_MAX_ROUNDS 且窗口
            # < WIP_DEFER_WINDOW_MINUTES，与 queue.py 同一常量口径）豁免：若不
            # 豁免，15 分钟后 orphaned_state major 照发召唤 Administrator，与
            # 「admin 仅处理真冲突与超限降级」的目标矛盾，且其处置复位
            # implementing→ready 会与周期消费者的状态守卫相撞。超限降级后
            # 豁免**自动失效**：标志保留、本探测恢复兜底，与
            # mergeback_wip_defer_stuck 降级告警汇合指向人工。
            if entry.get("_wip_gate_deferred"):
                try:
                    _wip_count = int(entry.get("_merge_retry_count", 0) or 0)
                except (TypeError, ValueError):
                    _wip_count = 0
                _wip_first = entry.get("_merge_retry_first_at")
                try:
                    _wip_first_f = float(_wip_first) if _wip_first else now
                except (TypeError, ValueError):
                    _wip_first_f = now
                _wip_over = (
                    (now - _wip_first_f) / 60.0 >= WIP_DEFER_WINDOW_MINUTES
                    or _wip_count >= WIP_DEFER_MAX_ROUNDS
                )
                if not _wip_over:
                    self.logger.debug(
                        "admin_monitor",
                        f"跳过 orphaned_state 探测：'{name}' 为 WIP 延迟合回等待"
                        f"载体（_wip_gate_deferred=True，{_wip_count} 轮，"
                        f"周期消费者自动 merge-only 重试中；超限后本豁免自动失效）",
                    )
                    continue
            updated_str = entry.get("updated") or entry.get("created") or ""
            try:
                updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            elapsed_minutes = (now - updated.timestamp()) / 60
            if elapsed_minutes <= threshold_minutes:
                continue
            # 与 stuck 的交接点（hand-off）：stuck 阈值远高于本信号短阈值，
            # 本信号只覆盖 (orphaned_threshold, stuck_threshold] 的早发现窗口——
            # 超过 stuck 阈值后既有 stuck 检测已覆盖该 spec（repeated 检测表里
            # 它也在），再补发 orphaned_state 只产生双信号/双唤起（实证：
            # 200 分钟无 run 悬置同时命中 stuck 与孤儿两路）。≤ stuck_threshold
            # 时的 orphaned 先于 stuck 触发（4.5 回归场景）。
            stuck_threshold = self._cfg_float("stuck_threshold_minutes", 0)
            if stuck_threshold > 0 and elapsed_minutes > stuck_threshold:
                continue
            # 注入 pm_engine（2026-09-18 修复）：条件 ④「无排队中的派发条目」——
            # 处置直通道 `transition_gate(testing) + verifier 入队` 后条目可在队列
            # 里等并发槽数十分钟，缺此判定则每轮巡检必判「无驱动」并唤起
            # Administrator（本 SPEC 07:55/08:07/08:30 三连误报实证）。pm_engine
            # 为 None（测试替身/独立组件）时不判 ④，行为与修复前一致。
            if not spec_is_undriven(self.project_root, name, entry, pm_engine=self.pm_engine):
                continue
            signals.append(
                self._make_signal(
                    "orphaned_state",
                    name,
                    f"'{name}' 处于 {status} 超过 {int(elapsed_minutes)} 分钟无驱动"
                    "（signal 阶段：无活动 run / 无存活子进程 / 无排队中派发条目 / "
                    "无待派发，待"
                    "Administrator 处置；pending/failed/escalated 阶段看处置记录）",
                    f"updated={updated_str}，阈值 {int(threshold_minutes)} 分钟"
                    f"（stuck 阈值 {int(self.admin_cfg.get('stuck_threshold_minutes', 0))}"
                    " 分钟远高于此，本信号先于 stuck 捕获）",
                )
            )
        return signals

    def _detect_daemon_errors(self, now: float) -> list:
        """fenixd.log：10 分钟窗口内同指纹 ERROR 复现 ≥2 次且最近两次间隔 ≤5 分钟
        → daemon_errors critical signal（daemon-error-escalation D5）。

        无状态每轮巡检重算（读尾部即得，不持久化计数器、daemon 重启安全）；恢复
        靠窗口滑动自然过期（重载成功不写 ERROR，10 分钟后自动归零）。中间被
        INFO/WARNING/其他错误打断不影响同指纹复现计数；单条瞬时错误不升级；
        两条不同错误各 1 次不聚合（指纹不同）。

        alert-noise-governance 治理（3.1/3.2/3.3）：
        - 指纹级重启冷却——daemon 启动后冷却窗内，「已知指纹」（本生命周期
          已升级过，或 admin store 既有 daemon_errors 记录在案——跨重启对账）
          不计满阈值、不产信号不召唤（INFO 留痕冷却决策）；窗后复现或全新指
          纹照常升级。与 _throttled 的关系见常量注释（指纹级补口而非替代）。
        - 同轮孪生/成对指纹合并——同一轮扫描多个指纹同时达阈值时按 fp 聚合
          为一条召唤信号（一次 Administrator run），不再各指纹各召唤一次。
        """
        log_file = self.project_root / ".fenix" / "logs" / "fenixd.log"
        if not log_file.exists():
            return []
        window = DAEMON_ERROR_WINDOW_MINUTES * 60
        max_gap = DAEMON_ERROR_RECURRENCE_MAX_GAP_MINUTES * 60

        by_fp: dict = {}
        for ts, component, message in self._read_tail_error_entries(log_file):
            by_fp.setdefault(_error_fingerprint(component, message), []).append(ts)

        cooldown = DAEMON_ERROR_RESTART_COOLDOWN_MINUTES * 60
        # __new__ 直构（单测）无 _started_at：按「刚启动」处理（冷却窗生效），
        # 与真实 daemon 启动后的首扫行为一致
        in_restart_window = (now - getattr(self, "_started_at", now)) < cooldown

        escalating = []  # [(fp, count, last_str, missing_ts)]
        for fp, stamps in by_fp.items():
            in_window = [t for t in stamps if t is None or (now - window <= t <= now)]
            if len(in_window) < DAEMON_ERROR_THRESHOLD:
                continue
            ts_ok = sorted(t for t in in_window if t is not None)
            if len(ts_ok) >= 2 and (ts_ok[-1] - ts_ok[-2]) > max_gap:
                continue
            # 已知指纹对账仅服务冷却窗分支（known 只被 known and
            # in_restart_window 消费）——冷却窗关闭后（长驻 daemon 的常态）
            # 不再为每个达阈指纹做全 store 扫描（code-review item e681493f4102）。
            if not in_restart_window:
                known, source = False, ""
            else:
                known, source = self._daemon_fp_known(fp)
            if known and in_restart_window:
                # 冷却命中（3.1）：重启后首扫窗口内的已知指纹不计满、不召唤，
                # INFO 留痕冷却决策；窗后复现照常升级（3.3，冷却仅约束首扫窗口）
                self.logger.info(
                    "admin_monitor",
                    f"daemon_errors 指纹冷却：指纹 {fp[:8]} 为已知指纹"
                    f"（{source}），处于重启后冷却窗（"
                    f"{DAEMON_ERROR_RESTART_COOLDOWN_MINUTES} 分钟）内，"
                    f"不升级不召唤（alert-noise-governance 3.1）",
                )
                continue
            count = len(in_window)
            last_ts = ts_ok[-1] if ts_ok else None
            last_str = (
                datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat()
                if last_ts
                else "无可用时间戳"
            )
            missing_ts = sum(1 for t in in_window if t is None)
            escalating.append((fp, count, last_str, missing_ts))

        if not escalating:
            return []
        # 记录指纹上次唤起时间戳（3.1「生命周期内用内存时间戳」）
        for fp, *_ in escalating:
            self._daemon_fp_escalated_at[fp] = now
        if len(escalating) == 1:
            return [self._make_daemon_error_signal(*escalating[0])]
        # 同轮孪生/成对指纹合并（3.2）：一条召唤信号、一次 Administrator run
        return [self._make_daemon_error_signal_merged(escalating)]

    def _daemon_fp_known(self, fp: str) -> tuple:
        """指纹是否「已知」（alert-noise-governance 3.1）。

        已知 = 本生命周期内已产生过升级信号（内存时间戳在案），或 admin
        store 存在携带该指纹的 daemon_errors 记录（跨重启对账——store 记录
        无结构化指纹字段，_fp 仅内存传递不落库，故以本模块产出 description
        的稳定文案「指纹 <fp[:8]>」前缀对账）。返回 (known, source)。

        store 读取失败按未知指纹处理（fail-open：冷却缺失的最坏后果是重启
        后多召唤一次，不掩盖真实新故障）。
        """
        if fp in getattr(self, "_daemon_fp_escalated_at", {}):
            return True, "本生命周期已升级过（内存时间戳在案）"
        prefix = fp[:8]
        try:
            for rec in self.store.read_all():
                if rec.get("signal_type") != "daemon_errors":
                    continue
                if f"指纹 {prefix}" in str(rec.get("description") or ""):
                    return True, "store 既有 daemon_errors 记录在案（跨重启识别）"
        except Exception:
            pass
        return False, ""

    def _make_daemon_error_signal(self, fp: str, count, last_str, missing_ts) -> dict:
        """单指纹 daemon_errors 信号（文案与治理前保持一致，语义回归）。"""
        sig = self._make_signal(
            "daemon_errors",
            None,
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
        return sig

    def _make_daemon_error_signal_merged(self, escalating: list) -> dict:
        """同轮多指纹合并信号（alert-noise-governance 3.2）。

        description 对每个指纹保留「指纹 <fp[:8]>」文案——跨重启已知指纹对账
        （_daemon_fp_known 对 store 记录的 description 前缀匹配）依赖该子串，
        合并形态下逐指纹仍可命中；evidence 另载各指纹复现明细。
        """
        fp_summary = "、".join(
            f"指纹 {fp[:8]}（复现 {count} 次）" for fp, count, _, _ in escalating
        )
        sig = self._make_signal(
            "daemon_errors",
            None,
            f"fenixd 日志同轮 {len(escalating)} 项错误同时达升级阈值（{fp_summary}），"
            f"已合并为一条召唤信号、一次 Administrator run（alert-noise-governance"
            f" 3.2），建议检查根因并重启 daemon",
            "；".join(
                f"指纹 {fp[:8]} 复现 {count} 次（最近一次 {last_str}）"
                for fp, count, last_str, _ in escalating
            )
            + f"；升级条件：同指纹 ≥{DAEMON_ERROR_THRESHOLD} 次且最近两次间隔"
            f" ≤{DAEMON_ERROR_RECURRENCE_MAX_GAP_MINUTES} 分钟",
        )
        # 合并信号的 status_hash 判据 = 全部指纹的稳定拼接（同集合同 hash，
        # 沉淀合并语义与单指纹一致）
        sig["_fp"] = "|".join(fp for fp, *_ in escalating)
        return sig

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
                ts_epoch = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
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
            raw = "daemon:{}\x00{}".format(signal.get("signal_type") or "", fp)
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

    def _fixture_invocation_suppressed(self, signal: dict) -> bool:
        """fixture 标记项目的自动召唤抑制（alert-noise-governance 5.1）。

        监控项目带 fixture:true 标记时，其告警（含 spec 级与 daemon 级全局
        巡检类）为验证噪音——自动召唤 Administrator 只会烧出空转 admin run
        （2026-09-22 实证：夹具噪音点燃 3 笔 admin-global 召唤）。命中即记
        INFO（含错误指纹与抑制原因）并返回 True，由调用点跳过自动召唤。

        落点约束：本判定置于各自动检测路径调用 _invoke_administrator 之前
        （_detect_family_explosion / _handle_signal / _retry_due_dispatch_failures
        / _recover_orphaned_dispositions 四处），MUST NOT 放进
        _invoke_administrator 本体——人工显式触发（run_administrator）与自动
        检测共用该入口，放本体必误伤人工通道（5.1）。抑制只阻断召唤动作，
        MUST NOT 修改/删除告警记录本身（5.2，看板仍可见）。
        """
        # getattr 兜底：半初始化实例（如测试用 __new__ 绕过 __init__）无该
        # 属性时按非 fixture 处理（fail-open，与 _is_fixture_project 同语义）。
        # 判定结果经实例级 TTL 备忘复用（code-review item 9427d41c85ef）：
        # _is_fixture_project 每次 = Registry() 构造 + discover()（YAML 读 +
        # 目录扫描），且对非夹具项目也恒执行并返回 False——巡检周期内每条
        # 信号都重付一次文件 I/O，_retry_due_dispatch_failures 对被抑制记录
        # 不增 retry_count，同一 pending 记录会无限期逐周期重触。夹具标记
        # 实践中静态，TTL 300s 足以覆盖巡检粒度且配置改动最多延迟一个 TTL 生效。
        root = getattr(self, "project_root", None)
        memo = getattr(self, "_fixture_project_memo", None)
        if memo is None:
            memo = self._fixture_project_memo = {}
        key = str(Path(root).resolve()) if root else ""
        hit = memo.get(key)
        now_mono = time.monotonic()
        if hit is not None and now_mono - hit[0] < _FIXTURE_PROJECT_MEMO_TTL:
            is_fixture = hit[1]
        else:
            is_fixture = _is_fixture_project(root)
            memo[key] = (now_mono, is_fixture)
        if not is_fixture:
            return False
        fp = signal.get("_fp")
        self.logger.info(
            "admin_monitor",
            f"fixture 项目抑制自动召唤: signal={signal.get('signal_type')} "
            f"spec={signal.get('spec') or 'daemon'}"
            + (f" 指纹={str(fp)[:8]}" if fp else "")
            + "（项目带 fixture:true 标记，告警为验证噪音；"
            f"人工显式触发不受限 — alert-noise-governance 5.1）",
        )
        return True

    def _handle_signal(self, signal: dict):
        """处理单条信号：状态沉淀记录 + 节流判定 + 唤起 Administrator。"""
        spec = signal.get("spec")
        signal_type = signal.get("signal_type")
        status_hash = self._signal_status_hash(signal)

        # 节流：冷却窗口内同 spec 同类信号已唤起过 / 已有未处理升级告警 → 跳过唤起
        if self._throttled(spec, signal_type):
            record, is_new = self.store.merge_signal(
                self._signal_record(signal, escalated=False), status_hash
            )
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

        # fixture 项目自动召唤抑制（alert-noise-governance 5.1）：置于唤起
        # 决策（escalated=True 锚点写入）之前；信号仍按沉淀语义入库
        # （escalated=False，不虚报已唤起），告警记录原样可见（5.2），仅召唤
        # 动作被阻断。
        if self._fixture_invocation_suppressed(signal):
            self.store.merge_signal(
                self._signal_record(signal, escalated=False), status_hash
            )
            return

        signal_rec, _ = self.store.merge_signal(
            self._signal_record(signal, escalated=True), status_hash
        )
        # fix-recovery-path-blockers D2b：唤起前与在飞 admin run 互斥——D1 生效后
        # 处置中的 spec 会在冷却窗（缺省 60 分钟）过期后重新成条，无本守卫即产生
        # 与在飞处置**并行**的第二个 Administrator run（写同一批 STATE/
        # test_scenarios.json）。守卫按 spec 单键聚合、覆盖**任意** signal_type
        # （admin 处置的 signal_type 不只有 orphaned_state）。为真 → 跳过
        # 本次唤起（信号仍按既有沉淀/节流语义落 store，不丢痕）并记 WARNING。
        if spec and self._has_active_admin_run_for_spec(spec):
            self.logger.warning(
                "admin_monitor",
                f"已有在飞处置，跳过重复唤起 '{spec}'（signal {signal_type}）"
                f"— fix-recovery-path-blockers D2b",
                {"signal": signal},
            )
            # code-review item 64cd854cebbb：上行 merge_signal 已落 escalated=True
            # 的冷却锚点，本路径实际未派发——不补痕则 store 永久留存「已唤起」
            # 假象，审计/看板失真。比照信号死法冷却路径补写说明性处置记录；
            # result="skipped" 不命中任何 result 消费分支，DISPOSITION 不参与
            # unhandled_for 节流——不阻断在飞处置完成后的自然重评。
            try:
                self.store.append(
                    {
                        "kind": DISPOSITION,
                        "signal_type": signal_type,
                        "spec": spec,
                        "severity": signal.get("severity"),
                        "description": signal.get("description"),
                        "action_taken": (
                            "已有在飞 admin run，跳过重复唤起"
                            "（fix-recovery-path-blockers D2b 互斥守卫）——"
                            "实际未派发，在飞处置完成后由检测循环自然重评"
                        ),
                        "result": "skipped",
                    }
                )
            except Exception as e:
                self.logger.error(
                    "admin_monitor",
                    f"Failed to persist mutex-skip disposition for "
                    f"'{spec or 'daemon'}': {e}",
                )
            return
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
            self.store.append(
                attach_trigger(
                    {
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
                    }
                )
            )
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
            if (
                rec.get("kind") != SIGNAL
                or rec.get("spec") != spec
                or rec.get("signal_type") not in STALLED_ESCALATION_SIGNAL_TYPES
            ):
                continue
            created = rec.get("created")
            if created and (earliest is None or created < earliest):
                earliest = created
        return earliest

    # ── 派发失败重试巡检（admin-dispatch-failure-escalation D2） ──

    def _retry_due_dispatch_failures(self, now: float) -> int:
        """派发失败升级记录到期重试巡检（admin-dispatch-failure-escalation D2）。

        扫描 kind=escalation ∧ next_retry_at ≤ now ∧ retry_count < 1 ∧
        未 handled 的派发失败记录 → 重建原信号 → 直接调 _invoke_administrator
        重试派发一次（带 _dispatch_retry_id 标记）。

        MUST NOT 经 _handle_signal：节流（latest_signal/unhandled_for，
        admin_monitor.py:890-896）命中刚写的升级记录把重试吞掉；重试直接
        走派发链本身，等价于把「冷却后重试一次原信号」落在派发时刻。frozen
        spec 跳过（同 _handle_signal 冻结语义，人工等待态不自动重试）。
        manual 派发记录不带 next_retry_at，天然不在扫描范围。

        重试失败由 _invoke_administrator 内部 bump 既有记录 retry_count
        （上限 DISPATCH_RETRY_MAX，不追加新记录）；重试成功由
        _invoke_administrator 内部闭环该 spec 的派发失败记录。

        挂 run_once 巡检（_force_escalate_stalled 之后、_run_alert_lifecycle
        之前），不新增线程/定时器。返回本次重试派发的记录数（供审计）。
        """
        retried = 0
        for rec in self.store.read_all():
            if rec.get("kind") != ESCALATION or rec.get("handled"):
                continue
            try:
                retry_count = int(rec.get("retry_count") or 0)
            except (TypeError, ValueError):
                retry_count = 0
            if retry_count >= DISPATCH_RETRY_MAX:
                continue
            next_retry_at = rec.get("next_retry_at")
            if not next_retry_at:
                continue
            try:
                due = datetime.fromisoformat(str(next_retry_at).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if due.timestamp() > now:
                continue
            # frozen spec 跳过（重试尊重人工冻结语义）
            spec = rec.get("spec")
            if spec:
                try:
                    entry = self.state_machine.read_one(spec) or {}
                except Exception:
                    entry = {}
                if entry.get("frozen"):
                    self.logger.info(
                        "admin_monitor",
                        f"Skipping dispatch retry for frozen SPEC '{spec}'",
                    )
                    continue
            signal = self._rebuild_dispatch_signal(rec)
            if signal is None:
                continue
            signal["_dispatch_retry_id"] = rec.get("id")
            # fixture 项目抑制（alert-noise-governance 5.1）：到期重派同属
            # 自动召唤，跳过（升级记录保留不删除，5.2）；不 bump retry_count
            # ——抑制非派发失败，下轮巡检到期仍会重评（窗内维持阻断）。
            if self._fixture_invocation_suppressed(signal):
                continue
            self.logger.warning(
                "admin_monitor",
                f"Dispatch failure retry due: re-invoking Administrator for "
                f"original signal {signal.get('signal_type')} on "
                f"'{spec or 'daemon'}' (escalation {rec.get('id')})",
            )
            self._invoke_administrator(signal, rec)
            retried += 1
        return retried

    # ── 孤儿处置重派（admin-disposition-reschedule） ─────────────

    def _has_active_admin_run_for(self, spec, signal_type: str, exclude_run_id: Optional[str] = None) -> bool:
        """同 (spec, signal_type) 是否已有在飞/待派发的 admin run。

        判据刻意对齐 _recover_orphaned_dispositions 自身的 by_run 归并口径
        （同款 `status == "pending"`）：一个 run 只有在「存在 pending 记录
        且无任何非 pending 兄弟记录」时才视为在飞——已终结 run（含被
        superseded/interrupted/escalated 终结的原 pending 记录仍滞留 store
        的形态）不算在飞。据此为「已有在飞 run 的信号」去重，避免双重派发。

        exclude_run_id：重派判定时排除「正被孤儿处理的中断 run」自身——其
        pending 记录是本判定的考察对象，不得把自己误判为「已有在飞 run」。
        """
        by_run: dict = {}
        for rec in self.store.read_all():
            if rec.get("kind") != DISPOSITION:
                continue
            if rec.get("signal_type") != signal_type:
                continue
            if rec.get("spec") != spec:
                continue
            rid = rec.get("admin_run_id")
            if not rid:
                continue
            if exclude_run_id is not None and rid == exclude_run_id:
                continue
            status = rec.get("status") or rec.get("result")
            info = by_run.setdefault(rid, {"final": False, "has_pending": False})
            if status == "pending":
                info["has_pending"] = True
            else:
                info["final"] = True
        return any(info["has_pending"] and not info["final"] for info in by_run.values())

    def _has_active_admin_run_for_spec(self, spec) -> bool:
        """该 spec 是否存在在飞/待派发的 Administrator run（任意 signal_type）。

        fix-recovery-path-blockers D2：守卫口径按 spec 单键聚合、覆盖**任意**
        signal_type（admin 处置的 signal_type 可能是 verify_env_blocked /
        manual-intervention / stuck，不只有 orphaned_state）。委托模块级
        ``_spec_has_active_admin_run``（单一归并实现，勿二次漂移）；判定异常
        fail-open 返回 False 并记 WARNING（守卫故障不阻断恢复路径）。
        """
        return _spec_has_active_admin_run(self.store, spec, logger=self.logger)

    def _reschedule_count_for(self, spec, signal_type: str) -> int:
        """读同 (spec, signal_type) 的 DISPOSITION 记录 reschedule_count 最大值（缺省 0）。

        计数按信号族聚合（跨独立信号事件可能多计；多计方向为更早升级，
        安全侧）。字段缺失/非法值按 0 计。
        """
        best = 0
        for rec in self.store.read_all():
            if rec.get("kind") != DISPOSITION:
                continue
            if rec.get("signal_type") != signal_type:
                continue
            if rec.get("spec") != spec:
                continue
            try:
                val = int(rec.get("reschedule_count") or 0)
            except (TypeError, ValueError):
                val = 0
            if val > best:
                best = val
        return best

    # ── 兜底升级（fix-admin-self-heal） ──────────────────────────

    def _recover_orphaned_dispositions(self):
        """检测「admin 被唤起但未完成处置」（pending 无最终结果）→ 升级人工。

        admin 是 daemon 子进程，若其在处置中被 kill（daemon 重启/崩溃），不会留下
        最终 disposition、也不会走升级分支。此方法每次巡检兜底：pending 记录超时
        无最终结果 → 转为人工升级告警，保证「admin 死了也有告警」。

        ★ 误报边界（2026-09-18 取证）：本判据「created 超过 grace 且无最终记录」
        推定 run 已死，但 admin 处置本身的耗时不受任何时限约束——`run_administrator`
        以 `agents.max_turns`（缺省 300，实测可跑 152 轮 / 63 分钟）驱动，稳定超过
        grace（`admin.escalation_cooldown_minutes`，缺省 60 分钟——config 默认，
        core/config.py get_admin_config）。于是**任何**跑满 60 分钟的 admin
        处置，无论存活与否都会在此被升级，措辞却断言「疑似 daemon
        重启/崩溃连带杀死 admin」——与本轮三次误报（09-17T17:55、09-18T00:19 两例
        + 09-18T08:19 一例）的实况（亚秒级认知负荷，从未真被杀）完全相反。
        真正的判死证据是可用而未用的：daemon 在被动关闭时**同步**向 `.fenix/runs/
        <rid>.jsonl` 追加 `{"type":"interrupted"}`（见 `_run_has_interrupted_marker`），
        run 正常收工时流文件末行必为终态事件（`core/agent_runner/run_files.py`
        `_file_has_terminal_event` 同口径）。故本方法必须先查 run 文件（daemon
        侧转写，不依赖 admin 子进程存活）——只要 daemon 还活着，被唤醒的 admin
        就仍在 daemon 进程表里受自己 300 轮上限约束，run 文件不会撒谎。
        调用 `has_live_attempt`（其 pgrep 只认 `worktrees/{impl,verify}-` 前缀）
        在此处**无效**：admin run 无 worktree，恒返回 False。

        本次仅加「死亡证据门」收紧误报路径，不改写/撤回任何已落记录——判定态
        不可逆，撤回属于另一条决策（存量记录需人工或后续 SPEC 处置）。
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

            # 死亡证据门（2026-09-18 误报取证修复，与 fix-graceful-shutdown-agents
            # 的 interrupted 判定同源扩展）：admin 处置耗时不受 grace 约束，故
            # 「超 grace 无最终记录」**不足以**推断 run 已死。仅当 run 文件同时
            # 满足 ① 存在 且 ② 末行是终态事件 时才确认死亡；文件缺失/无终态
            # （仍在跑）/读失败 → 本方法不是死亡判定器，跳过，不落告警。
            # 保守方向：宁可漏报（用户可见 admin run 仍在写流），不可拿「超时」
            # 冒充「被杀」——误报的措辞会误导人工去查根本不存在的 daemon 崩溃。
            if not self._run_file_has_terminal_state(rid):
                continue

            # fix-graceful-shutdown-agents：先验 run 文件是否含 interrupted 标记（daemon
            # 优雅退出所致已知中断）。含标记 → 判定已知中断：终结 pending disposition 且
            # 不产生人工升级告警；无标记/文件缺失 → 维持现有"疑似 daemon 崩溃"升级兜底
            # （保守方向：宁可多告警不漏告警，files 被 prune 删除也按无标记处理）。
            #
            # admin-disposition-reschedule：已知中断分支前置回溯底层未处理信号——
            # 命中（kind=signal ∧ escalated ∧ 非 handled ∧ (spec, signal_type) 严格相等）
            # 且重派未超限时，重新入队 admin run 而非静默终结；超限则升级人工。
            # 信号未找到 / 信号重建失败 / 已有在飞 run → 回落原「终结 interrupted」逻辑。
            if self._run_has_interrupted_marker(rid):
                sig_rec = self.store.unhandled_signal_for(spec, sig_type)
                if sig_rec is not None:
                    next_count = self._reschedule_count_for(spec, sig_type) + 1
                    if next_count > self.reschedule_max:
                        # 重派超限（design：第 1、2 次中断各重派一次，第 3 次即升级）：
                        # 不再自动重派，升级人工（kind=escalation, severity=critical，
                        # description 注明中断/重派次数），并为该 run 追加非 pending
                        # 终结记录，防同一孤儿每轮巡检重复升级。
                        self.store.append(
                            attach_trigger(
                                {
                                    "kind": ESCALATION,
                                    "signal_type": sig_type,
                                    "spec": spec,
                                    "severity": "critical",
                                    "description": (
                                        f"Administrator 处置反复中断（run {rid}）：底层信号 "
                                        f"{sig_type} 已累计重派 {next_count - 1} 次仍未处理完成，"
                                        f"达到上限 {self.reschedule_max}，停止自动重派，需人工介入"
                                    ),
                                    "evidence": (
                                        f"run {rid} 转录含 interrupted 标记；"
                                        f"reschedule_count={next_count - 1} ≥ {self.reschedule_max}"
                                    ),
                                    "action_taken": "AdminMonitor 孤儿检测：中断-重派超限转人工升级",
                                    "admin_run_id": rid,
                                    "recommended_action": (
                                        "人工检查底层信号未处理原因：处置连续中断说明 daemon "
                                        "停机循环或信号处置本身存在阻塞，需人工介入处置"
                                    ),
                                }
                            )
                        )
                        self.store.append(
                            {
                                "kind": DISPOSITION,
                                "status": "escalated",
                                "signal_type": sig_type,
                                "spec": spec,
                                "admin_run_id": rid,
                                "result": "escalated",
                                "actions_taken": (
                                    "AdminMonitor 孤儿检测：中断-重派超限升级人工并终结该 run"
                                ),
                                "description": (
                                    f"Administrator 处置反复中断已升级人工（run {rid}），pending 终结"
                                ),
                            }
                        )
                        self.logger.warning(
                            "admin_monitor",
                            f"Orphaned admin disposition escalated to human after "
                            f"reschedule limit: {rid} (reschedule_count={next_count - 1})",
                        )
                        continue
                    # 未超限：回溯底层信号并重派（不经 _handle_signal——否则
                    # _throttled 冷却会把重派吞掉，同 _retry_due_dispatch_failures
                    # 既有先例）。signal 重建失败 / 已有在飞 run → 回落原终结逻辑。
                    signal = self._rebuild_dispatch_signal(sig_rec)
                    if signal is not None and not self._has_active_admin_run_for(
                        spec, sig_type, exclude_run_id=rid
                    ):
                        # fixture 项目抑制（alert-noise-governance 5.1）：置于
                        # superseded 记录写入与重派之前——不写「已重派」审计、
                        # 不重入队 admin run；原 pending 记录保持待下一轮重评
                        # （人工显式触发不受限）。
                        if self._fixture_invocation_suppressed(signal):
                            continue
                        # 审计留痕：原 pending disposition 追加 status=superseded 记录
                        # （同 admin_run_id），携带 reschedule_count 新值；非 pending
                        # 记录即令该 run 被判 final，孤儿循环终止。MUST NOT 额外写
                        # status=dispatched 的新 disposition——新 run 的 pending 记录
                        # 由 run_administrator 自身落盘（core/agent_runner/
                        # maintenance_runs.py:182），额外写同 admin_run_id 的非 pending
                        # 记录会让 by_run 归并把新 run 判为已终结，后续中断永不检测。
                        self.store.append(
                            {
                                "kind": DISPOSITION,
                                "status": "superseded",
                                "signal_type": sig_type,
                                "spec": spec,
                                "admin_run_id": rid,
                                "result": "superseded",
                                "reschedule_count": next_count,
                                "actions_taken": (
                                    "superseded by rescheduled disposition "
                                    f"(signal {sig_rec.get('id')} still unhandled)"
                                ),
                                "description": (
                                    f"Administrator 处置因 daemon 关闭被中断（run {rid}），"
                                    f"底层信号 {sig_type} 仍未处理，自动重新入队 admin run"
                                    f"（第 {next_count} 次重派）"
                                ),
                            }
                        )
                        self.logger.warning(
                            "admin_monitor",
                            f"Rescheduling orphaned admin disposition for signal {sig_type} "
                            f"on '{spec or 'daemon'}' (superseded run {rid}, "
                            f"reschedule_count={next_count})",
                        )
                        self._invoke_administrator(signal, sig_rec)
                        continue
                # 未找到信号记录 / 信号重建失败 / 已有在飞 run：维持现「终结 interrupted」
                # 行为（回归兼容，task 2.6）
                self.store.append(
                    {
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
                    }
                )
                self.logger.info(
                    "admin_monitor",
                    f"Orphaned admin disposition marked interrupted (known shutdown): {rid}",
                )
                continue

            self.store.append(
                attach_trigger(
                    {
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
                    }
                )
            )
            # 升级即终结：补非 pending 记录，避免 escalation 被 handled 后 unhandled_for
            # 节流失效、同一孤儿在下轮巡检再次升级造成循环告警
            self.store.append(
                {
                    "kind": DISPOSITION,
                    "status": "escalated",
                    "signal_type": sig_type,
                    "spec": spec,
                    "admin_run_id": rid,
                    "result": "escalated",
                    "actions_taken": "AdminMonitor 孤儿检测：pending 超时升级人工并终结该 run",
                    "description": f"Administrator 处置中断已升级人工（run {rid}），pending 终结",
                }
            )
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

        路径解析复用 `_admin_run_file`（含 archive 回退）——run 被「runs 保留」规则
        移入 `archive/` 后，只看顶层会漏掉标记，使已知中断被误判为疑似崩溃。

        Args:
            admin_run_id: admin disposition 的 admin_run_id（形如 admin-<spec>-<ts>）。
        """
        run_file = self._admin_run_file(admin_run_id)
        if run_file is None:
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

    def _admin_run_file(self, admin_run_id: str):
        """定位 admin run 产物文件：先顶层 `.fenix/runs/`，再 `archive/`。

        run 收工后被「runs 保留」清理移入 `archive/`（见 fenixd 主循环
        runs_retention_check），届时顶层已不存在——只 glob 顶层会让所有依赖
        run 文件的死亡判定突然失明（文件缺失）。两处均无 → None。

        Args:
            admin_run_id: admin disposition 的 admin_run_id。

        Returns:
            Path（存在）或 None。
        """
        runs_dir = self.project_root / ".fenix" / "runs"
        for candidate in (runs_dir / f"{admin_run_id}.jsonl",
                          runs_dir / "archive" / f"{admin_run_id}.jsonl"):
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None

    def _run_file_has_terminal_state(self, admin_run_id: str) -> bool:
        """run 产物文件存在且末行为终态事件 → 确认该 admin run 已死。

        终态事件类型取自 `core/agent_runner/run_files.py:RUN_TERMINAL_EVENT_TYPES`
        真源（result/interrupted/error/cancelled 等）。判定用**末行**而非全文：
        文件一旦含终态即已终结，但只看末行同时排除「早先轮次写过终态又被后续
        事件续写」的不可能形态（终态行是收口时追加的最后一行）；读失败/无末行
        → False（非死亡证据，保守不升级）。

        Args:
            admin_run_id: admin disposition 的 admin_run_id。
        """
        run_file = self._admin_run_file(admin_run_id)
        if run_file is None:
            return False
        try:
            from core.agent_runner.liveness import _file_has_terminal_event
        except Exception:
            return False
        try:
            return bool(_file_has_terminal_event(run_file))
        except OSError:
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
        self.store.append(
            {
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
            }
        )
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
            # admin-dispatch-failure-escalation D2：重试派发遇 agent_runner 不
            # 可用 → bump 既有记录 retry_count 后结束，不重复落盘；非重试时
            # 保持原逻辑落「Administrator 不可用」升级（不带 next_retry_at，
            # 不参与自动重试）。
            if signal.get("_dispatch_retry_id"):
                self.store.bump_dispatch_retry(signal["_dispatch_retry_id"], DISPATCH_RETRY_MAX)
                self.logger.warning(
                    "admin_monitor",
                    f"Dispatch retry aborted (no agent_runner): "
                    f"bumped retry_count for {signal.get('_dispatch_retry_id')}",
                )
                return
            self.logger.warning(
                "admin_monitor",
                "No agent_runner available, cannot invoke Administrator; escalating to human",
            )
            self.store.append(
                attach_trigger(
                    {
                        "kind": ESCALATION,
                        "signal_type": signal.get("signal_type"),
                        "spec": signal.get("spec"),
                        "severity": signal.get("severity"),
                        "description": signal.get("description"),
                        "evidence": signal.get("evidence"),
                        "action_taken": "Administrator 不可用（未配置 agent_runner），未能自动处置",
                        "recommended_action": signal.get("recommended_action"),
                    }
                )
            )
            return

        # evo-sigterm-source-tracking-cooldown：信号死法冷却期内跳过 admin 处置
        # 唤起（该 spec 连续信号死法已达阈值——反复唤起只会再次撞运气烧预算）。
        # spec 保持原状，冷却到期由恢复定时器 / 检测循环自然恢复。
        try:
            _sig_spec = signal.get("spec")
            _sig_cooled = (
                bool(_sig_spec)
                and callable(getattr(self.agent_runner, "is_signal_kill_cooldown", None))
                and self.agent_runner.is_signal_kill_cooldown(_sig_spec) is True
            )
        except Exception:
            _sig_cooled = False
        if _sig_cooled:
            self.logger.debug(
                "admin_monitor",
                f"信号死法冷却中，跳过 Administrator 唤起 '{_sig_spec}'"
                f"（evo-sigterm-source-tracking-cooldown）",
            )
            # code-review item f954cc8875：自动巡检路径唤起前 _handle_signal 已落
            # escalated=True 的 signal 记录（冷却锚点），本路径实际未派发——不补
            # 痕则 store 永久留存「已唤起」假象，审计/看板失真。对齐 fixture 抑制
            # 路径 escalated=False 的「不虚报已唤起」约定；merge_signal 对
            # escalated 单调升级（False→True 绝不回退）无法回写降级，故补写
            # 说明性处置记录。result="skipped" 不命中任何 result 消费分支，且
            # DISPOSITION 不参与 unhandled_for 节流——不阻断冷却到期后的自然恢复。
            # 人工通道（signal_rec=None）无该虚报锚点，不补痕。
            if signal_rec is not None:
                try:
                    self.store.append(
                        {
                            "kind": DISPOSITION,
                            "signal_type": signal.get("signal_type"),
                            "spec": signal.get("spec"),
                            "severity": signal.get("severity"),
                            "description": signal.get("description"),
                            "action_taken": (
                                "信号死法冷却中，跳过 Administrator 唤起"
                                "（evo-sigterm-source-tracking-cooldown）——"
                                "实际未派发，冷却到期由恢复定时器/检测循环自然恢复"
                            ),
                            "result": "skipped",
                        }
                    )
                except Exception as e:
                    self.logger.error(
                        "admin_monitor",
                        f"Failed to persist cooldown-skip disposition for "
                        f"'{signal.get('spec') or 'daemon'}': {e}",
                    )
            return

        try:
            disp = self.agent_runner.run_administrator(signal)
        except Exception as e:
            self.logger.error(
                "admin_monitor",
                f"Administrator invocation failed: {e}",
                {"signal": signal},
            )
            # admin-dispatch-failure-escalation D1/D2：按异常类型分流升级
            self._escalate_dispatch_failure(signal, signal_rec, e)
            return

        # admin-dispatch-failure-escalation D2：dispatch 成功（run_administrator
        # 正常返回）→ 关闭该 spec 未处理的派发失败升级记录；闭环发生在
        # dispatch 时刻，不扩 alert_lifecycle._SIGNAL_CONDITIONS。
        self._close_dispatch_failures_on_success(signal)

        # 处置记录（任何情况下都留痕）；落盘失败不能丢 final 判定（否则该 run
        # 的 pending 会变孤儿触发人工升级），记日志后继续
        # fix-admin-disposition-empty-shell：失败记录自解释——error 携带 CLI 失败
        # 原因；failed 时 recommended_action 回退到信号侧（disp 空串不再覆盖信号值）。
        try:
            self.store.append(
                {
                    "kind": DISPOSITION,
                    "signal_type": signal.get("signal_type"),
                    "spec": signal.get("spec") or disp.spec,
                    "severity": signal.get("severity"),
                    "description": disp.problem or signal.get("description"),
                    "action_taken": disp.actions_taken,
                    "result": disp.result,
                    "recommended_action": (
                        (disp.recommended_action or signal.get("recommended_action") or "")
                        if disp.result == "failed"
                        else disp.recommended_action
                    ),
                    "summary": disp.summary,
                    "admin_run_id": disp.run_id,
                    "escalate": bool(disp.escalate),
                    "error": disp.error or "",
                    # orphaned-state-probe-calibration 1.5：非零退出的可定位
                    # 失败证据（原始 stderr 摘录/退出码/provider·model/带时间戳
                    # 事件时间线），独立字段随处置记录留痕；无证据时省略
                    # （类型守卫防 MagicMock 替身注入非 dict 值）。
                    "failure_evidence": (
                        disp.failure_evidence
                        if isinstance(getattr(disp, "failure_evidence", None), dict)
                        and disp.failure_evidence
                        else None
                    ),
                    # add-human-adjudication-choices 4.2：结构化裁决字段
                    # （choice_id 非空时框架按注册表 action 执行；空值写 None
                    # 保持记录形状稳定，前端按无裁决处理）
                    "choice_id": getattr(disp, "choice_id", "") or None,
                    "suggested_choice": getattr(disp, "suggested_choice", "") or None,
                }
            )
        except Exception as e:
            self.logger.error(
                "admin_monitor",
                f"Failed to persist administrator disposition for run {disp.run_id}: {e}",
            )

        # family_explosion 处置：Administrator「放行一次」→ 设置父 SPEC 豁免位
        # （fix-family-convergence-governor / design D4）。结构字段优先级最高；
        # 文本动作（放行 / _family_waiver / waive）兜底，兼容自由文本处置。
        self._apply_family_waiver(signal, disp)

        # infra 回拨处置（evo-infra-failure-budget-exempt R3）：Administrator
        # 文本显式声明「回拨 N 轮」→ 从 _verify_fail_rounds 减回误计入的
        # infra 轮次并解冻（幂等，审计留痕 admin_store DISPOSITION）。
        self._apply_infra_reclassification(signal, disp)

        # add-human-adjudication-choices 4.2：处置结论表达为结构化 choice_id
        # 时，走与人工 alert-resolve 相同的动作映射执行路径（同一动作映射、
        # 同一留痕格式），自动处置与人工处置收敛为同一裁决空间。
        self._apply_choice_execution(signal, disp)

        # env 阻塞 / blocked_stuck 处置收尾复位（add-blocked-reverify-lane D2 +
        # frozen-scenario-schema-migration D3）：result 为 resolved/
        # partially-resolved 且信号属复位集合（env 族 + blocked_stuck；人工唤起
        # 通道经 underlying_signal_type 透传底层类型感知，见
        # disposition_signal_hits_auto_reset）时，框架机械判定复位路径——实现
        # 分支已合并 → transition_gate(testing) 直通道重验（跳过全量重实现）；
        # 否则 → 既有 transition(ready)。两条路径均保留阻塞轮次（不清零，
        # 生命周期累计语义），仅清 error。
        # escalated 表示 admin 升级人工，不触发自动复位（人工处置是唯一出路）。
        if disp.result in ("resolved", "partially-resolved"):
            if disposition_signal_hits_auto_reset(signal):
                self._reset_env_blocked_after_disposition(signal, disp)
            elif signal.get("signal_type") == "orphaned_state":
                # 孤儿状态复位（orphaned-state-signal R3）：独立复位路径
                # （非 env 阻塞族）——testing→verifier 重验入队；implementing
                # →ready 重实现。resolve_env_blocked_reset_path 入口守卫要求
                # blocked 状态，孤儿 spec 处于 implementing/testing 不适用。
                self._reset_orphaned_after_disposition(signal)

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
            self.store.append(
                attach_trigger(
                    {
                        "kind": ESCALATION,
                        "signal_type": signal.get("signal_type"),
                        "spec": signal.get("spec") or disp.spec,
                        "severity": signal.get("severity"),
                        "description": signal.get("description"),
                        "evidence": signal.get("evidence"),
                        "action_taken": disp.actions_taken,
                        "recommended_action": disp.recommended_action
                        or signal.get("recommended_action"),
                        "admin_run_id": disp.run_id,
                    }
                )
            )
            self.logger.warning(
                "admin_monitor",
                f"Administrator escalated to human: {signal.get('signal_type')} "
                f"for '{signal.get('spec') or 'daemon'}'",
            )

    # ── admin-dispatch-failure-escalation D1/D2 ──────────────────

    def _escalate_dispatch_failure(self, signal: dict, signal_rec: dict, exc: Exception) -> None:
        """Administrator 派发失败升级分流（admin-dispatch-failure-escalation D1）。

        按异常类型分流：
        - 重试派发失败（signal 带 _dispatch_retry_id）→ bump 既有记录
          retry_count，不追加新记录（D2：重试失败不重复落盘）；
        - 编程错误（TypeError/AttributeError/NameError/ValueError）→
          signal_type=admin_dispatch_programming_error、severity=critical
          记录（evidence 含异常类型/消息/core/ 内最深调用点/原信号）；
        - 其余异常（OSError/超时/provider 类）→ 维持原 signal_type 升级
          记录。
        两条分流路径均带 next_retry_at/retry_count（自动巡检来源，
        signal_rec 非 None）；manual 派发（signal_rec=None）失败只落
        升级不重试（不带 next_retry_at）。
        """
        # 重试派发失败：bump 既有记录后结束，不重复落盘（D2）
        retry_id = signal.get("_dispatch_retry_id")
        if retry_id:
            self.store.bump_dispatch_retry(retry_id, DISPATCH_RETRY_MAX)
            self.logger.error(
                "admin_monitor",
                f"Dispatch retry failed for record {retry_id}, "
                f"bumped retry_count to max {DISPATCH_RETRY_MAX}",
            )
            return
        # 按异常类型分流
        if isinstance(exc, _PROGRAMMING_ERROR_TYPES):
            self._escalate_dispatch_programming_error(signal, signal_rec, exc)
        else:
            self._escalate_dispatch_failure_original(signal, signal_rec, exc)

    def _escalate_dispatch_programming_error(
        self, signal: dict, signal_rec: dict, exc: Exception
    ) -> None:
        """派发期编程错误升级落盘（admin-dispatch-failure-escalation D1）。

        signal_type=admin_dispatch_programming_error、severity=critical 记录，
        evidence 含异常类型/消息/core/ 内最深调用点/原信号 signal_type/spec/
        severity。同类未处理告警存在时按 unhandled_for 跳过（同
        _escalate_reset_programming_error R3 去重模式，防每轮巡检重复落盘）。
        重试失败走 _escalate_dispatch_failure 入口 bump，不重复落盘。
        """
        spec = signal.get("spec")
        if self.store.unhandled_for(spec, "admin_dispatch_programming_error") is not None:
            return  # 同类未处理告警已存在：跳过去重
        callsite = self._deepest_core_callsite(exc)
        original_signal = {
            "signal_type": signal.get("signal_type"),
            "spec": spec,
            "severity": signal.get("severity"),
        }
        evidence = {
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "original_signal": original_signal,
        }
        if callsite:
            evidence["callsite"] = callsite
        entry = {
            "kind": ESCALATION,
            "signal_type": "admin_dispatch_programming_error",
            "spec": spec,
            "severity": "critical",
            "description": (
                f"Administrator 派发期编程错误（{type(exc).__name__}: {exc}）："
                f"spec '{spec}' 信号 {signal.get('signal_type')} 唤起 "
                "Administrator 时提示词构造/序列化失败，Administrator 无法修复"
                "（非环境问题）"
            ),
            "evidence": evidence,
            "original_signal": original_signal,
            "recommended_action": SIGNAL_RECOMMENDATION.get("admin_dispatch_programming_error", ""),
        }
        self._attach_dispatch_retry_fields(entry, signal_rec)
        try:
            self.store.append(attach_trigger(entry))
            self.logger.error(
                "admin_monitor",
                f"派发期编程错误已升级（admin_dispatch_programming_error）"
                f"spec='{spec}' signal_type={signal.get('signal_type')} "
                f"异常={type(exc).__name__}: {exc}" + (f" 调用点={callsite}" if callsite else ""),
            )
        except Exception as e:
            self.logger.error(
                "admin_monitor",
                f"admin_dispatch_programming_error 升级落盘失败: {e}",
            )

    def _escalate_dispatch_failure_original(
        self, signal: dict, signal_rec: dict, exc: Exception
    ) -> None:
        """派发失败运维异常（OSError/超时/provider 类）→ 维持原 signal_type 升级记录
        （admin-dispatch-failure-escalation D1）。

        同样附带 next_retry_at/retry_count 参与 D2 重试（瞬态失败恰是重试
        高价值场景——proposal 目标③针对派发链本身，不限于编程错误）。
        evidence 统一携带 original_signal 供重试重建原信号。
        """
        spec = signal.get("spec")
        original_signal = {
            "signal_type": signal.get("signal_type"),
            "spec": spec,
            "severity": signal.get("severity"),
        }
        entry = {
            "kind": ESCALATION,
            "signal_type": signal.get("signal_type"),
            "spec": spec,
            "severity": signal.get("severity"),
            "description": signal.get("description"),
            "evidence": signal.get("evidence"),
            "action_taken": f"Administrator 唤起失败: {exc}",
            "recommended_action": signal.get("recommended_action"),
            "original_signal": original_signal,
        }
        self._attach_dispatch_retry_fields(entry, signal_rec)
        try:
            self.store.append(attach_trigger(entry))
            self.logger.error(
                "admin_monitor",
                f"Administrator 派发失败（运维异常，原类型升级）"
                f"spec='{spec}' signal_type={signal.get('signal_type')} "
                f"异常={type(exc).__name__}: {exc}",
            )
        except Exception as e:
            self.logger.error(
                "admin_monitor",
                f"派发失败运维异常升级落盘失败: {e}",
            )

    def _attach_dispatch_retry_fields(self, entry: dict, signal_rec: dict) -> None:
        """附加重试语义字段（admin-dispatch-failure-escalation D2）。

        自动巡检来源（signal_rec 非 None）→ 可重试：entry 附带
        next_retry_at（now + escalation_cooldown_minutes）与 retry_count=0；
        manual 派发（signal_rec=None）→ 不重试（不带 next_retry_at），
        保持原语义：手动呼叫 Administrator 失败只升级人工、不自动重试。
        """
        if signal_rec is None:
            return
        next_retry = time.time() + self.cooldown_minutes * 60
        entry["next_retry_at"] = datetime.fromtimestamp(next_retry, tz=timezone.utc).isoformat()
        entry["retry_count"] = 0

    def _close_dispatch_failures_on_success(self, signal: dict) -> None:
        """dispatch 成功（run_administrator 正常返回）→ 关闭该 spec 未处理的
        派发失败升级记录（admin-dispatch-failure-escalation D2）。

        仅关闭带 next_retry_at 字段的未处理 kind=escalation 记录（两条分流
        路径：admin_dispatch_programming_error 与原类型记录均带该字段；手动
        唤起的记录不带，天然不关）；其他升级记录（人工处置中/其他原因）不受
        影响。闭环发生在 dispatch 时刻，不扩 alert_lifecycle._SIGNAL_CONDITIONS。
        """
        spec = signal.get("spec")
        if not spec:
            return
        try:
            closed = self.store.close_dispatch_failure_alerts(spec, "后续派发成功")
            if closed:
                self.logger.info(
                    "admin_monitor",
                    f"Dispatch succeeded for '{spec}', closed {closed} "
                    f"dispatch-failure escalation(s)",
                )
        except Exception as e:
            self.logger.error(
                "admin_monitor",
                f"Failed to close dispatch-failure escalations for '{spec}': {e}",
            )

    def _rebuild_dispatch_signal(self, rec: dict) -> Optional[dict]:
        """从派发失败升级记录重建原信号（admin-dispatch-failure-escalation D2）。

        优先读记录顶层 original_signal 字段（结构化 dict，不被 store 归一）；
        回退解析 evidence（编程错误记录 evidence 为 JSON 串，内含
        original_signal）；字段缺失时从记录顶层补齐（description/
        recommended_action）。原信号 signal_type 必须存在（否则判定
        解析失败返回 None，跳过该条记录）。
        """
        original = rec.get("original_signal")
        if isinstance(original, str):
            try:
                original = json.loads(original)
            except (ValueError, TypeError):
                original = None
        if not isinstance(original, dict):
            original = None
        # 回退：解析 evidence JSON 串
        if original is None:
            evidence = rec.get("evidence")
            if isinstance(evidence, str):
                try:
                    parsed = json.loads(evidence)
                except (ValueError, TypeError):
                    parsed = None
                if isinstance(parsed, dict):
                    original = parsed.get("original_signal")
                    if isinstance(original, str):
                        try:
                            original = json.loads(original)
                        except (ValueError, TypeError):
                            original = None
        if not isinstance(original, dict):
            original = {}
        signal = dict(original)
        signal.setdefault("signal_type", rec.get("signal_type"))
        signal.setdefault("spec", rec.get("spec"))
        signal.setdefault("severity", rec.get("severity"))
        signal.setdefault("description", rec.get("description"))
        signal.setdefault("recommended_action", rec.get("recommended_action"))
        if not signal.get("signal_type"):
            return None
        return signal

    # ── 辅助 ────────────────────────────────────────────────────

    def _reset_env_blocked_after_disposition(self, signal: dict, disp) -> None:
        """阻塞处置收尾自动复位（add-blocked-reverify-lane D2 +
        frozen-scenario-schema-migration D3）。

        result=resolved/partially-resolved + 信号命中自动复位集合（env 族 +
        blocked_stuck；signal_type 或 underlying_signal_type 任一命中，见
        disposition_signal_hits_auto_reset）→ 框架机械判定：branch 已合并 →
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
        # 防御：信号类型不属复位集合不触发（fix-manual-invoke-signal-type-
        # passthrough 2.1：感知 underlying_signal_type 透传）——消费点已前置
        # 检查，此处再兜底，杜绝调用路径遗漏。
        if not disposition_signal_hits_auto_reset(signal):
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
                # fix-observability-gaps 2.1：transition_gate 带 context（恢复来源）
                sm.transition_gate(
                    spec, "testing",
                    trigger_run_id=None, agent_type=None, channel="recovery",
                )
                sm.update_spec(spec, {"error": None})
                # verifier 入队：pm_engine 存在时最小侵入调用 handle_event；
                # pm_engine 缺失时仅靠 daemon recovery 的 implemented 分支兜底
                # （testing 态在 INTERRUPTED_STATES 中，重启回退 ready 重新检测）
                if self.pm_engine is not None:
                    # 事故根因修复（add-control-plane-silent-failure-guards 3.4）：
                    # 生产签名 handle_event(event_kind, spec_name, spec_entry) 要求
                    # 3 必填位参——旧调用 `handle_event("spec_implemented", spec)`
                    # 缺 spec_entry 必然 TypeError，verifier 入队静默丢失（spec 卡
                    # 在 testing 无人驱动）。spec_entry 复用上文 read_one 结果。
                    self.pm_engine.handle_event("spec_implemented", spec, spec_entry)
                self.logger.info(
                    "admin_monitor",
                    f"env 阻塞处置复位（直通道）：'{spec}' transition_gate(testing)"
                    f" + verifier 入队重验",
                )
            else:
                # 既有路径：VALID_TRANSITIONS 允许 BLOCKED→READY
                # fix-observability-gaps 2.2：恢复复位来源（ready 重实现）
                sm.transition(
                    spec, "ready",
                    trigger_run_id=None, agent_type=None, channel="recovery",
                )
                sm.update_spec(spec, {"error": None})
                self.logger.info(
                    "admin_monitor",
                    f"env 阻塞处置复位：'{spec}' → ready（实现阶段熔断/未合并）",
                )
        except (TypeError, AttributeError, NameError) as pe:
            # 编程错误升级（add-control-plane-silent-failure-guards D3）：
            # 三类异常是代码缺陷的典型签名（实参数量不符/属性缺失/未定义名），
            # 重试无意义、Administrator 也无法修复——落 critical ESCALATION
            # 并携带调用点，不再静默降级为一行 WARNING（事故链第 2/3 层）。
            # 绝不重抛（处置记录已先落盘，右关联设计不被破坏）。
            self._escalate_reset_programming_error(pe, signal, reset_path)
        except Exception as e:
            # 运维失败（OSError/子进程/网络）保持既有 WARNING 语义，不升级
            self.logger.warning(
                "admin_monitor",
                f"env 阻塞处置复位失败 '{spec}'（reset_path={reset_path}）: {e}",
            )

    @staticmethod
    def _deepest_core_callsite(exc: Exception):
        """取异常 traceback 中 core/ 内最深栈帧的 `文件:行 (函数名)`。

        design D4：复现本事故需要读源码/日志才知道坏在哪行；把调用点直接写
        进告警，工程侧无需复现即可定位。core/ 内最深帧 = 栈底方向最后一个
        路径含 core/ 段落的帧（异常真正冒出的位置）。无 core 帧（罕见于
        纯测试注入）时回退最外层帧。
        """
        frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
        core_frames = [fr for fr in frames if "core" in Path(fr.filename).parts]
        deepest = core_frames[-1] if core_frames else (frames[-1] if frames else None)
        if deepest is None:
            return None
        # 报告用最短可读路径：剥到 core/ 段为止（core/xxx.py:行 (函数)）
        readable = deepest.filename
        if "core" in Path(readable).parts:
            marker = "/core/"
            readable = readable[readable.rfind(marker) + 1 :]
        return f"{readable}:{deepest.lineno} ({deepest.name})"

    def _escalate_reset_programming_error(
        self, exc: Exception, signal: dict, reset_path: str
    ) -> None:
        """复位路径编程错误升级落盘（add-control-plane-silent-failure-guards D3）。

        落 kind=escalation、signal_type=admin_reset_programming_error、
        severity=critical 告警（经 attach_trigger 埋点），含 spec、reset_path、
        异常类型/消息、core/ 内最深调用点（文件:行 (函数名)）。同类未处理
        告警存在时按 unhandled_for 跳过（R3 去重，防每轮巡检重复落盘）。
        自身失败只记日志、绝不重抛——处置记录先落盘的右关联设计不被破坏。
        """
        spec = signal.get("spec")
        if self.store.unhandled_for(spec, "admin_reset_programming_error") is not None:
            return  # 同类未处理告警已存在：跳过去重，不重复落盘
        callsite = self._deepest_core_callsite(exc)
        try:
            self.store.append(
                attach_trigger(
                    {
                        "kind": ESCALATION,
                        "signal_type": "admin_reset_programming_error",
                        "spec": spec,
                        "severity": "critical",
                        "description": (
                            f"复位路径编程错误（{type(exc).__name__}: {exc}）："
                            f"spec '{spec}' 阻塞处置收尾触发代码缺陷，Administrator "
                            "无法修复（非环境问题）"
                        ),
                        "evidence": (
                            f"signal_type={signal.get('signal_type')}; "
                            f"reset_path={reset_path}; 异常={type(exc).__name__}: {exc}"
                            + (f"; 调用点={callsite}" if callsite else "")
                        ),
                        "recommended_action": SIGNAL_RECOMMENDATION.get(
                            "admin_reset_programming_error", ""
                        ),
                    }
                )
            )
            self.logger.error(
                "admin_monitor",
                f"复位路径编程错误已升级（admin_reset_programming_error）"
                f"spec='{spec}' reset_path={reset_path} 异常={type(exc).__name__}"
                + (f" 调用点={callsite}" if callsite else ""),
            )
        except Exception as e:
            # 升级告警自身失败只记日志：不得再抛、不得回滚已落盘的处置记录
            self.logger.error(
                "admin_monitor",
                f"admin_reset_programming_error 升级落盘失败: {e}",
            )

    def _reset_orphaned_after_disposition(self, signal: dict) -> None:
        """孤儿状态处置收尾复位（orphaned-state-signal R3）。

        orphaned_state 信号唤起 Administrator，处置成功（result=resolved/
        partially-resolved，已由调用方前置检查）后框架机械复位，无需 admin
        手动 reset spec 状态：
        - testing：transition_gate(testing) 幂等（already testing）+ verifier
          入队重验（spec_implemented 重派），复用 env 阻塞直通道语义；
        - implementing：transition(ready) 清 error 重实现（VALID_TRANSITIONS
          允许 IMPLEMENTING→READY）。

        自身异常只记日志（右关联：处置记录永远先落盘，复位失败不得回滚）。
        """
        spec = signal.get("spec")
        if not spec:
            return
        sm = self.state_machine
        if not hasattr(sm, "read_one") or not hasattr(sm, "update_spec"):
            return
        spec_entry = sm.read_one(spec)
        if not spec_entry:
            return
        status = spec_entry.get("status")
        if status == "testing":
            try:
                # fix-recovery-path-blockers D2：派发 verifier 前与在飞 admin run
                # 互斥——admin 正在写 STATE/场景文件（test_scenarios.json）时复位
                # 重验会读半成品产物。守卫按 spec 单键聚合、覆盖**任意**
                # signal_type（admin 处置的 signal_type 不只有 orphaned_state）。
                # 在飞判定为真 → 跳过本次复位（不写状态、不派发）并记 INFO，
                # SPEC 保持原样（MUST NOT 因此写额外状态）。
                if self._has_active_admin_run_for_spec(spec):
                    self.logger.info(
                        "admin_monitor",
                        f"孤儿 testing 复位跳过 '{spec}': admin 处置在飞，"
                        f"verifier 重验派发互斥（fix-recovery-path-blockers D2）",
                    )
                    return
                # fix-observability-gaps 2.1：transition_gate 带 context（恢复来源；
                # 正常路径为幂等 old==new，state_machine 幂等分支不产生日志；
                # 兜底真实转换时也带上恢复来源）
                sm.transition_gate(
                    spec, "testing",
                    trigger_run_id=None, agent_type=None, channel="recovery",
                )  # 幂等（already testing）
                sm.update_spec(spec, {"error": None})
                if self.pm_engine is not None:
                    self.pm_engine.handle_event("spec_implemented", spec, spec_entry)
                self.logger.info(
                    "admin_monitor",
                    f"孤儿 testing 复位：'{spec}' transition_gate(testing)幂等"
                    " + verifier 入队重验",
                )
            except Exception as e:
                self.logger.warning(
                    "admin_monitor",
                    f"孤儿 testing 复位失败 '{spec}': {e}",
                )
        elif status == "implementing":
            try:
                # fix-observability-gaps 2.2：孤儿 implementing 复位（恢复来源）
                sm.transition(
                    spec, "ready",
                    trigger_run_id=None, agent_type=None, channel="recovery",
                )
                sm.update_spec(spec, {"error": None})
                self.logger.info(
                    "admin_monitor",
                    f"孤儿 implementing 复位：'{spec}' → ready 重实现",
                )
            except Exception as e:
                self.logger.warning(
                    "admin_monitor",
                    f"孤儿 implementing 复位失败 '{spec}': {e}",
                )
        else:
            self.logger.debug(
                "admin_monitor",
                f"孤儿信号但 spec '{spec}' 状态 {status} 无需复位（可能已被处置）",
            )

    def _apply_choice_execution(self, signal: dict, disp) -> None:
        """Administrator 处置 choice_id 非空 → 执行注册表动作映射（4.2）。

        与人工 alert-resolve 端点共用 ``execute_adjudication_choice``：同一
        动作映射、同一留痕格式。执行结果只记审计日志（最终 DISPOSITION
        记录已含 choice_id 留痕，动作步骤入日志 context）；执行失败记
        ERROR 不阻塞后续收尾（escalation 闭环 / 升级告警），失败状态由
        日志与既有告警面呈现。
        """
        choice_id = str(getattr(disp, "choice_id", "") or "").strip()
        if not choice_id:
            return
        spec = signal.get("spec") or disp.spec
        if not spec:
            self.logger.warning(
                "admin_monitor",
                f"处置 choice_id={choice_id} 无关联 spec，跳过执行",
            )
            return
        # 依据原文随执行留痕（截断防日志膨胀；完整依据已在 DISPOSITION 记录）
        basis = str(getattr(disp, "actions_taken", "") or "")[:200]
        try:
            from core.dashboard.data.admin_actions import execute_adjudication_choice

            result = execute_adjudication_choice(
                self.project_root,
                spec,
                choice_id,
                note=basis,
                signal_type=str(signal.get("signal_type") or ""),
            )
        except Exception as e:
            self.logger.error(
                "admin_monitor",
                f"处置 choice 执行异常 choice_id={choice_id} spec='{spec}': {e}",
            )
            return
        if result.get("ok"):
            self.logger.info(
                "admin_monitor",
                f"处置 choice 执行成功 choice_id={choice_id} spec='{spec}'",
                {"steps": result.get("steps") or [], "action": result.get("action")},
            )
        else:
            self.logger.error(
                "admin_monitor",
                f"处置 choice 执行失败 choice_id={choice_id} spec='{spec}': "
                f"{result.get('error')}",
                {"steps": result.get("steps") or []},
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
                waived = any(re.search(pattern, text) for pattern in _WAIVER_GRANT_PATTERNS)
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
            self.logger.warning(
                "admin_monitor", f"family_explosion 放行但状态机不支持写豁免位（spec={spec}）"
            )
            return
        try:
            sm.update_spec(spec, {"_family_waiver": "true"})
            self.logger.info(
                "admin_monitor",
                f"family_explosion 人工放行: '{spec}' 已设置 _family_waiver=true（单次豁免）",
            )
        except Exception as e:
            self.logger.warning("admin_monitor", f"family_explosion 豁免位设置失败: {e}")

    def _apply_infra_reclassification(self, signal: dict, disp) -> None:
        """infra 回拨处置（evo-infra-failure-budget-exempt R3）：从 _verify_fail_rounds 减回误计入的 infra 轮次并解冻。

        Administrator 处置文本显式声明「回拨 N 轮」（实为 infra 却计入
        _verify_fail_rounds 的历史轮次，策略生效前已误计入）→ 调
        ``pm_engine.reclassify_infra_rounds``：原子改写
        ``_verify_fail_rounds = max(0, current - n)`` + 解冻 + 审计留痕
        （admin_store DISPOSITION 记录，幂等按 reclassify_key 去重）。

        判定（对齐 ``_apply_family_waiver`` 文本识别范式，admin_monitor.py:1189）：
          - 结构字段 ``disp.infra_reclassify_rounds`` > 0 优先级最高；
          - 否则文本兜底：actions_taken / summary / recommended_action 含
            「回拨 N 轮」/「reclassify N rounds」等显式回拨语义，且不含否定短语。
          仅 result=resolved/partially-resolved 时触发（处置未成功不执行）。

        **方向**：只做减法（product→infra 方向）。env→product-bug 属相反方向
        （补计），不在此入口。
        """
        if getattr(disp, "result", None) not in ("resolved", "partially-resolved"):
            return
        spec = signal.get("spec") or getattr(disp, "spec", None)
        if not spec:
            return

        # ── 结构字段优先 ──
        n = 0
        try:
            n = int(getattr(disp, "infra_reclassify_rounds", 0) or 0)
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            # ── 文本模式兜底 ──
            text = (
                f"{(disp.actions_taken or '')}\n{(getattr(disp, 'summary', '') or '')}\n"
                f"{(disp.recommended_action or '')}\n{(getattr(disp, 'problem', '') or '')}"
            )
            if any(neg in text for neg in _RECLASSIFY_NEGATION_PHRASES):
                self.logger.info(
                    "admin_monitor",
                    f"infra 回拨被否定短语拦截 '{spec}'（保守不触发回拨）",
                )
                return
            for pattern in _RECLASSIFY_GRANT_PATTERNS:
                m = re.search(pattern, text)
                if m:
                    try:
                        n = int(m.groupdict().get("n") or 0)
                    except (TypeError, ValueError):
                        n = 0
                    if n > 0:
                        break
        if n <= 0:
            return

        # ── 委托 pm_engine.reclassify_infra_rounds（核心 API 在 verification）──
        if self.pm_engine is None or not hasattr(self.pm_engine, "reclassify_infra_rounds"):
            self.logger.warning(
                "admin_monitor",
                f"infra 回拨但 pm_engine 不可用（spec={spec}）— 无法执行回拨",
            )
            return
        try:
            result = self.pm_engine.reclassify_infra_rounds(
                spec,
                n,
                f"admin disposition: {getattr(disp, 'run_id', '')}",
                actor="admin",
            )
            self.logger.warning(
                "admin_monitor",
                f"infra 回拨: '{spec}' fail_rounds → {result.get('fail_rounds')} "
                f"（减回 {result.get('applied', 0)} 轮，status={result.get('status')}）",
            )
        except Exception as e:
            self.logger.warning(
                "admin_monitor",
                f"infra 回拨执行失败 '{spec}'（不阻断处置落痕）: {e}",
            )

    @staticmethod
    def _spec_from_run_id(run_id: str, prefixes=None):
        """从 run_id 还原 spec 名：匹配 <prefix><spec>-<ts> 结构。

        如 impl-myspec-1735... → myspec；planner-plan-myspec-1735... → myspec。
        无法识别返回 None。

        orphaned-state-probe-calibration：归一前缀改用真源**全量**前缀
        ``core/agent_runner/run_files.py:RUN_ID_AGENT_PREFIXES``（顺序与真源
        一致、长前缀在前，含 repair- 等全部 run 前缀）——活跃/归属判定对
        repair 通道不再失明（2026-09-15 活跃 repair run 被判「无驱动」误报
        根因①）。失败计数语义拆分到 ``_RUN_PREFIXES``：需要按失败子集还原时
        显式传入（_detect_repeated_failures），MUST NOT 随本函数默认全量前缀
        扩大计数口径（planner-/test- 失败 run 不得纳入，design 1 拆分约束）。

        后缀兼容 attempt（-a<n>）与瞬态重试（-r<n>，fix-provider-transient-backoff
        引入的 in-place retry run_id，形如 <base>-a1-r1）：两者都不影响 spec 名
        还原，若漏剥 -r<n> 将解析失败返回 None，导致 _has_recent_progress 匹配
        不到活跃 run 而误报 stuck（evo-verifier-result-single-source 事故实证）。
        """
        from core.agent_runner.run_files import RUN_ID_AGENT_PREFIXES

        if prefixes is None:
            prefixes = RUN_ID_AGENT_PREFIXES
        for p in prefixes:
            prefix = p[0] if isinstance(p, tuple) else p
            if not run_id.startswith(prefix):
                continue
            rest = run_id[len(prefix) :]
            m = re.match(r"^(.*)-\d{9,10}(-(?:a|r)\d+)*$", rest)
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
        """该 spec 是否存在窗口内有写活动的 run 文件（有进度）——非 admin 前缀。

        fix-recovery-path-blockers D1：与模块级 `_has_recent_spec_run` 同源，
        排除 `admin-` 前缀（`_is_admin_run_id` 单点判定）——Administrator 的
        处置 run 是处置者的活动，不是被处置 SPEC 的驱动证据。两处实现共用
        `_is_admin_run_id`，勿二次漂移。
        """
        if not runs_dir.is_dir():
            return False
        try:
            files = list(runs_dir.glob("*.jsonl"))
        except OSError:
            return False
        for p in files:
            if _is_admin_run_id(p.stem):
                continue
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
        """把当前快照与上次记录对比，状态变化则追加变更事件；每轮统一裁剪过期条目。"""
        history = self._load_history()
        # fix-observability-gaps 4.1：保留窗由 1 小时提升至 24 小时
        # （跨日状态反复不可复盘事故根因）。
        # 口径说明：仅针对 ready↔implementing 的状态切换——非这两个状态的
        # spec 记录不进入 changes（见下方 if status not in ("ready", "implementing")）。
        # flapping 检测（_detect_flapping, FLAPPING_WINDOW_MINUTES=10）按
        # 自身 10 分钟窗过滤，不受保留窗提升影响。
        # 量级评估（2026-09-17 实测）：24h 内自动调度 ready↔implementing
        # 切换约 100-300 条（日均 10-20 spec，每 spec 每日 2-5 次自动转换），
        # 内存占用可接受（每条 ≤200B → 300 条 ≈60KB）；不加条数上限。
        # code-review b7cd3526214a：spec 暂离活跃集（testing/bug-found 等）
        # 不再立即删除整条历史——冻结 last_status/changes 保留至下方
        # 24 小时过期窗自然淘汰，跨第三态的切换序列仍可累计触发 flapping；
        # 条目量受 24h 窗约束，不会无界膨胀。
        HISTORY_RETENTION_SECONDS = 24 * 60 * 60  # 24 小时
        cutoff = now - HISTORY_RETENTION_SECONDS
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
                changed = True
            elif not rec:
                changed = True
            elif not isinstance(rec, dict) or rec.get("inactive_since") is not None:
                # 暂离归来：重写记录时丢弃过期计时戳（一次性写盘）
                changed = True
            # code-review 9063aad172d4：裁剪不再只挂在追加分支——每轮对读到的
            # changes 统一按 cutoff 过滤后再回写，spec 长期停留同一状态时旧条目
            # 同样被 24h 窗淘汰。过滤为空转（未删任何条目）时 changed 不置位，
            # 不产生额外写盘，维持「写盘只发生在边界时刻」的口径。
            pruned = [c for c in changes if c[0] >= cutoff]
            if len(pruned) != len(changes):
                changed = True
            changes = pruned
            history[name] = {"last_status": status, "changes": changes}
        # 清理暂离/退场 spec 的历史（避免文件无限膨胀）：不立即删除，改为
        # 冻结保留至 24 小时过期窗自然淘汰——inactive_since 自首次观察到
        # 暂离起算（惰性打点，一次性写盘），写盘只发生在打点/归来清戳/
        # 到期删除等边界时刻，非每轮落盘。
        active = {n for n, e in specs.items() if e.get("status") in ("ready", "implementing")}
        for name in list(history.keys()):
            if name in active:
                continue
            rec = history.get(name)
            if not isinstance(rec, dict):
                del history[name]
                changed = True
                continue
            inactive_since = rec.get("inactive_since")
            if not isinstance(inactive_since, (int, float)):
                rec["inactive_since"] = now
                changed = True
                continue
            if now - inactive_since >= HISTORY_RETENTION_SECONDS:
                del history[name]
                changed = True
        if changed:
            self._save_history(history)
