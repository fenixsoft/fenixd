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
import math
import os
import re
import subprocess
import tempfile
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.timelib import from_epoch, now_local, parse_ts

from .admin_store import (
    AdminStore,
    SIGNAL,
    ESCALATION,
    DISPOSITION,
    evidence_project,
    _fsync_parent_dir,
)
from .alert_lifecycle import (
    attach_trigger,
    find_resolvable,
    find_self_healable,
    is_spec_attached_signal,
    DEFAULT_SELF_HEAL_QUIET_MINUTES,
)

# code-review a132ca295b06：family_explosion 放行 / infra 回拨的处置文本豁免
# 解析（_WAIVER_* / _RECLASSIFY_* 常量 + 纯判定）单源在 admin_monitor_text_rules，
# 本类 _apply_family_waiver / _apply_infra_reclassification 薄委托调用。
from .admin_monitor_text_rules import (
    family_waiver_granted,
    infra_reclassify_rounds,
    is_reclassify_negated,
)

# add-blocked-reverify-lane D2：env 阻塞复位判定与复位路径常量
from core.pm_engine.verification import (
    ENV_BLOCK_SIGNAL_TYPES,
    resolve_env_blocked_reset_path,
)

# evo-add-wip-defer-merge-retry-consumer 2.3：WIP 等待豁免的上限口径与周期
# 消费者（queue.py）共用同一常量——超限即「降级人工 + 豁免自动失效」单源。
from core.pm_engine.dispatch.queue import (
    WIP_DEFER_WINDOW_MINUTES,
    WIP_DEFER_MAX_ROUNDS,
    agent_worker_thread_name,
)

# code-review item a10425b71546：run 终态判定的尾读窗口与
# core.agent_runner.liveness._TAIL_READ_WINDOW 单源对齐（64KB，覆盖携带长
# stderr 摘录的终态行），不再各写一份窗口常量继续漂移。import 失败（模块
# 加载顺序等异常态）兜底同值，不因窗口常量缺失中断本模块加载。
try:
    from core.agent_runner.liveness import _TAIL_READ_WINDOW as _RUN_TAIL_READ_WINDOW
except Exception:  # pragma: no cover - 兜底同值，仅防加载顺序异常
    _RUN_TAIL_READ_WINDOW = 64 * 1024

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
# evo-add-codefix-conn-error-cooldown 3.1：daemon_errors 指纹记账的「跨日同刻
# 复发」升级维度（design D6）。保留每指纹最近一次失败终态时刻，新失败与上次
# 跨日差在 24h±5 分钟内即升级 escalation，不受已知指纹重启冷却窗压制（2026-09
# 连续 4 天实测样本跨日时刻差 <2 秒，±5 分钟容差充裕）。模块常量不入 config
# （对齐本层既有做法，规避「新增配置项必须带 Dashboard UI」约束）。
DAEMON_ERROR_CROSSDAY_PERIOD_SECONDS = 24 * 3600
DAEMON_ERROR_CROSSDAY_TOLERANCE_SECONDS = 5 * 60
# 指纹「最近失败终态时刻」记忆容量上限（实例内存防无界增长；超限淘汰最早的
# 一半）。日志尾读窗口（≤256KB）内的活跃指纹量级远低于此。
DAEMON_ERROR_FP_MEMORY_LIMIT = 512
# evo-fix-crossday-recurrence-fingerprint-normalization 2.1：跨日指纹记忆的
# 持久化状态文件（相对 project_root；仿 .fenix/admin_infra_breaker.json 既有
# 形态：实例 threading.Lock + mkstemp/fsync/os.replace 原子替换）。daemon 重启
# 后加载续用；缺失/损坏降级为日志定向回退检索，不影响主扫描。
CROSSDAY_FP_MEMORY_REL = ".fenix/crossday_fp_memory.json"
# 2.2（design D3）：定向回退检索的逐轮预算与 grep 超时。检索仅对「无记忆且
# tail 窗内次新条目未命中」的指纹触发（重启后首轮常态），预算防多新指纹同轮
# 放大 IO；超限/失败的指纹漏判方向 fail-open。
_CROSSDAY_SEARCH_MAX_PER_SCAN = 4
_CROSSDAY_SEARCH_TIMEOUT_SECONDS = 30
# 日志轮转备份上限（core/logger.py FlockRotatingFileHandler backupCount=5）：
# 回退检索的候选文件集为 fenixd.log 与 fenixd.log.1..5。
_LOG_ROTATION_BACKUPS = 5
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
# in-process 验证活性窗口（evo-inprocess-verify-activity-signal 1.1）：
# .fenix/verify-progress/<spec>.json（verify_engine._write_progress 起跑/逐
# 场景原子写）mtime 落入本窗内视为验证在飞。**独立于 ORPHANED_RUN_GRACE_
# SECONDS（120s）**：进度文件按逐场景节奏写，单场景可跑 4-5 分钟（2026-10-02
# cimbar-airgap-transfer 实测批间隔），沿用 120s 会把「正在长跑」误判为停滞
# （假阴性）。缺省 900s = 对齐 DEFAULT_ORPHANED_STATE_THRESHOLD_MINUTES
# （15 分钟）×60，与孤儿阈值同量级——超窗即恢复既有判定口径，残留 mtime
# 不构成长期豁免。
INPROCESS_VERIFY_ACTIVITY_WINDOW_SECONDS = 900
# 阈值缺省：15 分钟 = 3 个 admin.interval_minutes(5) 巡检周期（design D5，
# 与巡检周期整数倍对齐避免漏检），远短于 stuck（run_timeout+600s ≈ 160 分钟）。
DEFAULT_ORPHANED_STATE_THRESHOLD_MINUTES = 15
# stuck 阈值兜底缺省：_cfg_float 在键缺失/值非法时的回退值取与正常口径同量级的
# 160 分钟（= config.effective_stuck_threshold_seconds 脏配置回退 STUCK_FALLBACK_
# SECONDS 9600s/60），而非 0——0 会让 elapsed <= threshold 判定形同虚设（仅剩
# mtime 宽限与进程/进度反证约束即提前误报 stuck），并使 _detect_orphaned_state
# 的 stuck 交接（stuck_threshold > 0 分支）静默失效、长悬置 spec 双信号双召唤。
DEFAULT_STUCK_THRESHOLD_MINUTES = 160.0

# family_explosion 放行 / infra 回拨的处置文本豁免解析（_WAIVER_* /
# _RECLASSIFY_* 常量与纯文本判定）已抽至 core/admin_monitor_text_rules.py
# （code-review a132ca295b06）：纯函数模块，零副作用、零状态；本模块
# _apply_family_waiver / _apply_infra_reclassification 保留薄委托，
# 落位/日志/pm_engine 回拨等副作用仍在此处。

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
    # code-review item 82ed15325904：env 阻塞族（ENV_BLOCK_SIGNAL_TYPES，本模块
    # DISPOSITION_AUTO_RESET_SIGNAL_TYPES 组成部分）与 SIGNAL_RECOMMENDATION 对齐
    # 显式收录。当前主链路（pm_engine 直写 store + 处置重建）不经 _make_signal
    # 构造该类型，且缺省回退恰为 major、行为不变——补录消除表不对称：未来
    # 任何路径经 _make_signal 构造时严重度不再依赖 .get 缺省的巧合一致。
    "verify_env_blocked": "major",
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
    # add-mergeback-wip-active-coordination 2.2/D4：无主陈旧 WIP 宽限耗尽升级
    # ——defer 批占用者识别为零命中（在飞实现车道分支改动集零命中）、可配置
    # 宽限（缺省 30 分钟）内无人认领。``mergeback_wip_overlap`` 同级 major：
    # 升级是既有 WIP 重叠人工告警族的「无主限期」变体（在飞持有者场景由
    # 事件驱动重试等待、不打扰人工，降噪）；批保持「保留待自动合回」语义，
    # 升级不改变批的预算/台账状态。
    "mergeback_wip_orphan_stuck": "major",
    # evo-add-maintree-stray-wip-sweep 1.4/D3：主树散件 WIP（流水线外产生的
    # tracked 未提交改动）周期盘点归因为无主、宽限耗尽的一次性升级——
    # ``mergeback_wip_orphan_stuck`` 同级 major：同为「无主陈旧 WIP 宽限耗尽」
    # 人工告警族，差异只在数据源（本信号来自 daemon 周期只读盘点，非 defer
    # 批占用者协调）。由 STORED_SIGNAL_TYPES 收录，admin_monitor 摄取唤起。
    "maintree_stray_wip_stale": "major",
    # add-verify-evidence-placement-contract 2.2：主树 untracked 散件超阈值
    # 滞留（entry 级周期盘点）——info 级「只告警不处置」：AdminStore 纯留痕
    # （不进人工队列、无处理生命周期）、Dashboard 承载可见性。**MUST NOT
    # 收录 STORED_SIGNAL_TYPES**：摄取循环对收录类型无条件唤起、无 severity
    # 过滤，收录即把 info 留痕升级为人工唤起，与降噪意图相抵（info 级 +
    # 阈值 + 同指纹一次性三重兜底，观察误报率后再调）。
    # evo-stray-untracked-escalation 显式修订上述裁定适用边界：info 信号本身
    # 维持不收录，第二档升级信号（下条）除外。
    "maintree_untracked_stray_stale": "info",
    # evo-stray-untracked-escalation 2.1：untracked 散件第二档升级信号——
    # 滞留时长 ≥24h 或集合体积 ≥阈值（缺省 500MB）时由 stray_wip 盘点直发，
    # severity major、STORED_SIGNAL_TYPES 收录接入自动唤起（认领执行器：
    # 归档/追加 .gitignore/删除三裁决）。
    "maintree_untracked_stray_escalated": "major",
    # evo-stray-first-sight-prevention 1.1：目录型产物集合首现提示——新型
    # 产物目录首次出现（首现登记无该目录记录、未被 .gitignore 覆盖）即发
    # 一次预防性提示（携带 gitignore 草案），填补 below_threshold 静默缺口。
    # info 对齐 maintree_untracked_stray_stale 先例：只提示不处置、不进
    # STORED_SIGNAL_TYPES（不自动唤起 admin run——提示本身变成新浪费形态
    # 即与预防意图相抵）、不启动升级时钟（24h/体积阈值语义不动）。
    "maintree_untracked_stray_first_sight": "info",
    # evo-whitelist-tracked-patrol 2.1：白名单脱落信号——被 .gitignore `!`
    # 放行规则显式放行（＝声明了入库意图）却不在 git 索引中的路径，由
    # stray_wip 白名单巡检直发。major 对齐 maintree_untracked_stray_escalated
    # 先例：脱落即静默丢失入库意图，只能等 fresh clone / 新开 worktree 断链
    # 才暴露（2026-10-03 c91213f 误删 .fenix/verify.yaml 6 天未察觉实证），
    # 非 critical（不阻塞链路，可人工二选一修复）、非 minor（无任何既有机制
    # 兜底其可见性）。
    "whitelist_untracked": "major",
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
    # evo-inflight-spec-amendment-watch 2.1：spec/changes/<spec>/ 在实现分支
    # 在飞期间被框架外提交者于主树直接修订（已提交形态，现行三道闸门只覆盖
    # 未提交改动）——与分支勾选更新存在 merge-back 相撞风险。major（对照
    # orphaned_state: major）：预警级（结局不变——相撞仍由预演检出按 rehearsed
    # 链路转 repair），非 critical（非全链路瘫痪）、非 minor（相撞后 repair
    # 多耗一轮 run，2026-10-02 cimbar-airgap-transfer 实证 61 轮 / $0.427）。
    "spec_amendment_inflight": "major",
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
    # evo-merge-back-spec-dir-inflight-guard D1a/D2：spec 目录在飞编辑顺延超限
    # 处置指引——自动重试已停止，人工是唯一出路；spec 保持 implementing（不降
    # 级 ready），提交主树 spec 目录后复位 ready 重新放行 merge-back。
    "mergeback_spec_dir_inflight_stuck": "merge-back 顺延超限（spec 目录在飞编辑，窗口/轮数上限已到，自动重试已停止）：人工提交主树 spec/changes/<spec>/ 目录的未提交改动（git add/commit，含 spec 迭代修补）后，把该 spec 复位 ready 重新放行 merge-back（分支与已实现产物保留，勿静默丢弃）；或等待 daemon 恢复通道（recovery）下一轮再试",
    # evo-add-wip-defer-merge-retry-consumer 2.1：等待超限降级处置指引——周期
    # 消费者已停止自动重试，人工是唯一出路（勿复位 ready 后干等：自动通道已关）。
    "mergeback_wip_defer_stuck": "WIP 延迟合回等待超限（窗口/轮数上限已到，自动重试已停止）：人工核对主树与分支改动路径重叠的未提交改动归属后，提交（git add/commit）或 stash（git stash push）主树重叠改动，再把该 spec 复位 ready 重新放行 merge-back；或人工完成该分支向主树的合并",
    # add-mergeback-wip-active-coordination 2.2：无主陈旧 WIP 处置指引——批
    # 语义适配（批无 spec 可重派，指引指向提交/stash 重叠文件；主树清完后
    # 链边界自动合回，无需重派）。
    "mergeback_wip_orphan_stuck": "无主陈旧 WIP 宽限耗尽（占用者识别为零命中，宽限内无人认领）：该批无 spec 可重派，人工核对重叠文件归属后，提交（git add/commit）或 stash（git stash push）主树这些改动，链边界（选批前/收敛出口）自动重试合回核销该批，无需人工重派；识别证据与盲区注记见 evidence（worktree 分支型在飞车道之外的主树直改形态会被按无主升级，升级仅为告警）",
    # evo-add-maintree-stray-wip-sweep 1.4：主树散件 WIP 处置指引——项目级
    # 盘点信号无 spec 可重派，指向人工提交/stash（姊妹信号
    # mergeback_wip_orphan_stuck 同款批语义适配）。
    # evo-add-commit-stray-wip-choice 2.3：带出裁决选项 commit_stray_wip，
    # 与 worktree_manager/stray_wip._write_alert 的 inline recommended_action
    # 同文（文案变更两处同步，防双处漂移）。
    "maintree_stray_wip_stale": "主树散件 WIP 滞留宽限耗尽（周期盘点归因在飞实现车道零命中，无人认领）：人工核对主树未提交改动归属后，提交（git add/commit）或 stash（git stash push）主树这些改动；或执行裁决选项 commit_stray_wip 一键提交信号清单内文件（与 stash 类动作互斥，处置记录附提交 hash）。文件清单与滞留起点见 evidence（含盲区注记——worktree 分支型在飞车道之外的主树直改形态会被按无主升级，升级仅为告警）。同指纹一次性告警，改动消失后盘点状态自动复位",
    # add-verify-evidence-placement-contract 2.2：untracked 散件处置指引——
    # 复制 maintree_stray_wip_stale「只告警不处置」模板：info 级不唤起人工、
    # 不派生自动处置，本信号只增可见性（豁免注记与证据落位约定见 evidence）。
    "maintree_untracked_stray_stale": "主树 untracked 散件超阈值滞留（周期盘点，info 级只告警不处置，不唤起人工）：本告警不派生任何自动处置；人工按需核对主树这些 untracked 文件归属后自行决定挪入证据落位目录 .fenix/verify-evidence/<spec>/、补 ignore 规则或删除；文件清单、阈值与滞留起点见 evidence（.fenix/ negation 放行项与已 ignore 路径不计入）。同指纹一次性告警，指纹消失后盘点状态自动复位",
    # evo-stray-untracked-escalation 2.1：第二档升级处置指引——与
    # worktree_manager/stray_wip._write_untracked_escalated_alert 的 inline
    # recommended_action 同文（文案变更两处同步，防双处漂移）；带出三裁决
    # 选项 id（admin_actions 认领执行器，signal_type 绑定白名单仅收本信号）。
    "maintree_untracked_stray_escalated": "主树 untracked 散件滞留升级（滞留时长超 24 小时或集合体积超阈值，major）：核对主树这些 untracked 文件归属后，执行裁决选项 archive_untracked_stray 显式归档（移入登记目录 .fenix/stray-archive/）、ignore_untracked_stray 追加 .gitignore 或 delete_untracked_stray 删除；文件清单、体积与滞留起点见 evidence（.fenix/ negation 放行项与已 ignore 路径不计入）。同一集合只升级一次，指纹消失后盘点状态自动复位",
    # evo-stray-first-sight-prevention 1.1：首现提示处置指引——建议面语义
    # （与 worktree_manager/stray_wip._write_first_sight_alert 的 inline
    # recommended_action 同源口径：提示只携带预防性 gitignore 草案，不自动
    # 执行 ignore 动作）。
    "maintree_untracked_stray_first_sight": "主树 untracked 散件首现提示（目录型产物集合首次出现，info 级只提示不处置，不唤起人工）：人工核对目录归属后，将 evidence 中 gitignore 草案行（含成因注释）追加至 .gitignore（预防性 ignore，一行消除该目录后续散件告警），或将默认落盘路径移出仓库树/挪入证据落位目录 .fenix/verify-evidence/<spec>/；本提示不自动执行 ignore 动作、不启动升级时钟。同目录仅提示一次（集合内容增长不重提示），目录消失复位后再现视为新首现",
    # evo-whitelist-tracked-patrol 2.1：白名单脱落处置指引——与
    # worktree_manager/stray_wip._write_whitelist_untracked_alert 的 inline
    # recommended_action 同文（文案变更两处同步，防双处漂移）。无裁决执行器
    # 选项（不自动 git add，proposal 非目标明示「信号只唤起人工/裁决处置」），
    # 指向人工二选一。
    "whitelist_untracked": "白名单文件脱落（negation 放行即声明入库意图，放行+未跟踪＝白名单脱落，major）：人工二选一处置——① git add 恢复入库（白名单状态文件应随仓库入库，如 .fenix/verify.yaml / todo.md / config.template.yaml）；② 删除 .gitignore 对应放行规则、承认其为运行时文件（确保整体 ignore 规则覆盖）。MUST NOT 自动执行 git add 类修复动作（本信号只唤起人工/裁决处置）。文件清单与放行规则见 evidence。同指纹一次性告警，指纹消失后盘点状态自动复位",
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
    # evo-inflight-spec-amendment-watch 2.1：在飞修订预警处置指引——指向「等实现
    # 收尾后在分支上补修订或经 repair 合并」（design 关键约束）。与
    # worktree_manager/mergeback.py _report_spec_amendment_inflight 直写记录的
    # inline recommended_action 同文（直写 store 的记录不经 _make_signal，文案
    # 变更两处同步）。
    "spec_amendment_inflight": "主树 spec/changes/<spec>/ 在实现分支在飞期间被框架外修订（已提交，详见 evidence 修订提交列表）：等实现收尾后在分支上补齐同一修订（merge main 或手工同步到分支），或等 merge-back 相撞后经 repair 车道把 main 合入分支（上下文自带修订提交列表根因）；勿在主树侧继续叠加修订加剧分叉",
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
    # 本监视器摄取唤起——未收录则摄取循环（_detect_family_explosion）
    # continue 跳过、记录落 store
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
    # add-mergeback-wip-active-coordination 2.2：无主陈旧 WIP 宽限耗尽升级
    # 告警由 code-fix defer 消费者直发——未收录则记录落 store 后无人摄取、
    # Administrator 不唤起，「MUST NOT 无限期静默等待」的升级出口落空。
    "mergeback_wip_orphan_stuck",
    # evo-add-maintree-stray-wip-sweep 2.2：主树散件 WIP 滞留升级告警由
    # worktree_manager.stray_wip 周期盘点直发——未收录则记录落 store 后无人
    # 摄取、Administrator 不唤起，「散件滞留分钟级浮出」目标静默落空。
    # 记录无 spec（项目级盘点），证据含「项目名=」供无 spec 形态解析。
    "maintree_stray_wip_stale",
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
    # evo-inflight-spec-amendment-watch 1.1：merge-back 主链检出的主树已提交
    # 在飞修订告警由 worktree_manager 直发（_report_spec_amendment_inflight，
    # AdminStore.append）——未收录则记录落 store 后无人摄取、Administrator
    # 不唤起，「修订落地后一个扫描周期内告警」目标落空。
    "spec_amendment_inflight",
    # evo-stray-untracked-escalation 2.1：主树 untracked 散件第二档升级告警由
    # worktree_manager.stray_wip 周期盘点直发——未收录则记录落 store 后无人
    # 摄取、Administrator 不唤起，「滞留时长/体积触顶升级为人工处置」出口
    # 静默落空。记录无 spec（项目级盘点），证据含「项目名=」供无 spec 形态
    # 解析（姊妹 info 信号维持不收录，收录即降噪破防——placement contract
    # 裁定适用边界修订：info 信号维持不收录、升级信号除外）。
    "maintree_untracked_stray_escalated",
    # evo-whitelist-tracked-patrol 2.1：白名单脱落告警由 worktree_manager
    # .stray_wip 白名单巡检直发——未收录则记录落 store 后无人摄取、
    # Administrator 不唤起，「白名单脱落不再等 fresh clone 断链才暴露」的
    # 目标静默落空（c91213f 事故 6 天未察的机制缺口即本出口）。记录无 spec
    # （项目级盘点），证据含「项目名=」供无 spec 形态解析。
    "whitelist_untracked",
)

# 前置探测白名单（evo-signal-preprobe-handled-writeback R1）：请求型
# 「产物存在性」可探测信号——摄取循环在 mark_escalated / 唤起 Administrator
# 之前先做只读探测，诉求已被事实满足（产物/配置已存在）即闭环免唤起。
# 入表约束：仅收「探测谓词与诉求满足是同一事实」的类型（段/文件/配置存在性），
# 探测通过即无剩余动作；需语义判断的类型（manual-intervention、inconclusive_loop
# 等）永不收录。新增类型必须同时给出只读谓词与「满足即无剩余动作」论证。
# 探测异常 fail-open（R4）：按原路径照常唤起，不因探测器自身缺陷吞信号。
PREPROBE_SIGNAL_TYPES = (
    # UI 手动请求补写 .fenix/verify.yaml 的 regression 段：段已存在即诉求满足
    "verify_regression_missing",
    # 请求起草验证契约：.fenix/verify.yaml 存在且可解析即诉求满足
    "verify_contract_missing",
    # 请求裁决产物路径配置：worktree.build_artifact_paths 非空或
    # has_build_artifacts=false（确无产物）裁决已作出即诉求满足
    "build_artifact_paths_missing",
)

# run_id 前缀 → 计入"失败 run"的 agent 类型（失败计数专用子集）
# ⚠️ 真源 = core/agent_runner/run_files.py:RUN_ID_AGENT_PREFIXES（新增 run 前缀
# 只改那里）；本表是它的**子集**——只列计入失败统计的前缀（裸 `planner-`/
# `test-` 不计；细前缀 `planner-plan-`/`planner-judge-` 计入）。
# orphaned-state-probe-calibration：前缀归一（_spec_from_run_id）已改用真源全量
# 前缀表，本表**只**服务失败计数（_detect_repeated_failures 显式传入），不再服务
# 活跃度/归属判定。`repair-` 属实现通道（失败即实现失败）已补入；裸 `planner-`/
# `test-` 仍不计入（不得随归一扩大计数口径——design 1 拆分约束，计入/不计入
# 边界由 tests/test_admin.py::TestFailurePrefixSubset 锁定）。`planner-plan-`/
# `planner-judge-` 属既有 planner 细前缀、自初版即计（同测试锁定）；`admin-`
# 自初版收录——run_id 形如 admin-<spec>-<ts>（core/agent_runner/
# maintenance_runs.py），处置 run 失败同样还原到被处置 spec 计数。
# maintenance-work-ledger 2.2：maintenance- 同步收录——登记型 run
# （maintenance-<scope>-<ts>，core/maintenance_ledger）在失败计数中还原到
# scope 计数，归因/盘点视图识别为有名主体而非泛型无主 agent；与真源其余
# 前缀无子串冲突（顺序无关）。
# code-review item e5ea5fb4b0d1：impl-ocr- 同步收录（OCR 实现车道失败计入
# 失败统计，同 repair- 实现通道先例）——缺失时 impl-ocr-<spec>-<ts> 回落
# 命中 "impl-"，被误还原为 STATE 中不存在的幽灵 spec "ocr-<spec>"（30 分钟
# 窗口累计 3 次即触发 repeated_failures 唤起去处置不存在的 spec）。MUST 排
# 在其子串前缀 "impl-" 之前（_spec_from_run_id 首命中即止，同真源顺序敏感
# 约束），口径由 tests/test_admin.py::TestFailurePrefixSubset 锁定。
# [fenix-ignore:847c916d468e] design 1 拆分约束口径即「裸 planner-/test- 不计、细前缀 planner-plan-/planner-judge- 自初版即计」（TestFailurePrefixSubset 锁定），上方注释已逐项区分并写明 admin- 收录理由，注释与代码一致
_RUN_PREFIXES = (
    "impl-ocr-",
    "impl-",
    "verify-",
    "repair-",
    "planner-plan-",
    "planner-judge-",
    "dispute-judge-",
    "spec-review-",
    "admin-",
    "maintenance-",
)

# ── daemon-error-escalation D6：错误指纹归一化（保守集）────────────
# 只归一化四类：ISO-8601 时间戳→@、UUID→~、≥16 位 hex→~、纯数字序列→#。
# 不动路径与文字骨架——过度归一化会把不同错误误聚合，而"≥2 次才升级"已提供缓冲。
_ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_HEX16_RE = re.compile(r"[0-9a-fA-F]{16,}")
# 「小数+单位字母」形态（evo-fix-crossday-recurrence-fingerprint-normalization
# 1.1，design D1）：延迟/时长类数值（"median 84.0s"、"23.4s"、"5.3s"）。既有
# _STANDALONE_NUMBER_RE 对 "23.4s" 只归一小数点前的整数 23——尾数 4 后跟单位
# 字母 s 不满足「不被字母包围」而被保留，延迟数值不同的同形死亡行指纹必然
# 不等（10-02/10-03 两夜实测 dbd8dc91f1530046 vs 2770ed6f532f254c）。本规则把
# 小数体整体归一为 #、单位字母保留（"23.4s"→"#s"）：仅同形不同值聚合，指纹
# 其余部分（stderr_tail 骨架等）仍须全等，非数值差异照旧区分。负向先行/后行
# 限定与既有保守集同口径（v1.2b、标识符内小数不动）。后视含点号（code-review
# item b45b3b7de2dc）：多段数字（"v1.2.3s"）的尾段 "2.3s" 前导是点号，后视
# 不含点号时照常归一、首段之后全部塌缩（"v1.#s"），两个仅末段不同的多段形态
# 误聚同指纹；点号入后视后整条不动，目标形态 "23.4s"（前导通常为空格/冒号
# 等分隔符）不受影响。
_DECIMAL_UNIT_RE = re.compile(r"(?<![0-9a-zA-Z_.])\d+\.\d+(?=[a-zA-Z])")
# 独立数字 token（不被字母/下划线包围）——run_id、attempt 计数、epoch、超时秒数等
_STANDALONE_NUMBER_RE = re.compile(r"(?<![0-9a-zA-Z_])\d+(?![0-9a-zA-Z_])")

# evo-add-review-failure-attribution 2.1（design D1 按组件模板窄化）：spec_review
# 组件「评审 run 执行失败: <spec>: …」失败行模板（spec_review.py 失败 ERROR 行
# 实况形态）。SPEC 名段呈仓库 spec 目录名形态（[0-9A-Za-z._-]+，无空格无冒号）；
# 第二段非此形态（如 "评审 run 执行失败: claude CLI failed: …"，run_err 文本
# 直接跟前缀、无 SPEC 名段）不匹配整条规则、原样保留——防止错误文本被误剥。
# 剥离后 SPEC 名段替换为 `~`（与 UUID 占位同符，占位符集合不扩）。
_SPEC_REVIEW_FAIL_SPECNAME_RE = re.compile(
    r"^(评审 run 执行失败: )([0-9A-Za-z._-]+)(:.*)$", re.DOTALL
)
# SPEC 名第二嵌点：spec-review run-id token（spec_review.py 生成形态
# ``spec-review-<spec>-<uuid4hex6>-<epoch10>``）。失败异常文本的 latency 段
# 携带该 token（runner format_latency_summary 形态），仅剥模板段则 run_err
# 内嵌 SPEC 名仍使跨 SPEC 指纹互异——同组件窄化补此条。锚定尾部
# ``-<hex6>-<≥9 位数字>``：不匹配 "spec-review-incomplete:" 等骨架文字、
# 不匹配 `.fenix/spec-review/<spec>/` 路径形态（后随 "/"）。
_SPEC_REVIEW_RUNID_RE = re.compile(
    r"\bspec-review-[0-9A-Za-z._-]+-[0-9a-f]{6}-\d{9,}\b"
)


def _normalize_error_message(message: str, component: str = "") -> str:
    """err message 归一化（improve-hot-reload-robustness D6 保守集）。

    顺序：先按 ISO 时间戳（含日期骨架）、UUID、hex 三类带字母形态替换，再替换
    「小数+单位字母」形态（1.1），最后替换独立数字序列——防止 hex 中的数字被
    先行拆散、防止整数先归一拆散小数形态。

    evo-add-review-failure-attribution 2.1：component=="spec_review" 时先剥
    「评审 run 执行失败: <spec>: …」模板的 SPEC 名段与失败文本内嵌的
    spec-review run-id token——不同 SPEC 的同型失败（如限流 0 成功轮）聚到
    同指纹、可跨日追踪；其余组件文字骨架一律不动（沿用上方保守集原则：
    不做全局激进归一化，防不同骨架被误聚）。component 缺省空：既有调用方
    （信号记录指纹等）行为不变。
    """
    msg = str(message)
    if component == "spec_review":
        msg = _SPEC_REVIEW_RUNID_RE.sub("spec-review-~", msg)
        msg = _SPEC_REVIEW_FAIL_SPECNAME_RE.sub(r"\1~\3", msg)
    msg = _ISO_TS_RE.sub("@", msg)
    msg = _UUID_RE.sub("~", msg)
    msg = _HEX16_RE.sub("~", msg)
    msg = _DECIMAL_UNIT_RE.sub("#", msg)
    msg = _STANDALONE_NUMBER_RE.sub("#", msg)
    return msg


def _error_fingerprint(component: str, message: str) -> str:
    """错误指纹 = sha1(component + "\\x00" + normalize(message))（D6）。

    同一 source 同一错误骨架（仅内嵌时间戳/UUID/数字不同）→ 同指纹复现成立；
    不同错误 message 骨架不同 → 指纹不同、不聚合升级。
    """
    raw = f"{component or ''}\x00{_normalize_error_message(message, component)}"
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()


# ── evo-add-daemon-signal-spec-attribution-dedup 1.1/1.2：daemon 级信号 ──
# evidence 原文摘录与 spec 归属提取 ─────────────────────────────────────
# 1.1：daemon_errors 升级信号 evidence 附带的「最近一次同指纹 ERROR 原文摘录」
# 截断限长（字符）。摘录是 1.2 归属提取的基底；限长防超长 traceback 撑爆
# evidence/prompt，折叠空白后取头部（组件名+错误首行承载 spec/分支线索概率
# 最高）。
DAEMON_ERROR_EXCERPT_MAX_CHARS = 300
# 1.2：分支名归属线索正则——fenix/<spec>-<时间戳> 形态（WorktreeManager 派生
# 分支命名；时间戳为收尾的 10-13 位纯数字）。spec 名段非贪婪回溯到「末段纯
# 数字」之前，spec 名内嵌数字段不会被误截；误捕窗口再由互斥侧「该 spec 确有
# 在飞 run 才跳过」二次收窄（design Risks：误判最坏退化为先后各派一次，等于
# 现状，无额外损失）。
_DAEMON_SIGNAL_BRANCH_SPEC_RE = re.compile(
    r"fenix/([0-9A-Za-z._-]+?)-(\d{10,13})(?![\w-])"
)
# 1.3：跳过语义仅适用于「具检测循环重发生命周期」的 daemon 级信号类型（design
# D3——指纹过冷却窗再升级即重发，跳过后有确定的自然重评通路）。当前唯一
# spec=None 形态为 daemon_errors；未来新增无重发生命周期的 None-spec 信号
# 类型 MUST NOT 加入本集合（否则跳过后被静默吞掉且无重评），届时须先补该
# 类型的重评通路。
DAEMON_ATTRIBUTABLE_SIGNAL_TYPES = frozenset({"daemon_errors"})
# 1.3：跳过注记固定文案片段（spec.md「被在飞 run 覆盖、待重评」）——跳过日志
# 与 skipped 处置留痕双处消费，单点维护。
DAEMON_SIGNAL_COVERED_NOTE = "被在飞 run 覆盖、待重评"


def _format_error_excerpt(component, message) -> str:
    """最近一次同指纹 ERROR 原文摘录（1.1）：``[组件名] message``，超长截断。

    摘录含组件名（spec 线索常在组件/路径上下文）；message 折叠空白（logger
    保证单行 JSON，但 json.loads 还原后的 traceback 多行文本会重新带入换行，
    折叠保 evidence 单行形态）；截断取头部。纯文本整形，不影响 ``_fp``
    （指纹由 _error_fingerprint 在摘录之前独立计算）。
    """
    comp = str(component or "unknown")
    text = " ".join(str(message or "").split())
    excerpt = f"[{comp}] {text}".rstrip()
    if len(excerpt) > DAEMON_ERROR_EXCERPT_MAX_CHARS:
        excerpt = excerpt[:DAEMON_ERROR_EXCERPT_MAX_CHARS].rstrip() + "…"
    return excerpt


def _extract_spec_attribution_from_text(text, known_specs=()) -> str:
    """从证据文本（ERROR 原文摘录等）提取 spec 归属（1.2，双线索任一命中）。

    线索一（强模式）：实现分支名 fenix/<spec>-<时间戳> 正则；线索二：已知
    spec 名直接匹配（长名优先——短名是长名前缀时不被短名抢先归属）。命中
    返回 spec 名；无线索（含空文本）返回空串，调用方兜底现状派发（1.4，
    行为不变）。
    """
    if not text:
        return ""
    text = str(text)
    m = _DAEMON_SIGNAL_BRANCH_SPEC_RE.search(text)
    if m:
        return m.group(1)
    for name in sorted(
        (str(s) for s in known_specs if s), key=len, reverse=True
    ):
        if name in text:
            return name
    return ""


# evo-fix-crossday-recurrence-fingerprint-normalization 1.2（design D1 备选
# 路径裁决）：api_timeout 类失败终态「结构化签名（api_timeout 布尔 + stderr_tail
# 骨架哈希）替代整行指纹」为可选路径，本 SPEC 不采用——上方 _DECIMAL_UNIT_RE
# 已把两夜死亡行中唯一跨夜漂移的「延迟小数+单位」归一，整行指纹即可同形聚合
# （stderr_tail 骨架、exit_code、rounds 数等骨架部分本就参与指纹，误聚面更小）；
# 结构化路径须为 daemon_errors 另立指纹空间并做前缀命名空间隔离，复杂度与收益
# 不成比例。若后续实测误聚/漏聚数据需要重启该路径，MUST 以 "structured:" 类
# 前缀与既有指纹空间隔离，且不串扰 daemon_errors 第一维度判定。


# 尾部读上限：日志增长后每轮巡检只 seek 最近 256KB（3.5），避免全量 read_text
_TAIL_ERROR_READ_BYTES = 256 * 1024

# ── 孤儿处置收敛的生效核查（evo-add-admin-orphan-disposition-effect-check）──
# global 占位记法归一：DISPOSITION 记录 spec="global"（daemon 级唤起写占位），
# SIGNAL 记录 spec=None——unhandled_signal_for 严格相等匹配须先归一，否则对
# 429 现场形态（信号 spec=null + 处置 spec="global"）永不命中。
_ORPHAN_GLOBAL_SPEC_PLACEHOLDER = "global"
# 组 spec=global/None 时的日志对账窗口松弛（秒）：处置组记录 created 邻域
# 内的解冻族 Transition 留痕才算本组动作的生效证据（动作发生在唤起后、
# 终态落账前，留痕时刻与记录 created 同源时钟，松弛只吸收写入次序抖动）。
_ORPHAN_EFFECT_LOG_SLACK_SECONDS = 300
# 解冻族留痕的「人为裁决」通道集：dashboard/admin 动作（manual）与恢复/解冻
# 链路（recovery）。auto 通道的状态迁移不构成本判据的生效证据（自动链路
# 本就受冻结剥离约束，且与「人工/处置动作已生效」的核查语义无关）。
_ORPHAN_EFFECT_DELIBERATE_CHANNELS = frozenset({"manual", "recovery"})
# 解冻族 Transition 留痕形态（_finish_transition 成功行：f"Transition: "
# f"{spec} {old} → {new}"）；刻意不匹配 "Gate transition: " 前缀（门禁自动
# 逃生门，非人为裁决证据）。
_ORPHAN_UNFREEZE_TRANSITION_RE = re.compile(r"^Transition: (\S+) blocked → (\S+)\s*$")
# ── 提交类旁证 / STATE 旁证（evo-admin-orphan-effect-evidence-expansion）──
# 提交类旁证的 git 只读查询超时（对齐跨日复发检索 _CROSSDAY_SEARCH_TIMEOUT_
# SECONDS；git 不可用/非仓库/超时按提交类家族无证据处理，fail-closed 不阻塞
# 其余家族，通道参照 core/deliverables.py:1997、core/code_review.py:826 先例）。
_ORPHAN_EFFECT_GIT_TIMEOUT_SECONDS = 30
# 归档收尾提交的消息家族前缀：归档入库（[fenix] archive: <spec> 归档入库）
# 与 admin 收尾动作（[fenix] admin: 提交 <spec> 归档删除收尾…）。
_ORPHAN_EFFECT_FINALIZE_COMMIT_PREFIXES = ("[fenix] archive:", "[fenix] admin:")
# 归档收尾提交的收尾关键词约束：admin 前缀消息可能提及 spec 名但非收尾动作，
# 「前缀 ∧ 关键词 ∧ spec 名」三条件同时满足才命中（单一条件不命中防假阳性）。
_ORPHAN_EFFECT_FINALIZE_COMMIT_KEYWORDS = ("归档", "收尾")
# global 组 spec 名 token 提取（提取不到不猜）：≥3 段小写 kebab-case（本仓
# spec 命名形态 evo-add-xxx / fix-xxx / add-xxx…）；过短英语复合词（merge-
# back、code-review 等）不取。误取由 STATE 无条目/提交消息不匹配兜底
# （fail-closed），仅作提取指针、不构成证据本身。
_ORPHAN_SPEC_NAME_TOKEN_RE = re.compile(
    r"(?<![\w-])([a-z0-9]+(?:-[a-z0-9]+){2,})(?![\w-])"
)
# 分支名尾部派发时间戳剥离（fenix/<spec>-<ts> → spec）：仅剥 ≥10 位纯数字
# 尾段（epoch 秒/毫秒）；-7c1997 类十六进制短后缀是 spec 名组成部分，不剥。
_ORPHAN_SPEC_TOKEN_DISPATCH_TS_RE = re.compile(r"-[0-9]{10,}$")
# merge commit / 归档收尾提交家族锚定的「派发时间戳」放行段（两处共用：
# _is_orphan_merge_commit / _is_orphan_finalize_commit，
# 与上行 _ORPHAN_SPEC_TOKEN_DISPATCH_TS_RE 的串尾锚定口径同向，code-review
# f87ef32726a2）：spec 名后允许紧跟「连字符 + ≥10 位数字」，但数字段后必须
# 到串尾或引号/空白/常见标点分隔符——fix-x-<ts>-backup、fix-x-<ts>abc 等
# 「时间戳段后仍有后缀」形态不再误命中（否则窗口内恰好合并的他人同名前缀
# 分支会被误当本 spec 的 merge-back 证据提前收口底层信号，正是 fail-closed
# 要防的假闭环方向）。
_ORPHAN_MERGE_TS_LOOKAHEAD = (
    r"(?!\w|-(?!\d{10,}(?:$|[\s'\",;)])))"
)
# 单组 spec 名候选上限（边界防失控文本产生的候选膨胀）。
_ORPHAN_SPEC_NAME_TOKEN_LIMIT = 5


def _normalize_orphan_group_spec(spec):
    """处置组 spec 记法归一（None↔"global"）：空值/占位 "global" → None。

    SIGNAL 记录的 daemon 级形态是 spec=None，DISPOSITION 记录是
    spec="global"——关联信号匹配（unhandled_signal_for）与全局形态判定
    都以归一后的 None 为准。
    """
    s = str(spec or "").strip()
    if not s or s.lower() == _ORPHAN_GLOBAL_SPEC_PLACEHOLDER:
        return None
    return spec


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

    code-review item 780797acccdb：spec 名经 ``re.escape`` 转义后再拼模式，
    spec 名含正则元字符不再放大匹配集（同向 fail-open 的另一失真形态，
    本侧已修；event_bus 同名方法委托本实现，两路径同口径）。

    add-harness-adapter-layer 5.1：车道前缀 patterns 改经 current adapter
    （``worktree_pgrep_patterns``，claude 值 ``{impl,verify,repair}-
    <re.escape(spec)>-`` 与原字面量循环逐字节全等，re.escape 转义已收进
    adapter）。
    """
    # 函数内延迟解析：core.agent_runner 包初始化即拉入 runner 重链，
    # admin_monitor 不可成为其导入下游（同 proc_utils.is_claude_process 理由）。
    from core.agent_runner.harness import current_worktree_pgrep_patterns

    try:
        for pattern in current_worktree_pgrep_patterns(spec_name):
            # 前缀互撞（spec 名互为前缀）仍按上方处置记录 defer。
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


# [fenix-ignore:7514e3abee76] 三处归并已由 commit 9362f29b 收敛为单点本函数（spec/signal_type/exclude_run_id 以参传入），条目所述三份手写副本在当前代码不成立
def _merge_admin_runs(records, spec=None, signal_type=None, exclude_run_id=None) -> dict:
    """DISPOSITION 记录按 ``admin_run_id`` 归并（单一实现，勿二次漂移）。

    三处在飞/孤儿判定共用同一归并本体（``_spec_has_active_admin_run`` /
    ``AdminMonitor._has_active_admin_run_for_spec`` 薄封装 /
    ``_recover_orphaned_dispositions`` 的孤儿扫描），差异仅在过滤条件，
    以参数传入（None = 不过滤）：

      - ``spec`` / ``signal_type``：按记录字段精确相等过滤；
      - ``exclude_run_id``：剔除该 run（重派判定排除正被孤儿处理的中断
        run 自身——其 pending 记录是考察对象，不得自证「已有在飞 run」）。

    返回 ``{admin_run_id: {"final": bool, "has_pending": bool, "rec": dict}}``：
    组内出现任一非 pending 记录即 ``final=True``（已终结 run 含
    superseded/interrupted/escalated 终结后仍滞留 store 的 pending 记录均
    算终结）；``rec`` 为该 run 首条记录（孤儿扫描读 created/spec/
    signal_type 用，final 组不会被消费）。在飞 = 组 ``has_pending`` 且非
    ``final``。
    """
    by_run: dict = {}
    for rec in records:
        if rec.get("kind") != DISPOSITION:
            continue
        if signal_type is not None and rec.get("signal_type") != signal_type:
            continue
        if spec is not None and rec.get("spec") != spec:
            continue
        rid = rec.get("admin_run_id")
        if not rid:
            continue
        if exclude_run_id is not None and rid == exclude_run_id:
            continue
        status = rec.get("status") or rec.get("result")
        info = by_run.setdefault(rid, {"final": False, "has_pending": False, "rec": rec})
        if status == "pending":
            info["has_pending"] = True
        else:
            info["final"] = True
    return by_run


def _spec_has_active_admin_run(
    store, spec: str, logger=None, exclude_run_id=None, records=None
) -> bool:
    """该 spec 是否存在在飞/待派发的 Administrator run（任意 signal_type）。

    fix-recovery-path-blockers D2：按 ``(spec)`` 单键聚合 store 中
    ``kind == DISPOSITION`` 的记录，by_run 归并委托 ``_merge_admin_runs``
    （某 ``admin_run_id`` 组 ``has_pending`` 且无终结兄弟记录才算在飞——
    已终结 run 含 superseded/interrupted/escalated 终结后仍滞留 store 的
    pending 记录均不算），不传 signal_type 过滤：
    admin 处置的 signal_type 可能是 ``verify_env_blocked`` /
    ``manual-intervention`` / ``stuck``，不只有 ``orphaned_state``，
    按 ``(spec, signal_type)`` 精确匹配会漏
    （fix-admin-cross-type-duplicate-dispatch：摄取/到期重派/孤儿重派
    三路径统一收拢到本宽口径，跨 signal_type 的在飞处置必须命中守卫）。

    exclude_run_id：透传 ``_merge_admin_runs`` 既有同名参数（缺省 None
    零迁移）——孤儿重派排除正被孤儿处理的中断 run 自身，其 pending
    记录是考察对象，不得自证「已有在飞 run」；仅排除该 run，不排除
    其他在飞 run。

    records：调用方已持有的全库记录快照（可选，code-review c0df5dd3dbbf）
    ——传入则免重复 ``store.read_all()``：同一巡检周期内对多候选复用入口
    快照，消除每候选一次的全库重读（快照本就含全部 DISPOSITION 记录，
    周期内滞后对互斥语义影响可忽略）。

    模块级单一实现：``AdminMonitor._has_active_admin_run_for_spec`` 与
    ``event_bus`` 的两个守卫调用点都委托本函数（store 作为入参），勿复制
    第二份归并实现。判定异常 fail-open 返回 False（守卫故障不阻断恢复路径），
    异常记 WARNING（logger 可选注入）。
    """
    if records is None:
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
    by_run = _merge_admin_runs(records, spec=spec, exclude_run_id=exclude_run_id)
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

    ``AdminMonitor._has_recent_progress`` 已改为委托本函数（仅参数适配），
    扫描体唯一，禁二次漂移。
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


def _build_runs_activity_snapshot(project_root) -> dict:
    """单次 glob+stat 构建 runs 目录活跃快照：``{spec: 最近 run 文件 mtime}``。

    code-review item cfa277dc36e7：_detect_stuck 与 _detect_orphaned_state 旧
    对每个 spec 各自全量 glob+stat（O(spec 数 × run 文件数)，run 文件长期
    累积后单轮巡检要执行数万次 stat，拖慢 admin 巡检线程并连带推迟同线程
    后续检查点），本快照把目录扫描压到每轮一次、两检测器共用。口径与
    ``_has_recent_spec_run`` 一致：排除 admin- 前缀（``_is_admin_run_id``
    单点判定）、stem 还原不出 spec 的文件跳过；同 spec 取最大 mtime——
    「任一文件 mtime 落窗」与「最大 mtime 落窗」等价。glob 失败返回空表
    （与 _has_recent_spec_run 的 OSError → False 同 fail-open 方向）。快照
    生命周期不跨轮：由 ``AdminMonitor._round_runs_activity`` 按轮失效重建。
    """
    if project_root is None:
        return {}
    runs_dir = Path(project_root) / ".fenix" / "runs"
    try:
        files = list(runs_dir.glob("*.jsonl"))
    except OSError:
        return {}
    snapshot: dict = {}
    for p in files:
        if _is_admin_run_id(p.stem):
            continue
        spec = AdminMonitor._spec_from_run_id(p.stem)
        if not spec:
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if mtime > snapshot.get(spec, float("-inf")):
            snapshot[spec] = mtime
    return snapshot


def _runs_activity_recent(snapshot: dict, spec: str, now: float, window: float) -> bool:
    """基于快照的「窗口内有写活动」判定（_has_recent_spec_run 的等价消费形态）。

    快照未含该 spec（无该 spec 的非 admin run 文件）或最近 mtime 超窗 →
    False；判定阈值与逐文件扫描完全一致（``now - mtime < window``）。
    """
    mtime = snapshot.get(spec)
    return mtime is not None and (now - mtime) < window


def inprocess_verify_active(project_root, spec_name: str, *, window_seconds=None) -> bool:
    """daemon 进程内验证是否在飞（evo-inprocess-verify-activity-signal 1.1）。

    in-process 全量验证（daemon 线程内 asyncio.run，无 verify-<spec>-*.jsonl
    run 文件、无独立子进程）对 spec_is_undriven 原四条件全部不可见；本 helper
    补两类活性信号，OR 语义任一命中即 True：

      (a) 线程探测（主判据，零时间窗依赖）：threading.enumerate() 存在名为
          fenix-verifier-<spec> 的活线程（命名单点
          core/pm_engine/dispatch/queue.py agent_worker_thread_name）。
      (b) 进度文件 mtime（辅证）：.fenix/verify-progress/<spec>.json
          （verify_engine._write_progress 既有产物，起跑/逐场景原子写）mtime
          落入独立活动窗口（INPROCESS_VERIFY_ACTIVITY_WINDOW_SECONDS，缺省
          900s）内。MUST NOT 沿用条件①的 120s run 宽限——单场景长批间隔
          实测 4-5 分钟，120s 会把「正在长跑」误判为停滞。

    假阳性防线（design 已接受的风险）：进度文件起跑即写，run 崩溃残留的新鲜
    mtime 可能短暂豁免孤儿判定——以线程探测为主判据、mtime 仅作辅证；OR
    语义下残留风险可接受，下一窗口 mtime 超窗即恢复既有口径。线程臂无时间
    上界（零调参目标）：挂死不退出的 verifier 线程会持续豁免，回收依赖验证
    车道既有超时/升级机制。

    文件缺失 / mtime 超窗 / 线程不在 / 判定异常 → False（fail-open，与
    spec_is_undriven 既有容错同取向：豁免故障不得掩掉真阳性）。
    """
    try:
        expected = agent_worker_thread_name(spec_name, "verifier")
        for t in threading.enumerate():
            if t.name == expected and t.is_alive():
                return True
    except Exception:
        pass  # 线程臂故障不阻塞 mtime 臂（fail-open）
    if window_seconds is None:
        window_seconds = INPROCESS_VERIFY_ACTIVITY_WINDOW_SECONDS
    if project_root is None:
        return False
    progress = (
        Path(project_root) / ".fenix" / "verify-progress" / f"{spec_name}.json"
    )
    try:
        mtime = progress.stat().st_mtime
    except OSError:
        return False  # 文件缺失 / 不可达 → 不豁免
    return (time.time() - mtime) < window_seconds


def spec_is_undriven(
    project_root,
    spec_name: str,
    entry: dict,
    *,
    run_grace_seconds: float = ORPHANED_RUN_GRACE_SECONDS,
    pm_engine=None,
    runs_activity=None,
    pgrep_cache=None,
) -> bool:
    """「无驱动」判定（orphaned-state-signal R1 三条件，同一判定口径）。

    返回 True 当且仅当五者同时成立：
      ① 无活动 run 文件：该 spec 的 run 文件 mtime 均超出 run_grace_seconds
         （任意 run 前缀，含 repair-，orphaned-state-probe-calibration 1.3）；
      ② 无存活 agent 子进程：不存在 impl-<spec>- / verify-<spec>- /
         repair-<spec>- 模式进程（orphaned-state-probe-calibration 1.4）；
      ③ 无待派发：无 _cancelled_hold / start_after 未到 / 派发退避
         （_dispatch_backoff_until）未到期；
      ④ 无排队中的派发条目：pm_engine 给出时，该 spec 无待派发队列条目
         （见下）；
      ⑤ 无进程内验证在飞：daemon 线程 fenix-verifier-<spec> 不存在且
         verify-progress 进度文件 mtime 超独立窗口（inprocess_verify_active，
         evo-inprocess-verify-activity-signal 1.2）。
    任一不成立（长 run 仍在跑 / 进程仍存活 / 有意等待中 / 已入队等待槽位 /
    in-process 验证在飞）→ False——避免把正常长 run 或有意等待误判为孤儿。

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

    ⑤ 的由来（evo-inprocess-verify-activity-signal，2026-10-02 实证误报）：
    全量验证自 verify_engine 三段流水线起改为 in-process 执行（daemon 线程
    fenix-verifier-<spec> 内 asyncio.run，无 verify-<spec>-*.jsonl run 文件、
    无独立子进程），条件 ①② 对它全部不可见。'cimbar-airgap-transfer' 验证
    活跃期被本函数误判孤儿态，两条 orphaned_state 告警（09:50:36Z/10:35:37Z
    本地 17:50:36/18:35:37），recovery 出口（event_bus._recover_testing）与
    处置复位直通道（_reset_orphaned_after_disposition）先后重派，三个 23 场景
    全量批交错执行，外加 $1.289 admin 调查 run（admin-cimbar-airgap-transfer-
    1790934636）。补条件 ⑤：线程探测零调参为主判据、进度文件独立窗口 mtime
    （900s，非条件 ① 的 120s——单场景长批间隔实测 4-5 分钟）为辅。条件 ①
    保持不动：legacy 外置 verifier 车道本就被 ①② 覆盖。

    保留 `pm_engine=None`（不判定 ④）：本函数是模块级工具，既有单元测试与
    外部调用只传三参；缺省行为与引入 ④ 之前逐位一致，调用点按需注入。

    ``runs_activity`` / ``pgrep_cache``（code-review item cfa277dc36e7，可选）：
    传入每轮巡检级的 runs 目录快照（``_build_runs_activity_snapshot`` 产物）
    与 pgrep 结果缓存 dict 时，条件 ①② 改消费缓存——同轮内同 spec 只做一次
    目录 stat 与一次 pgrep 子进程派生，判定阈值不变；缺省 None 保持既有逐次
    扫描行为（event_bus 恢复出口与既有测试不受影响）。

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
    # ② 无存活 agent 子进程（pgrep_cache 传入时按轮缓存：同轮内同 spec 幂等，
    # 三个前缀的 pgrep 子进程派生不再随消费方数量放大）
    if pgrep_cache is not None and spec_name in pgrep_cache:
        alive = pgrep_cache[spec_name]
    else:
        alive = _pgrep_live_worktree(spec_name)
        if pgrep_cache is not None:
            pgrep_cache[spec_name] = alive
    if alive:
        return False
    # ① 无活动 run 文件（runs_activity 快照传入时零逐文件 stat：快照已含该
    # spec 全部非 admin run 文件的最近 mtime，窗口判定与逐文件扫描等价）
    if runs_activity is not None:
        recent = _runs_activity_recent(
            runs_activity, spec_name, time.time(), run_grace_seconds
        )
    else:
        recent = _has_recent_spec_run(
            project_root, spec_name, time.time(), run_grace_seconds
        )
    if recent:
        return False
    # ④ 无排队中的派发条目（调用方注入 pm_engine 时判定；见 docstring）
    if pm_engine is not None and _queued_for_dispatch(pm_engine, spec_name):
        return False
    # ⑤ 无进程内验证在飞（evo-inprocess-verify-activity-signal 1.2）：
    # in-process 全量验证无 run 文件/无子进程，①② 不可见——线程探测（主）
    # + verify-progress mtime 独立窗口（辅）任一命中即「有驱动」。
    if inprocess_verify_active(project_root, spec_name):
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


# 人工暂停/冻结文案的显式短语表（code-review item d5143302506e 判据③收窄）：
# 已知产生方为 freeze_spec 的 FREEZE_ERROR_PREFIX「用户指令冻结：…」与人工写入
# 的「用户指令暂停：…」（2026-08-30 误报形态），「用户指令中止」为同族前瞻。
# 裸「用户指令」子串会误命中恰好提及「用户指令」的普通错误文案（如 LLM 叙述
# 「按用户指令跳过某步骤后失败」），把该 spec 的全部自动检测/唤起路径静默关成
# 盲区；显式短语仍按子串匹配（不锚定行首）：存量 spec 文案可能把短语写在句中。
_INTENTIONAL_PAUSE_MARKERS = ("用户指令冻结", "用户指令暂停", "用户指令中止")


def _is_intentionally_paused(entry: dict) -> bool:
    """人工冻结/暂停「有意等待态」三重判据（单点判定，code-review item a1cab4f7bb6c）。

    判据与 _detect_blocked_stuck 既有实现逐字一致（fix-restart-dual-dispatch S4）：
      ① 结构化 ``frozen`` 字段——freeze_spec() 统一入口写入，首要判定，不依赖文案；
      ② error 前缀 ``'frozen:'``——Administrator 为去重/家族收敛人为冻结的
        历史 error 文案（其 blocked/悬置是有意保持的等待态，updated 不会推进）；
      ③ error 含显式暂停/冻结短语（_INTENTIONAL_PAUSE_MARKERS）——人工写入的
        「用户指令暂停/冻结：…」等价于 frozen（2026-08-30 v2-acceptance-suite
        误报），用词在暂停/冻结间漂移；按显式短语识别（code-review item
        d5143302506e 由裸「用户指令」子串收窄：裸子串误命中普通错误文案会把
        该 spec 的自动检测/唤起静默关成盲区）。

    存量 spec 可能仅以历史 error 文本表达冻结（结构化字段未迁移），全部自动
    检测/唤起路径（blocked_stuck / stuck / orphaned_state / _handle_signal 唤起前
    复查 / _force_escalate_stalled）MUST 共用本判定，消除文本回退判据的族内
    漂移——「人工冻结是有意等待态、不自动唤起」的语义在任一路径不得只认
    结构化字段。
    """
    if entry.get("frozen"):
        return True
    err = str(entry.get("error") or "")
    return err.startswith("frozen:") or any(m in err for m in _INTENTIONAL_PAUSE_MARKERS)


# [fenix-ignore:a132ca295b06] 多域拆分属架构级重构（需独立设计评审与分域迁移），超出 code-fix 单条最小修复边界，擅自拆分风险大于收益
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
        # decouple-codefix-review-lanes：审查 run stall 看门狗状态（run_id →
        # {"mtime": 产物最新 mtime, "cpu": 进程树 CPU 秒, "since": 双判据开始
        # 同时无进展的 monotonic 时间}）。任一判据有进展即整体重置（design D2
        # 双判据 + 误杀防护）；run 离开在飞即清条目。
        self._review_stall_state: dict = {}
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
        # evo-add-codefix-conn-error-cooldown 3.1：fp → 最近一次失败终态时刻
        # （epoch 秒，逐扫更新；跨日同刻复发判别的记忆事实源，容量上限
        # DAEMON_ERROR_FP_MEMORY_LIMIT）。evo-fix-crossday-recurrence-
        # fingerprint-normalization 2.1：记忆持久化到 CROSSDAY_FP_MEMORY_REL，
        # daemon 重启后加载续用；文件缺失/损坏降级为空记忆（回退两级对账：
        # tail 次新条目 → ≥24h 定向检索，_detect_crossday_recurrence）。
        self._crossday_memory_lock = threading.Lock()
        self._daemon_fp_last_failure = self._load_crossday_memory()
        # code-review item 9427d41c85ef：fixture 判定实例级 TTL 备忘。
        # _fixture_invocation_suppressed 每条信号都走一次 _is_fixture_project
        # （Registry.discover = YAML 读 + 扫描根目录级遍历）；夹具标记实践中
        # 静态，TTL 300s 内同项目只做一次真实解析（条目 (monotonic, bool)）。
        self._fixture_project_memo: dict = {}
        # evo-inflight-spec-amendment-watch 2.1：在飞修订告警指纹备忘（spec →
        # 最近一次告警指纹）。同 spec+修订提交集合不逐扫描周期重复成条；主树
        # 又落新修订 → 提交集变化 → 新指纹允许再次成条。内存态，daemon 重启后
        # 首轮可重复提醒一次（与 latest_signal 冷却互为补充，可接受）。
        self._spec_amendment_fp_alerted: dict = {}

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

    def run_once(self) -> list:
        """执行一次完整检测：识别信号 → 记录 → 节流判定 → 唤起 Administrator。

        返回本次检测到的信号列表（供测试/审计）。
        """
        if not self.enabled:
            return []

        # code-review item cfa277dc36e7：轮首失效本轮级扫描缓存——runs 目录
        # 快照（spec → 最近 mtime）与 pgrep 结果在单轮内构建/派生一次，供
        # _detect_stuck 与 _detect_orphaned_state 共用，生命周期不跨轮（惰性
        # 构建，本轮首个消费方触发时才发生 IO；半初始化实例由 _round_* 取值
        # 器的 getattr 兜底覆盖，直接调检测器的测试路径同样成立）。
        self._runs_activity_cache = None
        self._pgrep_round_cache = {}

        # 族谱爆炸信号由 pm_engine 在拦截时直接写入 store（父 SPEC 保持 bug-found，
        # 不满足 has_in_progress_specs 门控，却同样需要送达 Administrator）。
        # 该摄取在门控之前完成：_detect_family_explosion 内部直接唤起 Administrator
        # 并把源记录标记 escalated，返回仅供审计/测试（不再经 _handle_signal 节流，
        # 否则 pm_engine 刚写入的 SIGNAL 记录会被 latest_signal 误判为「已唤起」）。
        # code-review item eccaad574376：摄取段逐段 try 兜底（与本函数后半段
        # 各检查点的既有容错口径一致）——任何异常只记日志不阻断巡检。
        family_signals = []
        try:
            family_signals = self._detect_family_explosion()
        except Exception as e:
            self.logger.error("admin_monitor", f"Family-explosion intake failed: {e}")

        # code-review item eccaad574376：状态读取与规则链检测逐段 try 兜底，
        # 异常按空表降级（任何异常只记日志不阻断巡检）。
        # code-review item 45a3b8f03516：specs 读取前移——原先
        # has_in_progress_specs() 的独立 read_all 在任何 try 之外，读态异常
        # 会中断整个 run_once（本轮孤儿处置恢复、派发失败重试、告警生命周期
        # 与 code-review/regression/self-review 各检查点全部跳过）；in-progress
        # 条件改由下方同一份逐段 try 兜底的 specs 推导（status in
        # implementing/testing，与 has_in_progress_specs 同口径，单次读取）。
        try:
            specs = self.state_machine.read_all()
        except Exception as e:
            self.logger.error("admin_monitor", f"State read failed: {e}")
            specs = {}
        now = time.time()
        if not any(
            entry.get("status") in ("implementing", "testing")
            for entry in specs.values()
        ):
            # 假就绪盲区修复（improve-run-lifecycle-governance D6）：无 in-progress
            # spec 只说明没有运行态任务，MUST NOT 成为跳过整轮巡检的理由——
            # ready 滞留（假就绪）、blocked_stuck、daemon_errors 等非运行态检查
            # 仍然必须执行（2026-08-27 事故：假 ready 滞留近 1 小时无人发现）。
            self.logger.debug(
                "admin_monitor",
                "No in-progress SPECs — continuing non-running-state scans",
            )

        regular = []
        try:
            regular = self._detect(specs, now)
        except Exception as e:
            self.logger.error("admin_monitor", f"Signal detection failed: {e}")

        for signal in regular:
            try:
                delivered = bool(self._handle_signal(signal))
            except Exception as e:
                self.logger.error("admin_monitor", f"Signal handling failed: {e}")
                delivered = False
            if not delivered and signal.get("_amendment_fp_pending"):
                # code-review item 78eb37d3b06b：在飞修订指纹备忘于成条时预写，
                # 信号被 _handle_signal 守卫丢弃或唤起异常时在此回滚该条目——
                # 冷却过期后同修订提交集合仍可再次成条，不把「未送达」
                # 记成「已告警」（getattr 兜底半初始化实例，与检测侧同款形态）。
                getattr(self, "_spec_amendment_fp_alerted", {}).pop(
                    signal.get("spec"), None
                )

        # fix-admin-self-heal：孤儿处置与重启失败的兜底升级（非 per-spec 信号）
        # （code-review item eccaad574376：逐段 try 兜底，任何异常只记日志不阻断巡检）
        try:
            self._recover_orphaned_dispositions()
        except Exception as e:
            self.logger.error("admin_monitor", f"Orphaned-disposition recovery failed: {e}")
        try:
            self._detect_restart_failure(now)
        except Exception as e:
            self.logger.error("admin_monitor", f"Restart-failure detection failed: {e}")

        # admin-signal-consolidation D2：blocked 悬置 ≥2h 强制升级真人
        # （突破节流、受未处理告警约束；不重新唤起 Administrator）
        # （code-review item eccaad574376：逐段 try 兜底，任何异常只记日志不阻断巡检）
        try:
            self._force_escalate_stalled(specs, now)
        except Exception as e:
            self.logger.error("admin_monitor", f"Stalled-signal escalation failed: {e}")

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
        # decouple-codefix-review-lanes 3.2：审查 run stall 看门狗（同挂载点
        # 复用巡检节拍，不新增线程/定时器；任何异常只记日志不阻断巡检）。
        try:
            self._check_review_run_watchdog()
        except Exception as e:
            self.logger.error(
                "admin_monitor", f"Review-run stall watchdog failed: {e}"
            )
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

        守卫与自省同形：``admin.code_review.enabled``、同自然日防重、
        生效 ``run_at``（独立键 admin.code_review.run_at，缺省回退自省，
        add-code-review-run-at）未到不跑；manifest 为空则跳过（不派发空
        run）；已有 code-review run 在跑则跳过（单飞）。

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

        # aware 本地当前时刻：_parse_run_at（self_review 批① aware 化）返回
        # aware，naive now 与之比较会抛 TypeError；now_local() 与原 naive
        # 同一瞬时，now.date() 本地自然日语义不变。
        now = now_local()

        # run_at 未到不触发（add-code-review-run-at 2.1：改读独立键
        # admin.code_review.run_at——回退解析由 get_code_review_config 单源
        # 完成（缺省回退自省 run_at），此处 MUST NOT 二次解析）
        if now < _parse_run_at(cr_cfg["run_at"], now.date()):
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
                # 快照后迭代（code-review item be53fac9d762，对齐 runner 读取侧
                # 的 list(...) 快照惯例）：runner 侧并发注册/pop 改变字典大小会使
                # 直接迭代抛 RuntimeError: dictionary changed size during iteration。
                running = dict(getattr(self.agent_runner, "_running_agents", None) or {})
                if any(str(rid).startswith("code-review-") for rid in running):
                    # code-review item 68a28fa47419：此处 MUST NOT 置位本车道单飞
                    # 标志——命中的是外部（如 Dashboard 手动）启动的 run，其收尾
                    # 不经过本监视器自有 _worker 的 finally 复位点，置位后外部 run
                    # 结束标志恒为 True，周期审查在本次 daemon 生命周期内静默停摆。
                    # 外部 run 的去重已由本探测每轮重查 _running_agents 承担。
                    return {"triggered": False, "reason": "already_running_agent"}
            self._code_review_in_flight = True

        # code-review item 6cc5281326bc：置位单飞标志之后的所有语句统一纳入本
        # try——compute_window/collect_manifest（git 子进程）与
        # save_code_review_state（文件 IO）均可抛异常，此前不在任何 try 内，
        # 异常沿 run_once 逐段 try 兜底被吞但单飞标志无人复位，此后每轮检查点
        # 恒命中 already_running 提前返回，周期审查直至 daemon 重启前静默停摆
        # （与 68a28fa47419 修复的「外部 run 置位标志致车道静默停摆」同型）。
        # except 中复位单飞标志，对齐空 manifest 分支与 submit 失败分支的既有
        # 复位口径。
        try:
            # 周期审查跨窗顺延（evo-add-review-night-defer-snapshot-writeoff
            # 2.1）：派发时刻加近几轮归档 code-review run 实测时长均值得预计
            # 在飞区间，与任一夜间静默窗相交即本轮不派发——周期审查实测约 2
            # 小时、01:00 起跑落点必然压在 03:00-04:45 断窗带上（2026-10-10
            # 03:00 断窗击杀 118 分钟 run 实证），窗前顺延留待窗末后巡检自然
            # 触发。判定 MUST 先于 manifest 收集与同日防重写入（二者均有副
            # 作用：收集走 git 子进程、防重写入会使顺延当日永不跑）；命中即
            # 复位单飞标志（对齐下方空 manifest 分支口径）后返回。
            defer_note = self._code_review_night_window_defer_note()
            if defer_note is not None:
                with self._code_review_lock:
                    self._code_review_in_flight = False
                self.logger.info("admin_monitor", defer_note)
                return {
                    "triggered": False,
                    "reason": "night_quiet_window_deferred",
                }

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
                        + self._pending_writeoff_note()
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
                # code-review item 42b4a0f7ac08：排程段自带兜底——经 executor
                # 投递时本 _worker 跑在无人消费结果的 Future 里，这里抛出的异常
                # （RATELIMIT_REDISPATCH_MAX import 失败/锁操作等）原本滞留
                # Future 无任何日志，本生命周期唯一的 429 重派机会静默丢失；
                # 同步回退路径有外层 try 兜底，仅异步投递路径暴露。保持排在
                # finally（单飞复位）之后：重派 Timer 冷却可能为 0，若先排程后
                # 复位，回调会在锁内见到在途标志误判放弃。异常记 ERROR 不再上抛。
                if ratelimit_intent:
                    try:
                        self._schedule_ratelimit_redispatch(
                            manifest=manifest,
                            review_kind=review_kind,
                            window_start=window_start if review_scope == "window" else None,
                            scope=review_scope,
                            intent=ratelimit_intent,
                        )
                    except Exception as e:
                        self.logger.error(
                            "admin_monitor", f"code-review 429 重派排程异常: {e}"
                        )

            try:
                if self._code_review_executor is not None:
                    self._code_review_executor.submit(_worker)
                else:
                    # executor 不可用（测试/禁用态）：同步执行（行为不变，保逃生门）
                    _worker()
                return {"triggered": True, "ok": True, "reason": "scheduled", "date": local_today_str()}
            except Exception as e:
                # code-review item 9803d23b31dc：投递失败（executor 已 shutdown 等）
                # 回退同步执行，对齐 _invoke_administrator 的既有投递失败回退口径
                # （保逃生门）——save_code_review_state 防重已在投递前写入，此前
                # 仅复位单飞返回，当日周期审查即静默丢失（次日才重试）。_worker
                # 自身 finally 复位单飞标志；同步执行仍抛异常时由外层 except
                # 沿用既有「复位单飞+日志」口径兜底。
                self.logger.error(
                    "admin_monitor",
                    f"code-review 周期审查后台投递失败，回退同步执行: {e}",
                )
                _worker()
                return {"triggered": True, "ok": False, "reason": f"exception: {e}", "date": local_today_str()}
        except Exception as e:
            with self._code_review_lock:
                self._code_review_in_flight = False
            self.logger.error(
                "admin_monitor",
                f"code-review 周期审查异常（单飞标志已复位）: {e}",
            )
            return {"triggered": True, "ok": False, "reason": f"exception: {e}", "date": local_today_str()}

    # ── 周期审查跨窗顺延（evo-add-review-night-defer-snapshot-writeoff 2.1）──

    def _code_review_archive_duration_mean(self) -> Optional[float]:
        """归档 code-review run 实测时长均值（秒）；无有效样本返回 None。

        样本源（design D2）：``.fenix/runs/archive/code-review-*.jsonl`` 尾部
        run_metrics 行 ``duration_s``，按归档新→旧取最近
        ``NIGHT_QUIET_DURATION_SAMPLE_LIMIT``（=3，core.code_fix 单源导入，
        对齐 code-fix 同名常量的样本策略）轮均值；历史行缺字段/负值/非有限
        数值一律剔除。尾部读取按 512KB 窗（run_metrics 行落 run 收尾段，全
        量转录可达数十 MB，整读无谓）；窗内截断/损坏行跳过。归档目录缺失/
        列举或读取异常一律按无样本处理——顺延判定 fail-open 依据，MUST NOT
        因取样阻断派发主路径。
        """
        from .code_fix import NIGHT_QUIET_DURATION_SAMPLE_LIMIT

        archive_dir = Path(self.project_root) / ".fenix" / "runs" / "archive"
        samples: list = []
        try:
            candidates = sorted(
                archive_dir.glob("code-review-*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for path in candidates:
                if len(samples) >= NIGHT_QUIET_DURATION_SAMPLE_LIMIT:
                    break
                try:
                    with path.open(encoding="utf-8", errors="replace") as fh:
                        fh.seek(0, 2)
                        size = fh.tell()
                        fh.seek(max(0, size - 524288))
                        tail = fh.read()
                except OSError:
                    continue
                last: dict = {}
                for line in tail.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if (isinstance(rec, dict)
                            and rec.get("type") == "run_metrics"):
                        last = rec
                try:
                    dur = float(last.get("duration_s"))
                except (TypeError, ValueError):
                    continue
                if dur < 0 or not math.isfinite(dur):
                    continue
                samples.append(dur)
        except Exception:  # noqa: BLE001 — 取样失败按无样本回退（fail-open）
            return None
        if not samples:
            return None
        return sum(samples) / len(samples)

    def _code_review_night_window_defer_note(self) -> Optional[str]:
        """周期审查跨窗顺延判定：顺延返回日志文案，不顺延返回 None。

        判定（design D2）：派发时刻加近几轮归档 code-review run 实测时长
        均值（``_code_review_archive_duration_mean``；无有效样本回退仅判
        派发时刻落窗）得预计在飞区间，与任一夜间静默窗相交即顺延——本轮
        不派发、不写同日防重状态，留待窗末后巡检自然触发。窗配置与解析
        复用 core.code_fix 单源（``_parse_night_quiet_windows``，键
        ``admin.code_review_fix.night_quiet_window``，与 code-fix 车道同键
        同缺省），MUST NOT 引入第二份窗配置。多窗与预计区间相交取最晚窗末
        为「下一可派发时刻」（仅日志文案，实际派发交由巡检自然到达）。与
        provider 瞬断冻结不复用：冻结态已有全局冻结闸（
        ``_night_dispatch_block_reasons``），本判定只管窗相交。

        配置读取/解析/取样异常一律按不顺延处理——观测失败 MUST NOT 阻断
        派发主路径。调用方职责（契约）：命中时 MUST NOT 写同日防重状态
        （否则顺延当日永不跑）、MUST 复位单飞标志（对齐空 manifest 分支
        口径）。
        """
        try:
            from .code_fix import (
                NIGHT_QUIET_WINDOW_DEFAULT,
                _epoch_iso,
                _local_window_end_epoch,
                _parse_night_quiet_windows,
            )

            raw = self._get_config(
                "admin.code_review_fix.night_quiet_window",
                NIGHT_QUIET_WINDOW_DEFAULT,
            )
            windows = _parse_night_quiet_windows(raw)
            if not windows:
                return None
            lt = time.localtime()
            cur = lt.tm_hour * 60 + lt.tm_min
            est = self._code_review_archive_duration_mean()
            if est is None:
                crossing = [w for w in windows if w[0] <= cur < w[1]]
                sample_note = "无实测样本，仅判派发时刻落窗"
            else:
                cur_s = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec
                # 相交判定对齐 code-fix 守卫口径：派发时刻已落窗（任一窗
                # start<=cur<end）或预计结束越过尚未开始的窗起点（严格
                # 大于——恰压线视作不相交，批次在窗起点整点前收尾）。
                crossing = [
                    w for w in windows
                    if (w[0] <= cur < w[1])
                    or (cur < w[0] and cur_s + est > w[0] * 60)
                ]
                sample_note = f"近几轮实测均时长 {est:.0f} 秒"
            if not crossing:
                return None
            cur_clock = f"{lt.tm_hour:02d}:{lt.tm_min:02d}"
            if est is None:
                span = f"{cur_clock}（派发时刻）"
            else:
                end_s = cur_s + int(est)
                span = (
                    f"{cur_clock}-"
                    f"{(end_s // 3600) % 24:02d}:{(end_s % 3600) // 60:02d}"
                )
            next_ts = _local_window_end_epoch(max(w[1] for w in crossing))
            return (
                "code-review: 预计审查区间与夜间静默窗相交，本轮顺延不派发"
                f"（预计区间 {span}，{sample_note}；窗区间 "
                f"{', '.join(w[2] for w in crossing)}；下一可派发时刻="
                f"{_epoch_iso(next_ts)}），同日防重未写、窗末后巡检自然触发"
            )
        except Exception:  # noqa: BLE001 — 判定失败按不顺延处理（fail-open）
            return None

    def _pending_writeoff_note(self) -> str:
        """pending-writeoff 锚在侧 → 完成日志追加「部分覆盖待核销」标注。

        evo-add-review-night-defer-snapshot-writeoff 3.3：error 收场抢救落账
        会写待核销锚（``.fenix/code-review/writeoff-pending.json``，见
        ``core.code_review.write_pending_writeoff``），审查完成日志两处落账
        文案读到锚即追加标注（观测走日志，不加告警、不进 dashboard 新页，
        design D4）。读取异常按无锚处理——标注缺失 MUST NOT 影响完成日志
        主路径。
        """
        try:
            from core.code_review import read_pending_writeoff

            pending = read_pending_writeoff(self.project_root)
        except Exception:  # noqa: BLE001 — 标注失败不影响完成日志主路径
            return ""
        if not pending:
            return ""
        rid = str(pending.get("run_id") or "unknown")
        return f"，部分覆盖待核销（run_id={rid}）"

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
        - 冷却到期前 MUST NOT 重派：延迟 = max(0, cooldown_until_epoch − now)；
        - cooldown_until_epoch 缺失/非法（不可解析为有限数值）时放弃排程并记
          WARNING（不计配额，按既有失败路径收场升级人工）。
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
            # code-review item 2d15a48ece2a：先解析冷却到期时刻，缺失/非法
            # （不可解析为有限数值，NaN/inf 视同非法）时放弃排程并记 WARNING
            # （按既有失败路径收场升级人工），不计配额、不排 Timer——旧写法
            # `or 0.0` 会得大负数被 max(0.0, …) 归零、Timer 立即触发，在
            # provider 限流窗口内烧掉唯一一次重派额度（重派仍 429 即按失败
            # 收场），违背「冷却到期前 MUST NOT 重派」契约。在占额前置判定，
            # 放弃路径无需回滚。
            try:
                cooldown_until_epoch = float(intent.get("cooldown_until_epoch"))
            except (TypeError, ValueError):
                cooldown_until_epoch = None
            if cooldown_until_epoch is None or not math.isfinite(cooldown_until_epoch):
                self.logger.warning(
                    "admin_monitor",
                    f"code-review 429 重派放弃：intent 无合法 "
                    f"cooldown_until_epoch（原 run {run_id}，按既有失败路径"
                    f"收场升级人工）",
                )
                return
            # 登记即占额（防并发意图重复消耗/重复排队）；消费侧若因单飞放弃
            # 不退额——防风暴优先。
            self._code_review_ratelimit_redispatches += 1
            delay = max(0.0, cooldown_until_epoch - time.time())
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

        单飞守卫：车道忙时放弃本次重派（原 run 的分片产物仍被 error 收场
        抢救落账，不因放弃而丢失）——既查本车道自有标志（新周期 run 在途），
        也探测外部（如 Dashboard 手动）启动的 code-review run（对齐
        _run_code_review_checkpoint 的 _running_agents 前缀探测；外部 run 的
        置位/复位不经过本监视器自有 _worker，自有标志检测不到）。放弃不退
        重派配额（防风暴优先，与 _schedule_ratelimit_redispatch 登记处口径
        一致）。
        """
        # ── 分片续跑：重派前把 manifest 剃成剩余文件（evo-add-code-review-
        # ratelimit-resume 3.2）── 事故基线 code-review-1790574672：270 文件级
        # 全仓审查死于 429 时原 run 已落 4 片，既有全量重跑重烧约 14 美元。剃余
        # 口径：累计覆盖（原 run 及其重派链产物 file 字段并集）对原 manifest 求
        # 补（code_review.remaining_manifest），redispatch_of 链路由 run_code_
        # review 落盘时保留。剩余为空（原 run 已全覆盖，如 429 死于收尾段）→
        # 无需重派，记日志返回；重派配额不退（防风暴优先，与登记处口径一致——
        # 空跑重派同样占用冷却与单飞）。剃余失败回退原 manifest 全量重派（既有
        # 行为，不因续跑优化引入新的失败面）。
        try:
            from core.code_review import (
                cumulative_covered_files as _cum_covered,
                remaining_manifest as _remaining_files,
            )

            covered = _cum_covered(self.project_root, original_run_id)
            shaved_manifest = _remaining_files(list(manifest), covered)
        except Exception as e:  # noqa: BLE001 — 剃余失败回退全量重派
            self.logger.warning(
                "admin_monitor",
                f"code-review 429 重派剃余失败，回退原 manifest 全量重派: {e}",
            )
            shaved_manifest = list(manifest)
        if not shaved_manifest:
            # 触发即摘句柄（code-review 5e447f90226d）：早退分支同样在锁内复位
            # 句柄，否则 self._code_review_redispatch_timer 永久指向已触发的
            # Timer，后续新意图恒命中「已有待发重派 Timer」的误导性跳过路径，
            # 重派通道静默失效。此刻句柄仍指向本 Timer（其他路径改写前都先判
            # is not None），锁内复位不会误清新排程的句柄。
            with self._code_review_lock:
                self._code_review_redispatch_timer = None
            self.logger.info(
                "admin_monitor",
                f"code-review 429 重派跳过：原 run {original_run_id} 累计覆盖已"
                f"完整（{len(manifest)} 文件全部落账），无需重派（核销解锁由"
                f" maintenance_runs 收尾分支按覆盖完整性判定）",
            )
            return

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
            if self.agent_runner is not None:
                # 快照后迭代（code-review item be53fac9d762，对齐 runner 读取侧
                # 的 list(...) 快照惯例）：runner 侧并发注册/pop 改变字典大小会使
                # 直接迭代抛 RuntimeError: dictionary changed size during iteration。
                running = dict(getattr(self.agent_runner, "_running_agents", None) or {})
                if any(str(rid).startswith("code-review-") for rid in running):
                    self.logger.warning(
                        "admin_monitor",
                        f"code-review 429 重派放弃：已有外部 code-review run 在跑"
                        f"（原 run {original_run_id}）",
                    )
                    return
            self._code_review_in_flight = True

        def _worker():
            try:
                # 剃余后的 manifest 续跑（evo-add-code-review-ratelimit-resume
                # 3.2）：只跑原 run 未落账的剩余文件，redispatch_of 链路保留。
                result = self.agent_runner.run_code_review(
                    shaved_manifest,
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
                    f"（剃余续跑 {len(shaved_manifest)}/{len(manifest)} 文件）"
                    + self._pending_writeoff_note()
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

        hit = check_progress_stall(self.project_root, now_local())  # SPEC-B 批③收拢
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

    def _review_stall_minutes(self) -> int:
        """看门狗停滞阈值（分钟）：``admin.review_stall_minutes``，缺省 30。

        缺失/非法/非正整数（含 bool）一律回退 30——巡检路径 MUST NOT 因配置
        脏值中断（与 ``_stall_alert_minutes`` 同款容错口径）。
        """
        default = 30
        raw = self._get_config("admin.review_stall_minutes", default)
        if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
            return default
        return raw

    def _check_review_run_watchdog(self) -> dict:
        """审查 run stall 看门狗（decouple-codefix-review-lanes 3.1/3.2）。

        在飞审查 run 的**双判据**同时无进展持续达 ``admin.review_stall_minutes``
        （缺省 30）时自动收走：``runner.cancel_run``（既有 run 粒度取消原语，
        属主轮询环完成 terminate→grace→kill→cancelled 终态）→ run 收尾即走既有
        急救落账路径（``run_code_review`` error 收场抢救，本方法不新造落账路径）
        → AdminStore 告警留痕（单 run 去重）。

        双判据（design D2）：① 进度产物 mtime（主产物 + 全部分片最新 mtime）；
        ② run 子进程进程树 CPU 时间。任一判据有进展即整体重置计时；CPU 判据
        不可解析（进程句柄缺失/已退出）按 fail-open 不触发——宁可漏杀不可误杀，
        且无进程句柄时 cancel_run 也无从终止。run 不在飞时短路并清理状态。

        Returns: 判定结果 dict（供测试断言；巡检不消费返回值）。
        """
        from core.code_review import out_path, read_progress, shard_paths

        progress = read_progress(self.project_root)
        run_id = str(progress.get("review_id") or "")
        if not progress.get("running") or not run_id:
            # 不在飞：清状态（保留其它 run 的条目没有意义——审查单飞）
            if self._review_stall_state:
                self._review_stall_state.clear()
            return {"triggered": False, "reason": "not_running"}

        # 判据 ①：进度产物最新 mtime（分片集合经 shard_paths 唯一入口）。
        # 产物暂缺（sources 空）或 stat 失败（OSError）时沿用上一轮记录的
        # mtime（code-review item be72a1425abd）：兜底 0.0 与上一轮值（>0）
        # 必然不同，会被下方「任一判据有进展 → 整体重置计时」当进展清零——
        # run 收尾/轮转窗口内产物短暂不可读即反复重置停滞计时，看门狗在该
        # 期间形同失效；无上一轮记录才兜底 0.0（首跑产物未落盘）。
        root = self.project_root
        sources = [
            p
            for p in [*shard_paths(root, run_id), out_path(root, run_id)]
            if p.is_file()
        ]
        prev = self._review_stall_state.get(run_id)
        try:
            mtime = max(p.stat().st_mtime for p in sources) if sources else 0.0
        except OSError:
            mtime = 0.0
        if mtime == 0.0 and prev is not None:
            mtime = prev.get("mtime") or 0.0

        # 判据 ②：run 子进程进程树 CPU 时间（秒）；不可解析 fail-open
        proc = (getattr(self.agent_runner, "_running_agents", None) or {}).get(run_id)
        cpu = None
        if proc is not None:
            try:
                from core.agent_runner.maintenance_runs import (
                    agent_process_cpu_seconds,
                )

                cpu = agent_process_cpu_seconds(proc)
            except Exception:  # noqa: BLE001 — 判据读取失败按不可用处理
                cpu = None
        if cpu is None:
            self._review_stall_state.pop(run_id, None)
            return {"triggered": False, "reason": "cpu_unavailable", "run_id": run_id}

        now = time.time()
        if prev is not None and (
            mtime != prev.get("mtime") or cpu != prev.get("cpu")
        ):
            # 任一判据有进展 → 整体重置计时（误杀防护，Requirement 2）
            prev = None
        if prev is None:
            self._review_stall_state[run_id] = {
                "mtime": mtime,
                "cpu": cpu,
                "since": now,
            }
            return {"triggered": False, "reason": "baseline", "run_id": run_id}

        stalled_minutes = (now - prev["since"]) / 60.0
        threshold = self._review_stall_minutes()
        if stalled_minutes < threshold:
            return {
                "triggered": False,
                "reason": "below_threshold",
                "run_id": run_id,
                "stalled_minutes": round(stalled_minutes, 1),
                "threshold_minutes": threshold,
            }

        # 达阈值 → 取消 + 告警留痕（急救落账由 run 收尾的既有 error 收场
        # 抢救路径执行；本文档 D3：MUST NOT 新造落账路径）
        reason = (
            f"review_stall_watchdog: 审查 run 双判据停滞 {int(stalled_minutes)} 分钟"
            f"（阈值 {threshold}）：产物 mtime 冻结于 {mtime}、进程树 CPU 冻结于 "
            f"{cpu}s——自动取消并走既有急救落账（09-24 ocr scan 僵死 2h20m 同型）"
        )
        cancelled = {"status": "skipped", "base_run_id": run_id}
        cancel_fn = getattr(self.agent_runner, "cancel_run", None)
        if callable(cancel_fn):
            try:
                cancelled = cancel_fn(run_id, reason=reason, by="review_stall_watchdog")
            except Exception as e:  # noqa: BLE001 — 取消失败仍落告警留痕
                self.logger.error(
                    "admin_monitor", f"review stall watchdog cancel_run failed: {e}"
                )
                cancelled = {"status": "error", "error": str(e)}
        else:
            cancelled = {"status": "no_agent_runner"}
        self._review_stall_state.pop(run_id, None)

        dedup_key = f"review-stall-watchdog-{run_id}"

        def _inflight(rec: dict) -> bool:
            return (
                rec.get("kind") == ESCALATION
                and rec.get("signal_type") == "review_stall_watchdog"
                and rec.get("dedup_key") == dedup_key
            )

        self.store.append_if_absent(
            {
                "kind": ESCALATION,
                "signal_type": "review_stall_watchdog",
                "dedup_key": dedup_key,
                "spec": None,
                "severity": "major",
                "description": (
                    f"审查 run 看门狗自动取消：{run_id} 产物 mtime 与进程 CPU 双判据"
                    f"同时无进展 {int(stalled_minutes)} 分钟（阈值 {threshold}）——"
                    f"已登记取消旗标，收尾急救落账自动执行"
                ),
                "evidence": (
                    f"run_id={run_id}; mtime={mtime}; cpu_seconds={cpu}; "
                    f"stalled_minutes={int(stalled_minutes)}; "
                    f"cancel={cancelled}"
                ),
                "action_taken": (
                    "cancel_run(by=review_stall_watchdog) + AdminStore 告警"
                    f"（去重键 {dedup_key}，单 run 至多一条）"
                ),
                "recommended_action": (
                    "无需人工干预：产物已由急救落账路径入账（对照 error 收场抢救"
                    "日志 inserted/updated；读数为 0 时复核 .fenix/code-review/"
                    "out-<run_id>.jsonl 是否滞留未转化 findings）。判为误杀时在"
                    "「代码审查」分面手动重审一次即可"
                ),
            },
            _inflight,
        )
        self.logger.warning("admin_monitor", f"review stall watchdog triggered: {reason}")
        return {
            "triggered": True,
            "run_id": run_id,
            "stalled_minutes": round(stalled_minutes, 1),
            "threshold_minutes": threshold,
            "cancel": cancelled,
        }

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
        # aware 本地当前时刻：_parse_run_at（self_review 批① aware 化）返回
        # aware，naive now 与之比较会抛 TypeError；now_local() 与原 naive
        # 同一瞬时，now.date() 本地自然日语义不变。
        now = now_local()

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
                # 快照后迭代（code-review item be53fac9d762，对齐 runner 读取侧
                # 的 list(...) 快照惯例）：runner 侧并发注册/pop 改变字典大小会使
                # 直接迭代抛 RuntimeError: dictionary changed size during iteration。
                running = dict(getattr(self.agent_runner, "_running_agents", None) or {})
                if any(str(rid).startswith("regression-") for rid in running):
                    # code-review item 68a28fa47419（对齐 code-review 车道同款）：
                    # 此处 MUST NOT 置位本车道单飞标志——命中的是外部启动的
                    # regression run，其收尾不经过本监视器自有 _worker 的 finally
                    # 复位点，置位后外部 run 结束标志恒为 True，周期回归在本次
                    # daemon 生命周期内静默停摆。外部 run 去重已由本探测每轮重查
                    # _running_agents 承担。
                    return {"triggered": False, "reason": "already_running_agent"}
            self._regression_in_flight = True

        # regression item 6cc5281326bc：置位单飞标志之后的所有语句统一纳入本
        # try——load_verify_contract/save_state（文件 IO）均可抛异常，此前不在
        # 任何 try 内，异常沿 run_once 逐段 try 兜底被吞但单飞标志无人复位，
        # 此后每轮检查点恒命中 already_running 提前返回，周期回归直至 daemon
        # 重启前静默停摆（同 code-review 车道 6cc5281326bc）。except 中复位
        # 单飞标志，对齐未配置分支与 submit 失败分支的既有复位口径。
        try:
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
                # code-review item 9803d23b31dc：投递失败（executor 已 shutdown 等）
                # 回退同步执行，对齐 _invoke_administrator 的既有投递失败回退口径
                # （保逃生门）——save_state 防重已在投递前写入，此前仅复位单飞
                # 返回，当日周期回归即静默丢失（次日才重试）。_worker 自身
                # finally 复位单飞标志；同步执行仍抛异常时由外层 except 沿用
                # 既有「复位单飞+日志」口径兜底。
                self.logger.error(
                    "admin_monitor",
                    f"regression 周期回归后台投递失败，回退同步执行: {e}",
                )
                _worker()
                return {"triggered": True, "ok": False, "reason": f"exception: {e}", "date": local_today_str()}
        except Exception as e:
            with self._regression_lock:
                self._regression_in_flight = False
            self.logger.error(
                "admin_monitor",
                f"regression 周期回归异常（单飞标志已复位）: {e}",
            )
            return {"triggered": True, "ok": False, "reason": f"exception: {e}", "date": local_today_str()}

    def _run_alert_lifecycle(self, specs: dict) -> int:
        """告警自动闭环扫描（add-alert-auto-resolve design D1/D3/D4）。

        判定为纯函数（alert_lifecycle.find_resolvable）：输入未闭环告警 +
        当轮 STATE.md 状态表，输出可闭环条目；写回经 AdminStore.auto_resolve
        在其排他锁内完成（不绕锁）。无未闭环告警时不做写回、无可闭环条目时
        零写回（admin_alerts.json mtime 不变）。返回实际闭环数量。

        evo-add-signal-subject-terminal-close 2.1：通道一 pending 纳入未
        handled 且属 spec 附着条件族的 kind=signal 记录（blocked_stuck 等，
        落库形态 kind=signal），与 escalation 复用同一判定与写回——此前只收
        kind=escalation，blocked_stuck 信号在主体 spec 终态/离开 blocked 后
        永不收口，台账虚报人工升级。

        daemon 启动首轮扫描（_lifecycle_backfilled=False）附带存量回填：
        无 trigger 字段的 verify_fail_escalation / blocked_stuck 告警按
        signal_type 推断 condition 走同一判定路径，resolve_note 注明
        「存量回填」。

        add-alert-self-heal-marking 3.1 双通道扩展：既有 spec 附着判定不变
        （通道一）；新通道（通道二）把全量告警（含 spec-less）与当前时刻
        注入自愈判定（alert_lifecycle.find_self_healable），产出 resolutions
        经 AdminStore.auto_self_heal 写回——spec-less 瞬态族签名安静超窗后
        标「已自愈」。两通道互斥不双重判定（find_self_healable 跳过既有
        条件在册条目）；各自 try 兜底，一段失败不阻断另一段与巡检（对齐
        同函数既有风格）。
        """
        records = self.store.read_all()
        resolved_total = 0

        # ── 通道一：既有 spec 附着条件判定 ───────────────────────────
        # evo-add-signal-subject-terminal-close 2.1：pending 过滤纳入未 handled
        # 且属 spec 附着条件族的 kind=signal 记录（blocked_stuck 等，落库形态
        # 是 kind=signal 而非 escalation，旧过滤结构性漏收），与 escalation 复用
        # 同一终态判定与 auto_resolve 写回；族判定单源 is_spec_attached_signal
        # （与判定端 kind 门同口径，签名安静族/未登记族仍不进入）。
        try:
            backfill = not self._lifecycle_backfilled
            pending = [
                r
                for r in records
                if not r.get("handled")
                and (
                    r.get("kind") == ESCALATION
                    or is_spec_attached_signal(r, backfill=backfill)
                )
            ]
            # pending 为空 = 通道一零写回（无 find_resolvable 判定与写回），
            # 直接跳过；回填标志两分支同值（code-review 3caf5598dc97）的
            # 统一置位收进本 try 块末尾（见下，code-review 5c6103677e02）。
            if pending:
                resolvable = find_resolvable(pending, specs, backfill=backfill)
                if resolvable:
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
                    resolved_total += resolved
            # 回填标志置于判定与写回成功之后（code-review item
            # 5c6103677e02）：find_resolvable/auto_resolve/写回异常路径不
            # 消耗标志，下一轮巡检仍以 backfill=True 重试一次——否则 daemon
            # 启动首轮异常即令无 trigger 字段存量条目的一次性回填在本
            # 生命周期内永久丢失。pending 为空 = 零判定零写回，同值置位
            # （3caf5598dc97 两分支同值约定不变）。
            self._lifecycle_backfilled = True
        except Exception as e:
            self.logger.warning(
                "admin_monitor", f"alert lifecycle spec 附着通道失败（跳过）: {e}"
            )

        # ── 通道二：spec-less 瞬态族自愈（add-alert-self-heal-marking）──
        try:
            healable = find_self_healable(
                records, time.time(), self._self_heal_quiet_minutes()
            )
            if healable:
                healed = self.store.auto_self_heal(healable)
                for item in healable:
                    self.logger.info(
                        "admin_monitor",
                        f"alert self-healed: id={item.get('id')} "
                        f"spec='{item.get('spec')}' — {item.get('resolve_note')}",
                    )
                if healed:
                    self.logger.warning(
                        "admin_monitor",
                        f"alert lifecycle: self-healed {healed}/{len(healable)} "
                        f"transient alert(s)（已自愈）",
                    )
                resolved_total += healed
        except Exception as e:
            self.logger.warning(
                "admin_monitor", f"alert lifecycle 自愈通道失败（跳过）: {e}"
            )
        return resolved_total

    def _self_heal_quiet_minutes(self) -> int:
        """告警自愈安静窗口（分钟，add-alert-self-heal-marking 3.2）。

        取 ``admin.self_heal_quiet_minutes``（get_admin_config 已归一：缺省
        1440、脏值回退）；此处再兜一层——缺失/bool/非 int/≤0 一律回退
        1440，巡检路径 MUST NOT 因脏值中断（与 ``_review_stall_minutes``
        同款容错口径）。
        """
        raw = self.admin_cfg.get("self_heal_quiet_minutes")
        if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
            return DEFAULT_SELF_HEAL_QUIET_MINUTES
        return raw

    # ── 检测规则 ────────────────────────────────────────────────

    def _detect(self, specs: dict, now: float) -> list:
        """运行全部检测规则，返回信号列表。"""
        signals = []
        signals.extend(self._detect_repeated_failures(now))
        signals.extend(self._detect_flapping(specs, now))
        signals.extend(self._detect_stuck(specs, now))
        signals.extend(self._detect_merge_streak(specs))
        signals.extend(self._detect_blocked_stuck(specs, now))
        signals.extend(self._detect_orphaned_state(specs, now))
        signals.extend(self._detect_spec_amendment_inflight(specs, now))
        signals.extend(self._detect_daemon_errors(now))
        signals.extend(self._detect_verify_contract_unresolved(specs))
        return signals

    def _detect_verify_contract_unresolved(self, specs: dict) -> list:
        """契约模板态前置预检（add-verify-contract-preflight 1.2）。

        fenix-init 对每个新项目写入全注释 verify.yaml 模板，而消费期对
        「文件存在但解析为 None」fail-fast、对「文件缺失」放行——两者叠加
        使每个新项目首个 spec 推进到验证段必然卡 blocked 等待自主起草。本
        检测器在 spec 尚未进入验证消费（状态 ready/implementing）时前置识别
        该模板态，写既有 ``verify_contract_missing`` 信号，把契约起草从验证
        消费点前移到实现阶段并行完成。

        语义与边界：
        - 触发窗口只取 ready/implementing：spec 进入 testing 后由消费期轻量
          自证 fail-fast（pipeline）与其信号通道负责，两段互斥不双发；
        - 项目级单例：契约是项目级产物（一个项目一份 .fenix/verify.yaml），
          既有节流按 (spec, signal_type) 判定、对不同 spec 不互斥——多 spec
          命中只产出一条信号（spec 字段取首个命中 spec），不按 spec 数量
          放大 Administrator 唤起；
        - description 注明「前置预检」与「勿复位 spec 状态」：前置触发时
          spec 可能有活跃实现 run（VALID_TRANSITIONS 允许
          IMPLEMENTING→READY），机械沿用消费期「spec 复位 ready」收尾会把
          进行中的实现打回重做、与活跃 run 收尾竞态——前置起草落位即可
          （验证消费点届时经 mtime 门直接放行）；
        - 零新机制：recommended_action 复用 SIGNAL_RECOMMENDATION 既有起草
          指引，信号写入走既有 store 通道与同 spec 节流，PREPROBE 白名单
          已含 verify_contract_missing（契约在信号在途期间被修正为可解析时
          免唤起），不新增信号类型、不新增去重机制；
        - 自身异常 fail-open（对齐巡检惯例）：预检缺陷不阻断其余检测器。
        """
        signals = []
        try:
            hits = [
                name
                for name, entry in specs.items()
                if entry.get("status") in ("ready", "implementing")
            ]
            if not hits:
                return signals
            from .verify_contract import CONTRACT_FILENAME, contract_file_unresolvable

            if not contract_file_unresolvable(self.project_root):
                return signals
            hits_desc = "、".join(
                "{}({})".format(n, specs[n].get("status")) for n in hits
            )
            signals.append(
                self._make_signal(
                    "verify_contract_missing",
                    hits[0],
                    "前置预检：验证契约仍为未裁决模板态；spec 仍在实现流程中，"
                    "起草落位即可，勿复位 spec 状态",
                    f"项目根={self.project_root}，契约路径=.fenix/"
                    f"{CONTRACT_FILENAME}；命中 spec={hits_desc}",
                )
            )
        except Exception as e:
            # fail-open：预检缺陷不得拖垮监视器（design Risks 第 3 条）
            self.logger.error(
                "admin_monitor",
                f"verify contract preflight 检测器异常（fail-open）: {e}",
            )
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
            # 人工冻结豁免（fix-restart-dual-dispatch S4）：三重判据单点化在
            # 模块级 _is_intentionally_paused（code-review item a1cab4f7bb6c）——
            # 结构化 frozen 字段是首要判定（freeze_spec() 统一入口写入，不依赖
            # 文案）；文本匹配保留为存量 spec 的兼容回退（历史 error 未迁移）。
            # 冻结豁免：Administrator 为去重/家族收敛而人为冻结的 spec（error
            # 前缀 'frozen:'），其 blocked 是有意保持的等待态，updated 不会推进
            # ——按超时唤起只会形成每轮重复误报。真实停滞仍由 stuck/
            # repeated_failures/family_explosion 等规则覆盖。
            # 用户指令暂停/冻结（2026-08-30 v2-acceptance-suite 误报）：人工直接
            # 写入的「用户指令暂停：…」「用户指令冻结：…」同样是有意等待态，
            # 等价于 frozen——按「用户指令」子串识别，双保险。
            if _is_intentionally_paused(entry):
                self.logger.debug(
                    "admin_monitor",
                    f"Skipping blocked_stuck for intentionally-paused SPEC '{name}'",
                )
                continue
            updated_str = entry.get("updated") or entry.get("created") or ""
            updated = parse_ts(updated_str)  # SPEC-B 批③收拢 parse_ts；None 同路 continue
            if updated is None:
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
        # 入口快照复用（code-review c0df5dd3dbbf）：本循环内所有记录判定
        # （含下方在飞互斥守卫）共用同一份 read_all() 快照，不再对每条候选
        # 记录经 _has_active_admin_run_for_spec → _spec_has_active_admin_run
        # 重复全库重读（O(候选×全库) → O(全库)）；循环体内的 mark_escalated /
        # skipped 留痕写库不影响快照判定（留痕记录无 admin_run_id，不参与
        # _merge_admin_runs 归并）。
        records = self.store.read_all()
        for rec in records:
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
                # evo-add-maintree-stray-wip-sweep 2.2：主树散件 WIP 信号为
                # 项目级盘点（无 spec），按「项目名=」解析——未加入则
                # spec=None → 被下方丢弃、记录落 store 后无人唤起，告警浮出
                # 目标静默落空（与三表漏登记同款落空模式）。
                "maintree_stray_wip_stale",
                # evo-stray-untracked-escalation 2.1：untracked 散件第二档
                # 升级信号同为项目级盘点（无 spec），同款「项目名=」解析——
                # 漏加则升级记录被丢弃、自动唤起静默落空（源码注释点名的
                # 同款坑，以测试钉住）。
                "maintree_untracked_stray_escalated",
                # evo-whitelist-tracked-patrol 2.1：白名单脱落信号同为项目级
                # 盘点（无 spec），同款「项目名=」解析——漏加则脱落记录被
                # 丢弃、自动唤起静默落空（同款坑，以测试钉住）。
                "whitelist_untracked",
                # code-review item b4074810e49e：无主陈旧 WIP 宽限耗尽升级
                # （code_fix._write_defer_orphan_alert 直发）记录固定 spec=None、
                # evidence 以「项目名=」开头，同为项目级记录——漏加则 spec 保持
                # None 被下方静默丢弃且未 mark_escalated（每轮巡检重复丢弃），
                # 「MUST NOT 无限期静默等待」的人工升级通道落空（注释点名的
                # 同款落空模式第 8 例；已登记 STORED_SIGNAL_TYPES 却漏配本表，
                # 以端到端测试钉住）。
                "mergeback_wip_orphan_stuck",
            ):
                # 从 evidence 提取项目名（格式: "项目名=<name>; ..."）。
                # 「项目名=」字段解析单源：core.admin_store.evidence_project
                # （原内联副本已收敛，code_fix / mergeback / settings_routes 同款）。
                spec = evidence_project(rec.get("evidence") or "") or None
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
            # 前置探测守卫（evo-signal-preprobe-handled-writeback R1/R3）：
            # 白名单内的请求型「产物存在性」信号在 mark_escalated / 唤起之前
            # 先做只读探测——诉求已被事实满足（段/文件/配置已存在）即闭环，
            # 免对已被满足的诉求白唤起一次 admin 处置 run（LLM 调用）。
            if stype in PREPROBE_SIGNAL_TYPES:
                try:
                    # spec 直传（evo-add-scenario-serve-consistency-preflight 2.1）：
                    # verify_contract_missing 的能力覆盖判定需按在途场景 kind 统计
                    satisfied = self._preprobe_signal_satisfied(stype, spec)
                except Exception as e:
                    # R4 fail-open：探测异常按原路径继续唤起，不静默吞信号
                    self.logger.warning(
                        "admin_monitor",
                        f"{stype}: 前置探测异常（{type(e).__name__}: {e}），"
                        f"按原路径继续唤起",
                        {"record_id": rec.get("id"), "spec": spec},
                    )
                else:
                    if satisfied:
                        self._close_signal_preprobed(rec, stype, spec)
                        continue
            # fix-recovery-path-blockers D2b 在飞互斥守卫（code-review item
            # 82e05894a9b0）：本方法直接 _invoke_administrator，不经 _handle_signal
            # 的「已有在飞 admin run 即跳过」守卫（同 _retry_due_dispatch_failures /
            # _recover_orphaned_dispositions 重派分支的既有豁免形态）。同 spec
            # 任意 signal_type 已有在飞/待派发的 admin run（如 env 阻塞处置正在写
            # STATE/test_scenarios.json）时再唤起，会产生与在飞处置**并行**的
            # 第二个 Administrator run 写同一批状态。为真 → 跳过本次唤起。
            # 与上方终态守卫/前提复核守卫的 mark_escalated+continue 核销范式不同，
            # 本守卫 MUST NOT mark_escalated——源记录保持未消费（写入即待唤起
            # 语义保留），在飞 run 结束后的下一巡检周期由本摄取循环自然重评
            # （再武装路径）；落点必须在 mark_escalated 之前。
            if spec and self._has_active_admin_run_for_spec(spec, records=records):
                self.logger.warning(
                    "admin_monitor",
                    f"{stype}: 已有在飞处置，跳过本次摄取唤起 '{spec}'"
                    f"— fix-recovery-path-blockers D2b"
                    f"（记录未消费，在飞 run 结束后自然重评）",
                    {"record_id": rec.get("id"), "spec": spec},
                )
                # 比照 _handle_signal D2b 路径（code-review item 64cd854cebbb）
                # 补写 result="skipped" 说明性处置留痕：无 admin_run_id，
                # _merge_admin_runs 对无 admin_run_id 的记录跳过归并，不会伪造
                # 「在飞 run」；DISPOSITION 不参与 unhandled_for 节流，不阻断
                # 重评。本路径无 _handle_signal 的冷却锚点兜重复，逐巡检周期都会
                # 重捞未 escalated 的源记录——同一源记录只补痕一次（记忆集按
                # store 记录 id 去重，getattr 惰性初始化同 _fixture_project_memo
                # 先例，兼容 __new__ 半初始化实例），后续命中仅留日志。
                memo = getattr(self, "_family_intake_mutex_skip_memo", None)
                if memo is None:
                    memo = self._family_intake_mutex_skip_memo = set()
                # 容量封顶（比照 DAEMON_ERROR_FP_MEMORY_LIMIT 姊妹 memo 惯例，
                # code-review item 2a34dfb74710）：长驻 daemon 下互斥跳过逐条
                # 累积从不淘汰会无界增长；set 无序、防重语义只需近窗口，超限
                # 整体清空即可（被清 id 最多多补一次 skipped 留痕，无正确性影响）。
                if len(memo) > DAEMON_ERROR_FP_MEMORY_LIMIT:
                    memo.clear()
                if rec.get("id") not in memo:
                    memo.add(rec.get("id"))
                    # 字段拼装/异常留痕收敛到 _persist_skipped_disposition
                    # （item 4d50570fd394）：signal_type/severity/description
                    # 均源自 rec（stype == rec.get("signal_type")），兜底形态
                    # 经显式传参原样保留，action_taken 文案不变。
                    self._persist_skipped_disposition(
                        rec,
                        (
                            "已有在飞 admin run，跳过本次摄取唤起"
                            "（fix-recovery-path-blockers D2b 互斥守卫）——"
                            "实际未派发，源记录未消费，在飞处置完成后"
                            "由摄取循环自然重评"
                        ),
                        spec=spec,
                        severity=rec.get("severity")
                        or SIGNAL_SEVERITY.get(stype, "major"),
                        description=rec.get("description")
                        or SIGNAL_RECOMMENDATION.get(stype, ""),
                        error_context={"record_id": rec.get("id"), "spec": spec},
                    )
                continue
            # code-review 9e031d3e7c7f：缺 description 的兜底文案不再用三元链
            # 硬编码——三元链仅覆盖 family_explosion/dispatch_stalled/
            # inconclusive_loop，其余存储型信号（mergeback_wip_overlap/
            # stash_pop_conflict/verify_uniform_failure 等）会误落
            # 「AI 起草验证契约请求（UI 手动触发）」文案，与信号语义完全不符。
            # 改按 SIGNAL_RECOMMENDATION 表推导；表外类型用中性兜底。
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

    def _inflight_scenario_kinds(self, spec: str | None) -> set[str]:
        """在途场景 kind 集按执行 kind 原样统计（evo-add-scenario-serve-consistency-preflight 2.1）。

        读 ``verify-progress/<spec>/test_scenarios.json``，口径与验证执行期
        serving.py:960 完全一致（``str(sc.get("kind", "web"))``，缺失 kind
        缺省 web）。文件缺失/不可解析/根非数组 → 空集（调用方退化为 serve/
        start 存在性判定）。只读探测：任何异常按空集处理，不落盘不抛出。
        """
        if not spec:
            return set()
        path = (
            Path(self.project_root) / ".fenix" / "verify-progress" / str(spec)
            / "test_scenarios.json"
        )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return set()
            return {str(sc.get("kind", "web")) for sc in data if isinstance(sc, dict)}
        except Exception:  # noqa: BLE001 — 只读探测，缺失/损坏一律按空集
            return set()

    def _preprobe_signal_satisfied(self, stype: str, spec: str | None = None) -> bool:
        """只读探测：PREPROBE_SIGNAL_TYPES 内请求型信号的诉求是否已被满足。

        evo-signal-preprobe-handled-writeback R2：全部谓词只读——仅检查目标
        产物/配置的存在性，不写项目文件、不触发构建或网络访问。探测谓词与
        诉求满足是同一事实（段/文件/配置已存在），语义等价故可免唤起。
        返回 False = 诉求未满足（调用方照常唤起）；异常由调用方 fail-open。

        evo-add-scenario-serve-consistency-preflight 2.1：verify_contract_missing
        的满足判定从「契约可解析」收紧为「serve 段存在或 commands.start 非占位
        （OR），且能力可覆盖在途场景 kind 需求」——2026-10-10 事故形态：契约
        可解析但无 serve 能力，三条在途信号被批量 pre-probe 错误闭环。能力缺口
        未补齐 → False，信号保持 open 走正常唤起。``spec`` 形参承载在途场景
        kind 统计的定位（调用方持 rec/spec 直传；缺省 None 时 kind 集按空集
        退化，判定同文件缺失形态）。
        """
        if stype in ("verify_regression_missing", "verify_contract_missing"):
            # 复用契约装载做存在性判断（缺文件/解析失败返回 None，本身不落盘、
            # 不执行脚本）；logger 传 None 防测试替身缺方法——装载器的 warning
            # 仅提示性，探测路径不需要它。
            from .verify_contract import load_verify_contract

            contract = load_verify_contract(self.project_root, None)
            if contract is None:
                return False
            if stype == "verify_regression_missing":
                # 共用分支语义不变：regression 段存在性（缺段 regression=None）
                return contract.regression is not None
            # ── verify_contract_missing：serve/start 能力覆盖判定（本 SPEC）──
            from core.verify_engine.scenario_static_check import start_fallback_valid

            kinds = self._inflight_scenario_kinds(spec)
            if kinds and kinds <= {"cli"}:
                # 纯 cli 在途场景集：执行期为无实例形态（serving.py 纯 cli 白名单，
                # serve/ready 全省），不消费 serve/start 能力——契约可解析即诉求
                # 满足（proposal 兜底条款：纯 cli + 无 serve 契约维持合法）。
                return True
            # api/web 在途（或 kind 集空 = 文件缺失/不可解析，退化为存在性判定）：
            # serve 段存在或 commands.start 非占位（OR，口径同 serving.py:1098-1099
            # 哨兵）——二者任一有效即执行期可兜底，能力缺口未补齐不 auto-resolve。
            start_cmd = str(self._get_config("commands.start", "") or "")
            return contract.serve is not None or start_fallback_valid(start_cmd)
        if stype == "build_artifact_paths_missing":
            paths = self._get_config("worktree.build_artifact_paths", None)
            if paths:
                return True
            # 「确无产物」亦属已裁决（SIGNAL_RECOMMENDATION 明确不得用路径
            # 留空冒充已裁决——has_build_artifacts=false 是唯一合法结案形态）
            return self._get_config("worktree.has_build_artifacts", None) is False
        return False

    def _close_signal_preprobed(self, rec: dict, stype: str, spec: str) -> None:
        """前置探测通过即闭环（evo-signal-preprobe-handled-writeback R3/R6）。

        mark_signal_handled（handled=true）+ 同步 mark_escalated——摄取过滤
        只看 escalated，缺此步记录下一 tick 会被重捞、每周期重复探测并重复
        追加留痕；与既有终态守卫/前提复核守卫 mark_escalated+continue 同范式。
        再追加 result=resolved 处置留痕（无 admin_run_id——_merge_admin_runs
        对无 admin_run_id 的记录跳过归并，不会伪造「在飞 run」；先例同冷却
        跳过留痕）。留痕失败不阻断闭环本身（handled/escalated 已落）。
        """
        handled = self.store.mark_signal_handled(rec.get("id"))
        escalated = self.store.mark_escalated(rec.get("id"))
        try:
            self.store.append(
                {
                    "kind": DISPOSITION,
                    "signal_type": stype,
                    "spec": spec,
                    "severity": rec.get("severity")
                    or SIGNAL_SEVERITY.get(stype, "major"),
                    "description": rec.get("description")
                    or SIGNAL_RECOMMENDATION.get(stype, ""),
                    "action_taken": (
                        "pre-probe auto-resolve：前置探测通过、诉求已满足、免唤起"
                        "（evo-signal-preprobe-handled-writeback）"
                    ),
                    "result": "resolved",
                }
            )
        except Exception as e:
            self.logger.error(
                "admin_monitor",
                f"{stype}: 前置探测闭环留痕写入失败（id={rec.get('id')}）：{e}",
                {"record_id": rec.get("id"), "spec": spec},
            )
        self.logger.info(
            "admin_monitor",
            f"{stype}: 前置探测通过、诉求已满足、免唤起"
            f"（handled={'ok' if handled else '未命中'}，"
            f"escalated={'ok' if escalated else '未命中'}）",
            {"record_id": rec.get("id"), "spec": spec},
        )

    def _detect_repeated_failures(self, now: float) -> list:
        """窗口内同 spec 失败 run ≥ 阈值。

        只扫描 .fenix/runs 统计失败 run，不依赖当轮状态表（specs）。
        """
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
            # code-review item f67ba8199742：历史文件被手工编辑或旧版本格式
            # 残留时元素可能为标量/dict，直接取 c[0]/c[1] 会 TypeError 并中断
            # 当轮全部信号检测——形状不合法（非二元 list/tuple、时间戳非
            # 数值，或 code-review f9814702b128 补的状态值非字符串——下方
            # seq 的 join 对非 str 元素同样 TypeError）的条目跳过。
            in_window = [
                c
                for c in changes
                if isinstance(c, (list, tuple))
                and len(c) == 2
                and isinstance(c[0], (int, float))
                and isinstance(c[1], str)
                and c[0] >= cutoff
            ]
            if len(in_window) < 2:
                continue
            # code-review 4fb31d5c2719：changes 条目本身即一次切换事件
            # （_update_history 仅在状态变化时追加，首见建档不追加），
            # 切换次数直接按窗口内条目数计；原 len-1 为差一错误，
            # 实际需 4 次切换才达阈值 3，比宣称灵敏度低一档。
            transitions = len(in_window)
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
        threshold_minutes = self._cfg_float(
            "stuck_threshold_minutes", DEFAULT_STUCK_THRESHOLD_MINUTES
        )
        grace_minutes = max(STUCK_GRACE_MINUTES, self.interval_minutes * 2)
        silence_minutes = self._cfg_float("stuck_silence_minutes", 120)
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
            # 人工冻结/暂停豁免（code-review item a1cab4f7bb6c）：有意等待态
            # （结构化 frozen 字段 / 历史 error 文本 'frozen:' 前缀 / 「用户指令」
            # 子串，三重判据单点 _is_intentionally_paused）不产生 stuck 信号、
            # 不自动升级 Administrator，与 _detect_blocked_stuck 同判据——此前本
            # 路径完全不检查冻结，legacy 文本冻结的 implementing/testing spec 会
            # 被持续判 stuck 并自动唤起。
            if _is_intentionally_paused(entry):
                self.logger.debug(
                    "admin_monitor",
                    f"Skipping stuck for intentionally-paused SPEC '{name}'",
                )
                continue
            # 取消保持豁免（fix-cancel-holdstate-recovery D5）：人工取消的
            # hold spec 是有意等待态，不产生 stuck 信号、不自动升级
            # Administrator（自动升级可能自行复位，破坏「我来决定何时重派」
            # 的人工决策）。唯一出路是显式复位（update_spec 携带 status）。
            if entry.get("_cancelled_hold"):
                continue
            updated_str = entry.get("updated") or entry.get("created") or ""
            updated = parse_ts(updated_str)  # SPEC-B 批③收拢 parse_ts；None 同路 continue
            if updated is None:
                continue
            elapsed_minutes = (now - updated.timestamp()) / 60
            if elapsed_minutes <= threshold_minutes:
                continue
            # D1 进程存活反证：run_id → spec 归属用 _spec_from_run_id
            # （本模块既有方法，正则 -(?:a|r)\d+ 同时覆盖 attempt 与 -r<n> 瞬态
            # 重试后缀）。run_spec_part（run_files.py）现已经
            # strip_run_id_suffixes（RUN_ID_SUFFIX_RE = (-(?:a|r)\d+)+$）与本方法
            # 同口径剥除 -a<n>/-r<n>（fix-robustness-edge-cases 1.0/1.2），两者
            # 可互换；本处沿用 _spec_from_run_id 仅因其是既有实现且被测试直接
            # 覆盖，非因 run_spec_part 缺陷（旧注释「只剥离 -a\d+」已失效）。
            if running_ids is not None and any(
                self._spec_from_run_id(rid) == name for rid in running_ids
            ):
                self.logger.debug(
                    "admin_monitor",
                    f"Skipping stuck for '{name}': alive run process(es) registered",
                )
                continue
            # 有进度豁免改消费每轮 runs 快照（code-review item cfa277dc36e7，
            # 与 _detect_orphaned_state 共用同一次 glob+stat，判定阈值不变）
            if _runs_activity_recent(
                self._round_runs_activity(), name, now, grace_minutes * 60
            ):
                continue
            # 已入队等待并发槽的豁免（code-review item 8400e0b92e68，与
            # _detect_orphaned_state 2026-09-18 修复的条件④同口径）：testing 态
            # verifier 经处置直通道入队后可在队列中等待并发槽数十分钟（队列老化
            # 最坏 50 分钟 + 在飞 run 剩余时长），期间 run 文件无写活动、无存活
            # 进程，上述守卫链全不豁免 → stuck 照发唤起 Administrator 空转；同
            # 场景 orphaned_state 因 elapsed > stuck 阈值主动让位（hand-off），
            # 两路都不豁免时只剩误报路径。pm_engine 为 None（测试替身/独立组件）
            # 时不判本条件，行为与修复前一致。
            if self.pm_engine is not None and _queued_for_dispatch(self.pm_engine, name):
                self.logger.debug(
                    "admin_monitor",
                    f"Skipping stuck for '{name}': queued for dispatch "
                    f"(waiting for concurrency slot)",
                )
                continue
            # D3 处置后静默期：最近一条成功处置距 now < silence 窗口 → 跳过。
            # result=escalated（升级人工）不匹配 resolved/partially-resolved，
            # 天然不触发静默——人工处置是唯一出路，不得被静默吞掉。
            if silence_minutes > 0:
                disp = self.store.latest_resolved_disposition(name, "stuck")
                if disp is not None:
                    disp_created_str = disp.get("created") or ""
                    disp_created = parse_ts(disp_created_str)  # SPEC-B 批③收拢
                    disp_age_minutes = (
                        (now - disp_created.timestamp()) / 60
                        if disp_created is not None
                        else None
                    )
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
            # 人工冻结豁免：冻结即「等待人工」的显式表达（与 blocked_stuck 同款
            # 三重判据，单点 _is_intentionally_paused，code-review item
            # a1cab4f7bb6c——存量 spec 可能仅以历史 error 文本表达冻结，
            # 结构化字段未迁移时同样豁免）
            if _is_intentionally_paused(entry):
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
            # orphaned_state_threshold_minutes（缺省 15 分钟，即常量
            # DEFAULT_ORPHANED_STATE_THRESHOLD_MINUTES）即复发一次告警，且
            # 处置侧对该载体无正确出口（复位 ready 会清空待合并标记、白废已完成的
            # 实现；复位 testing 会把未合并分支的 committed 态当合并态直通验证）、
            # 自动复位 resolve_env_blocked_reset_path 亦因其非 blocked 而不触发，
            # 只能反复空转升级人工。
            # 实证：'evo-merge-back-wip-overlap-gate-575976'（前任 admin 于
            # 2026-09-17T22:59:31Z 置入该载体）在约 8 分钟后的 23:07:30Z 即被本
            # 巡检判为「无驱动」唤起 Administrator 空转——该 8 分钟是实测时间差
            # （elapsed 自 updated 字段起算，与置入时刻不必重合），并非阈值口径，
            # 判停阈值以上述缺省 15 分钟为准。
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
                # 等待起点解析（code-review 4242f060d0e9）：first_at 缺失/非法
                # 时改用 entry 的 updated/created 时间戳兜底作等待起点近似，
                # 不再回退 now——回退 now 使窗口超限判据 (now-first_at)/60 恒
                # 为 0，若 _merge_retry_count 亦为 0/缺失（手工编辑 STATE.md、
                # 标志与时间戳解耦的异常残留态），orphaned_state 对该 spec 在
                # 标志存续期间永久豁免（漏报方向，与本文件头「宁多唤起一次也
                # 不掩真阳性」取向相反）。updated/created 亦不可解析即起点
                # 不可考：不豁免、照常探测（保守方向；探测段随后对不可解析
                # 时间戳自会跳过，不产生新风险）。
                _wip_first = entry.get("_merge_retry_first_at")
                _wip_first_f = None
                try:
                    _wip_first_f = float(_wip_first) if _wip_first else None
                except (TypeError, ValueError):
                    _wip_first_f = None
                if _wip_first_f is None:
                    for _wip_ts_key in ("updated", "created"):
                        _wip_dt = parse_ts(entry.get(_wip_ts_key))
                        if _wip_dt is not None:
                            _wip_first_f = _wip_dt.timestamp()
                            break
                _wip_over = _wip_first_f is not None and (
                    (now - _wip_first_f) / 60.0 >= WIP_DEFER_WINDOW_MINUTES
                    or _wip_count >= WIP_DEFER_MAX_ROUNDS
                )
                if _wip_first_f is not None and not _wip_over:
                    self.logger.debug(
                        "admin_monitor",
                        f"跳过 orphaned_state 探测：'{name}' 为 WIP 延迟合回等待"
                        f"载体（_wip_gate_deferred=True，{_wip_count} 轮，"
                        f"周期消费者自动 merge-only 重试中；超限后本豁免自动失效）",
                    )
                    continue
            updated_str = entry.get("updated") or entry.get("created") or ""
            updated = parse_ts(updated_str)  # SPEC-B 批③收拢 parse_ts；None 同路 continue
            if updated is None:
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
            stuck_threshold = self._cfg_float(
                "stuck_threshold_minutes", DEFAULT_STUCK_THRESHOLD_MINUTES
            )
            if stuck_threshold > 0 and elapsed_minutes > stuck_threshold:
                continue
            # 注入 pm_engine（2026-09-18 修复）：条件 ④「无排队中的派发条目」——
            # 处置直通道 `transition_gate(testing) + verifier 入队` 后条目可在队列
            # 里等并发槽数十分钟，缺此判定则每轮巡检必判「无驱动」并唤起
            # Administrator（本 SPEC 07:55/08:07/08:30 三连误报实证）。pm_engine
            # 为 None（测试替身/独立组件）时不判 ④，行为与修复前一致。
            # 无驱动判定注入每轮 runs 快照与 pgrep 缓存（code-review item
            # cfa277dc36e7）：目录扫描与子进程派生在单轮内各做一次，与
            # _detect_stuck 共用；缺省 None 形态（event_bus/既有测试）行为不变。
            if not spec_is_undriven(
                self.project_root,
                name,
                entry,
                pm_engine=self.pm_engine,
                runs_activity=self._round_runs_activity(),
                pgrep_cache=self._round_pgrep_cache(),
            ):
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
                    # code-review item 6afca7da6f16：复用上方 _cfg_float 容错读出的
                    # stuck_threshold（裸 int() 直读 admin_cfg 会在脏配置如 "160m"
                    # 下抛 ValueError 中断整轮检测）。
                    f"（stuck 阈值 {int(stuck_threshold)}"
                    " 分钟远高于此，本信号先于 stuck 捕获）",
                )
            )
        return signals

    def _detect_spec_amendment_inflight(self, specs: dict, now: float) -> list:
        """主树 spec 目录在飞修订周期探测（evo-inflight-spec-amendment-watch 2.1）。

        对有活跃实现 run 的 spec（implementing + 分支锚点在案 + run 文件写活动
        或 worktree agent 进程存活），检测 spec/changes/<spec>/ 相对 merge-base
        在主树出现的新已提交修订——与 merge-back 主链同条件（同一模块级判定
        ``core.worktree_manager.mergeback.detect_spec_amended_inflight``，延迟
        导入防装载环：admin_monitor ← pm_engine ← worktree_manager 顶层互导入
        环；命中路径低频，函数级导入无热路径开销）。命中发 spec_amendment_inflight
        信号，把发现时刻从 merge 时刻提前到修订落地后的一个扫描周期；结局不变
        （相撞仍由预演检出按 rehearsed 链路转 repair，本信号只做早期反馈）。

        去重（2.1）：以 spec+修订提交集合为告警指纹（``spec_amendment_fingerprint``）
        ——同指纹不重复成条（不逐扫描周期轰炸）；主树又落新修订 → 提交集变化 →
        新指纹允许再次成条。``_throttled``（latest_signal 冷却 + unhandled，
        _handle_signal 处）依旧生效，本去重是其上的指纹级补口（orphaned_state
        同款节流语义 + 本 SPEC 要求的指纹维度）。

        静默跳过（关键约束）：run 不在飞（状态非 implementing / 无分支锚点 /
        无 run 写活动且无存活进程）→ 不检测；分支不存在（merge-base 失败/已
        清理）→ 模块级判定返回空列表；检测命令失败/超时同路——均不报错、
        不产信号。分支名取自 spec 记录的 branch 锚点（run/spec 记录为准，
        不自行猜测命名规则）。
        """
        signals = []
        for name, entry in specs.items():
            if entry.get("status") != "implementing":
                continue
            branch = entry.get("branch")
            if not branch or not isinstance(branch, str):
                continue
            # run 在飞判定：run 文件写活动在宽限窗内，或 worktree agent 进程
            # 存活（长工具调用窗口内 run 文件可数分钟不落笔，进程判据兜住——
            # 与 spec_is_undriven 的 ①② 条同源判据，口径不漂移）。判定消费每轮
            # runs 快照与 pgrep 缓存（code-review item 6937d0f31901，与
            # _detect_orphaned_state 同款消费形态）：目录 glob+stat 与 pgrep
            # 子进程派生同轮内与 _detect_stuck/_detect_orphaned_state 共用，
            # 不再逐 spec 重复全量扫描；pgrep 仍惰性派生（run 判据命中即免），
            # 命中缓存后同轮同 spec 幂等（spec_is_undriven 同款写法）。
            if not _runs_activity_recent(
                self._round_runs_activity(), name, now, ORPHANED_RUN_GRACE_SECONDS
            ):
                pgrep_cache = self._round_pgrep_cache()
                if name in pgrep_cache:
                    alive = pgrep_cache[name]
                else:
                    alive = _pgrep_live_worktree(name)
                    pgrep_cache[name] = alive
                if not alive:
                    continue
            try:
                from core.worktree_manager.mergeback import (
                    detect_spec_amended_inflight,
                    spec_amendment_fingerprint,
                )

                commits = detect_spec_amended_inflight(self.project_root, branch, name)
            except Exception as e:
                self.logger.warning(
                    "admin_monitor",
                    f"spec_amendment_inflight 检测异常 '{name}'（静默跳过）: "
                    f"{type(e).__name__}: {e}",
                )
                continue
            if not commits:
                continue
            fp = spec_amendment_fingerprint(name, commits)
            seen = getattr(self, "_spec_amendment_fp_alerted", None)
            if seen is None:
                # 半初始化实例（测试用 __new__ 绕过 __init__）兜底，与
                # _fixture_invocation_suppressed 同款 getattr 形态。
                seen = self._spec_amendment_fp_alerted = {}
            if seen.get(name) == fp:
                continue
            seen[name] = fp
            signal = self._make_signal(
                "spec_amendment_inflight",
                name,
                (
                    f"'{name}' 实现分支在飞期间，主树 spec/changes/{name}/ 出现 "
                    f"{len(commits)} 个新已提交修订（{', '.join(commits)}）——与分支 "
                    f"'{branch}' 对同一 spec 目录的改动存在 merge-back 相撞风险"
                    f"（现行三道闸门只覆盖未提交改动）。结局不变：相撞仍由预演"
                    f"检出并按 rehearsed 链路转 repair。"
                ),
                (
                    f"项目名={self.project_root.name}; spec={name}; "
                    f"branch={branch}; amended_commits={commits}; 指纹={fp}"
                ),
            )
            # code-review item 78eb37d3b06b：成条 ≠ 送达。指纹备忘仍于成条时
            # 预写（同指纹去重在本方法内闭环），但信号还要经 run_once 的
            # _handle_signal 守卫链（节流/冻结/夹具抑制/在飞互斥/落库拒写），
            # 任一命中即丢弃本次唤起——信号携带 ``_amendment_fp_pending``，
            # 由 run_once 在未送达时回滚备忘，冷却过期后同修订提交集合仍可
            # 再次成条（否则告警未送达却被记为已告警，漏报）；送达成功则
            # 备忘照常保留。
            signal["_amendment_fp_pending"] = fp
            signals.append(signal)
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
        # 1.1：逐指纹最近一次 ERROR 原文（日志时序序逐条覆盖 → 末条即最近），
        # 升级时经 _format_error_excerpt 附入信号 evidence（归属提取基底）。
        last_err: dict = {}
        for ts, component, message in self._read_tail_error_entries(log_file):
            fp = _error_fingerprint(component, message)
            by_fp.setdefault(fp, []).append(ts)
            last_err[fp] = (component, message)

        cooldown = DAEMON_ERROR_RESTART_COOLDOWN_MINUTES * 60
        # __new__ 直构（单测）无 _started_at：按「刚启动」处理（冷却窗生效），
        # 与真实 daemon 启动后的首扫行为一致
        in_restart_window = (now - getattr(self, "_started_at", now)) < cooldown

        escalating = []  # [(fp, count, last_str, missing_ts, crossday, excerpt)]
        # 跨日同刻复发判别（evo-add-codefix-conn-error-cooldown 3.1，D6）：
        # 先于逐指纹升级判定独立成判（记忆更新独立于升级与否），命中者绕过
        # 已知指纹冷却窗。
        crossday = self._detect_crossday_recurrence(by_fp)
        for fp, stamps in by_fp.items():
            cd = crossday.get(fp)
            in_window = [t for t in stamps if t is None or (now - window <= t <= now)]
            # 升级第二维度（D6）：跨日同刻复发单次在窗也升级——既有「≥2 次/
            # 10 分钟窗」判定保留为第一维度（cd=None 时语义不变）。
            if cd is None and len(in_window) < DAEMON_ERROR_THRESHOLD:
                continue
            ts_ok = sorted(t for t in in_window if t is not None)
            if cd is None and len(ts_ok) >= 2 and (ts_ok[-1] - ts_ok[-2]) > max_gap:
                continue
            # 已知指纹对账仅服务冷却窗分支（known 只被 known and
            # in_restart_window 消费）——冷却窗关闭后（长驻 daemon 的常态）
            # 不再为每个达阈指纹做全 store 扫描（code-review item e681493f4102）。
            # 跨日同刻复发（cd 命中）不受该冷却压制（3.1），无需对账。
            if not in_restart_window or cd is not None:
                known, source = False, ""
            else:
                known, source = self._daemon_fp_known(fp)
            if known and in_restart_window and cd is None:
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
                from_epoch(last_ts).isoformat() if last_ts else "无可用时间戳"
            )
            missing_ts = sum(1 for t in in_window if t is None)
            # 六元组末位（1.1）：最近一次同指纹 ERROR 原文摘录，随信号构造
            # 附入 evidence（_make_daemon_error_signal / _merged 消费）。
            escalating.append((
                fp, count, last_str, missing_ts, cd,
                _format_error_excerpt(*last_err[fp]),
            ))

        if not escalating:
            return []
        # 记录指纹上次唤起时间戳（3.1「生命周期内用内存时间戳」）
        for fp, *_ in escalating:
            self._daemon_fp_escalated_at[fp] = now
        # 容量上限（code-review item e6516ce88dc9）：与姊妹记忆
        # _daemon_fp_last_failure 同款封顶（DAEMON_ERROR_FP_MEMORY_LIMIT，超限
        # 按插入序淘汰最早一半）——本 dict 此前任何路径都不淘汰，长驻 daemon
        # 遇大量不同骨架的瞬时错误时单调增长（实例内存防无界增长，与跨日记忆
        # 治理口径一致）；「已知指纹」判定（_daemon_fp_known 成员查询）语义
        # 不变，被淘汰的老指纹冷却对账回落 store 既有记录路径（fail-open：
        # 最坏重启冷却窗内多召唤一次）。
        escalated_at = self._daemon_fp_escalated_at
        if len(escalated_at) > DAEMON_ERROR_FP_MEMORY_LIMIT:
            for k in list(escalated_at)[: DAEMON_ERROR_FP_MEMORY_LIMIT // 2]:
                escalated_at.pop(k, None)
        if len(escalating) == 1:
            return [self._make_daemon_error_signal(*escalating[0])]
        # 同轮孪生/成对指纹合并（3.2）：一条召唤信号、一次 Administrator run
        return [self._make_daemon_error_signal_merged(escalating)]

    def _detect_crossday_recurrence(self, by_fp: dict) -> dict:
        """跨日同刻复发判别（evo-add-codefix-conn-error-cooldown 3.1，design D6）。

        保留每指纹最近一次失败终态时刻（记忆 ``_daemon_fp_last_failure``，逐扫
        更新并持久化到 CROSSDAY_FP_MEMORY_REL——evo-fix-crossday-recurrence-
        fingerprint-normalization 2.1，daemon 重启后由 __init__ 加载续用）；新
        失败与上次失败终态时刻跨日差在 24h±5 分钟内即判定跨日同刻复发，返回
        ``{fp: (prev_ts, last_ts)}``（信号构造消费，升级文案与 evidence 注明
        前次时刻）。

        恰发一次语义：记忆更新到本扫最近时刻后，同一 ``last_ts`` 的后续扫描
        不再命中（prev==last 不比）——10 分钟内同指纹不重复升级；新失败到来
        （last_ts > 记忆）才重新判别。本生命周期首见指纹（含重启后记忆文件
        缺失/损坏的降级态）回退对账分两级：先就 tail 窗内的次新条目判跨日差
        （零额外 IO）；仍无命中时对 ≥24h 前做定向检索（2.2，design D3：以
        last_ts 为锚构造窄时间窗，先按轮转文件 mtime 与行前缀缩小范围再
        grep，替代 256KB 尾读窗的 24h 盲区；逐轮预算
        _CROSSDAY_SEARCH_MAX_PER_SCAN 封顶）。

        缺时间戳条目（ts=None）不参与判别（无跨日差可算）；两级回退均未命中
        ——漏判方向 fail-open，与模块取证取向一致。持久化失败仅记日志，不
        影响主扫描。
        """
        memory = getattr(self, "_daemon_fp_last_failure", None)
        if memory is None:
            # __new__ 直构（单测）无 __init__：按空记忆处理并就地建
            memory = self._daemon_fp_last_failure = {}
        hits = {}
        dirty = False
        search_budget = _CROSSDAY_SEARCH_MAX_PER_SCAN
        for fp, stamps in by_fp.items():
            ts_all = sorted(t for t in stamps if t is not None)
            if not ts_all:
                continue
            last_ts = ts_all[-1]
            prev = memory.get(fp)
            if prev is None:
                # 本生命周期首见：先就 tail 窗内次新条目判跨日差（零额外 IO）
                for cand in reversed(ts_all[:-1]):
                    if (
                        abs(last_ts - cand - DAEMON_ERROR_CROSSDAY_PERIOD_SECONDS)
                        <= DAEMON_ERROR_CROSSDAY_TOLERANCE_SECONDS
                    ):
                        hits[fp] = (cand, last_ts)
                        break
                # tail 窗无前夜条目（重启后常态）：定向检索 ≥24h 前同签名
                if fp not in hits and search_budget > 0:
                    search_budget -= 1
                    cand = self._search_crossday_predecessor(fp, last_ts)
                    if cand is not None:
                        hits[fp] = (cand, last_ts)
            elif last_ts > prev:
                if (
                    abs(last_ts - prev - DAEMON_ERROR_CROSSDAY_PERIOD_SECONDS)
                    <= DAEMON_ERROR_CROSSDAY_TOLERANCE_SECONDS
                ):
                    hits[fp] = (prev, last_ts)
            if prev != last_ts:
                # 先 pop 再重插（code-review item 33042541a50c）：dict 对已存在
                # key 的就地赋值不刷新插入位次，下方「淘汰最早一半」按插入序取
                # 队首，会把长期活跃（每日复发、持续更新）的老指纹先于一次性
                # 出现后不再复发的陈旧指纹淘汰——跨日记忆丢失后下次复发只能
                # 回退日志尾对账，256KB 尾读窗容不下 24h 前的次新条目，跨日
                # 升级维度静默失效。重插使插入序=最近失败时刻序，淘汰才与
                # 注释「最早」的真实语义（最近失败时刻最旧）重新对齐。
                memory.pop(fp, None)
                memory[fp] = last_ts
                dirty = True
            # 容量上限（防无界增长）：超限淘汰最早一半（dict 保插入序）
            if len(memory) > DAEMON_ERROR_FP_MEMORY_LIMIT:
                for k in list(memory)[: DAEMON_ERROR_FP_MEMORY_LIMIT // 2]:
                    memory.pop(k, None)
                dirty = True
        if dirty:
            # 淘汰后快照落盘：文件体量随 DAEMON_ERROR_FP_MEMORY_LIMIT 有界
            self._persist_crossday_memory(memory)
        return hits

    def _crossday_log(self, level: str, message: str):
        """跨日记忆/检索的留痕通道：logger 缺失或级不存在时静默吞掉。

        观测私有路径——留痕失败 MUST NOT 打断主扫描（半初始化实例、close 后
        的 logger 等测试/关停态均安全）。
        """
        logger = getattr(self, "logger", None)
        if logger is None:
            return
        try:
            getattr(logger, level)("admin_monitor", message)
        except Exception:  # noqa: BLE001 — 留痕失败不影响主扫描
            pass

    def _load_crossday_memory(self) -> dict:
        """加载持久化跨日指纹记忆（evo-fix-…-normalization 2.1，启动时调用）。

        文件缺失/不可解析/形态不符一律降级为空记忆（回退两级日志对账），
        不抛错——观测私有记忆受损 MUST NOT 影响主扫描（规格「记忆损坏时降级
        安全」）。仅同进程单实例写（生产路径仅 daemon 构造一例），与
        pm_engine.infra_breaker 同判：跨进程 flock 防不了各自整文件覆写的
        lost update，实例内 threading.Lock 已覆盖读改写窗口。
        """
        project_root = getattr(self, "project_root", None)
        if project_root is None:
            return {}
        path = Path(project_root) / CROSSDAY_FP_MEMORY_REL
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            self._crossday_log(
                "info", f"跨日指纹记忆文件不可解析，降级为日志回退对账: {e}"
            )
            return {}
        memory: dict = {}
        entries = data.get("memory") if isinstance(data, dict) else None
        if isinstance(entries, dict):
            for k, v in entries.items():
                # 形态不符的条目跳过（部分损坏只弃坏条目，不弃整份记忆）
                if isinstance(k, str) and isinstance(v, (int, float)):
                    try:
                        memory[k] = float(v)
                    except OverflowError:
                        # 损坏记忆文件中的超大整型条目弃坏条目、不弃整份记忆；
                        # isinstance 守卫已排除 str/None 形态，float() 无其余
                        # 可抛异常类型（code-review item 5422628780b6）
                        continue
        return memory

    def _persist_crossday_memory(self, memory: dict):
        """持久化跨日指纹记忆快照（evo-fix-…-normalization 2.1）。写失败仅记
        日志不阻塞。须在调用方完成淘汰后调用（快照=淘汰后记忆，条目数随
        DAEMON_ERROR_FP_MEMORY_LIMIT 有界）。原子替换（mkstemp + fsync +
        os.replace，对齐 pm_engine/infra_breaker._save_state 既有形态）——
        写中途崩溃不留截断 JSON。
        """
        project_root = getattr(self, "project_root", None)
        if project_root is None:
            return
        lock = getattr(self, "_crossday_memory_lock", None)
        if lock is None:
            # __new__ 直构（单测）无 __init__：就地补锁（对象尚未共享时安全）
            lock = self._crossday_memory_lock = threading.Lock()
        path = Path(project_root) / CROSSDAY_FP_MEMORY_REL
        data = {
            "version": 1,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "memory": dict(memory),
        }
        try:
            with lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp_str = tempfile.mkstemp(
                    prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_str, str(path))
                finally:
                    if os.path.exists(tmp_str):
                        try:
                            os.unlink(tmp_str)
                        except OSError:
                            pass
        except OSError as e:
            self._crossday_log(
                "warning", f"跨日指纹记忆持久化失败（降级内存记忆）: {e}"
            )

    def _search_crossday_predecessor(self, fp: str, last_ts: float):
        """定向检索 ≥24h 前的同签名死亡条目（evo-fix-…-normalization 2.2，
        design D3）。

        以本轮扫描得到的同签名最新时刻 ``last_ts`` 为锚，构造 ``last_ts − 24h
        ± 容差`` 的窄时间窗（±5 分钟 → 分钟粒度行前缀 ≤12 个），先按轮转备份
        mtime 缩小候选集（mtime 早于窗口起点的备份只含更老条目），再 grep -F
        行前缀过滤，逐命中解析核对指纹与秒级窗。检索能力覆盖 ≥24h（受轮转
        备份保留期约束），替代 256KB 尾读窗的盲区；检索成本与命中留痕写
        debug 日志。任何失败（文件缺失/超时/grep 不可用）返回 None——漏判
        方向 fail-open，不影响主扫描。
        """
        project_root = getattr(self, "project_root", None)
        if project_root is None or not last_ts:
            return None
        win_start = (
            last_ts
            - DAEMON_ERROR_CROSSDAY_PERIOD_SECONDS
            - DAEMON_ERROR_CROSSDAY_TOLERANCE_SECONDS
        )
        win_end = (
            last_ts
            - DAEMON_ERROR_CROSSDAY_PERIOD_SECONDS
            + DAEMON_ERROR_CROSSDAY_TOLERANCE_SECONDS
        )
        log_dir = Path(project_root) / ".fenix" / "logs"
        # 行前缀窄窗：logger 的 JSON 行键序固定（timestamp 居首），分钟粒度
        # 固定串可被 grep -F 精确匹配（isoformat 的秒/微秒后缀不影响前缀）
        prefixes = []
        cur = math.floor(win_start / 60) * 60
        while cur <= win_end:
            prefixes.append(
                '"timestamp": "'
                + datetime.fromtimestamp(cur, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M"
                )
            )
            cur += 60
        candidates = []
        total_bytes = 0
        for name in ("fenixd.log",) + tuple(
            f"fenixd.log.{i}" for i in range(1, _LOG_ROTATION_BACKUPS + 1)
        ):
            f = log_dir / name
            try:
                st = f.stat()
            except OSError:
                continue
            if st.st_mtime < win_start:
                continue  # 该备份最后写入早于窗口起点 → 只含更老条目
            candidates.append(str(f))
            total_bytes += st.st_size
        window_desc = (
            f"{from_epoch(win_start).isoformat()}~{from_epoch(win_end).isoformat()}"
        )
        if not candidates:
            self._crossday_log(
                "debug",
                f"跨日回退定向检索：指纹 {fp[:8]} 窗口 {window_desc} 无候选"
                f"日志文件，未命中",
            )
            return None
        cmd = ["grep", "-F", "-h"]
        for p in prefixes:
            cmd += ["-e", p]
        cmd += candidates
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                timeout=_CROSSDAY_SEARCH_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as e:
            self._crossday_log(
                "debug", f"跨日回退定向检索失败（fail-open 漏判）: {e}"
            )
            return None
        hit_ts = None
        sig_lines = 0
        # 字节捕获 + replace 解码：日志可能含非 UTF-8 杂质，严格解码会整批失败
        for line in (res.stdout or b"").decode("utf-8", "replace").splitlines():
            parsed = self._parse_error_line(line.strip())
            if parsed is None:
                continue
            ts_epoch, component, message = parsed
            if ts_epoch is None or not (win_start <= ts_epoch <= win_end):
                continue
            if _error_fingerprint(component, message) != fp:
                continue
            sig_lines += 1
            if hit_ts is None or ts_epoch > hit_ts:
                hit_ts = ts_epoch
        self._crossday_log(
            "debug",
            f"跨日回退定向检索：指纹 {fp[:8]} 窗口 {window_desc} 扫候选文件"
            f" {len(candidates)} 个共 {total_bytes // 1024} KB、同签名 ERROR"
            f" {sig_lines} 条，{'命中 ' + str(from_epoch(hit_ts).isoformat()) if hit_ts else '未命中'}",
        )
        return hit_ts

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

    def _extract_daemon_signal_spec(self, signal: dict) -> str:
        """daemon 级信号（spec 为空）派发判定前的 spec 归属提取（1.2）。

        只对 DAEMON_ATTRIBUTABLE_SIGNAL_TYPES 白名单类型生效（1.3：跳过语义
        仅适用于具检测循环重发生命周期的 daemon 级信号类型，其余 None-spec
        类型不套用）；从 evidence（1.1 补齐的 ERROR 原文摘录为主基底）做
        「分支名 fenix/<spec>-<时间戳> 正则 + 已知 spec 名直接匹配」双线索
        归属（模块级 _extract_spec_attribution_from_text 单源），任一命中即
        返回 spec 名。evidence 无摘录的存量形态 / 无线索 / 状态读取失败一律
        返回空串——兜底与现状完全一致（1.4）；已有 spec 的信号原样返回自身
        spec（调用方 ``spec or …`` 短路，既有互斥行为不变）。本提取只读，
        不改写信号任何字段。
        """
        spec = signal.get("spec")
        if spec:
            return spec
        if signal.get("signal_type") not in DAEMON_ATTRIBUTABLE_SIGNAL_TYPES:
            return ""
        evidence = signal.get("evidence")
        if evidence is not None and not isinstance(evidence, str):
            try:
                evidence = json.dumps(evidence, ensure_ascii=False)
            except (TypeError, ValueError):
                evidence = str(evidence)
        try:
            known = list(self.state_machine.read_all().keys())
        except Exception:  # noqa: BLE001 — 状态读取失败按无已知 spec 兜底（fail-open）
            known = []
        return _extract_spec_attribution_from_text(evidence, known)

    def _make_daemon_error_signal(self, fp: str, count, last_str, missing_ts,
                                  crossday=None, excerpt=None) -> dict:
        """单指纹 daemon_errors 信号（文案与治理前保持一致，语义回归）。

        ``crossday``（可选，evo-add-codefix-conn-error-cooldown 3.1）：跨日同刻
        复发命中的 (prev_ts, last_ts) 二元组——description 追加复发判定（保留
        「指纹 <fp[:8]>」前缀子串，跨重启已知指纹对账依赖它），evidence 注明
        前次时刻明细。

        ``excerpt``（可选，evo-add-daemon-signal-spec-attribution-dedup 1.1）：
        最近一次同指纹 ERROR 原文摘录（_format_error_excerpt 产物，含组件名、
        截断限长）——附入 evidence 作为 daemon 级信号 spec 归属提取的基底
        （不补则提取恒空、归属能力 no-op）；description 的「指纹 <fp[:8]>」
        前缀子串与 ``_fp`` 判据保持不变。
        """
        crossday_desc = ""
        crossday_evidence = ""
        if crossday is not None:
            prev_ts, _last_ts = crossday
            crossday_desc = (
                "，判定为跨日同刻复发（与上次同指纹失败时刻差≈24 小时），"
                "已绕过已知指纹冷却升级"
            )
            crossday_evidence = (
                f"；跨日同刻复发：前次 {from_epoch(prev_ts).isoformat()}，"
                f"跨日差 {(_last_ts - prev_ts) / 3600:.2f} 小时"
                f"（容差 ±{DAEMON_ERROR_CROSSDAY_TOLERANCE_SECONDS // 60} 分钟）"
            )
        sig = self._make_signal(
            "daemon_errors",
            None,
            f"fenixd 日志同错误（指纹 {fp[:8]}）在 {DAEMON_ERROR_WINDOW_MINUTES} 分钟"
            f"窗口内复现 {count} 次，建议检查根因并重启 daemon" + crossday_desc,
            f"同指纹 ERROR 复现 {count} 次（最近一次 {last_str}"
            + (f"；{missing_ts} 条缺时间戳按窗口内计入" if missing_ts else "")
            + f"）；升级条件：同指纹 ≥{DAEMON_ERROR_THRESHOLD} 次且最近两次间隔"
            f" ≤{DAEMON_ERROR_RECURRENCE_MAX_GAP_MINUTES} 分钟" + crossday_evidence
            # 1.1：原文摘录附 evidence 尾部；缺省 None（存量直构形态）不追加
            + (f"；最近一次 ERROR 原文摘录：{excerpt}" if excerpt else ""),
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

        escalating 元组形态（evo-add-daemon-signal-spec-attribution-dedup 1.1
        扩至六元组）：(fp, count, last_str, missing_ts, crossday, excerpt)——
        excerpt 为该指纹最近一次 ERROR 原文摘录，逐指纹附入 evidence（归属
        提取基底）。
        """
        fp_summary = "、".join(
            f"指纹 {fp[:8]}（复现 {count} 次）" for fp, count, *_ in escalating
        )
        crossday_fps = [
            fp for fp, _, _, _, cd, _ex in escalating if cd is not None
        ]
        crossday_desc = (
            f"（其中指纹 {'、'.join(f[:8] for f in crossday_fps)} 判定跨日同刻"
            "复发，已绕过已知指纹冷却升级）"
            if crossday_fps else ""
        )
        sig = self._make_signal(
            "daemon_errors",
            None,
            f"fenixd 日志同轮 {len(escalating)} 项错误同时达升级阈值（{fp_summary}），"
            f"已合并为一条召唤信号、一次 Administrator run（alert-noise-governance"
            f" 3.2），建议检查根因并重启 daemon" + crossday_desc,
            "；".join(
                f"指纹 {fp[:8]} 复现 {count} 次（最近一次 {last_str}）"
                + (
                    f"；跨日同刻复发：前次 {from_epoch(cd[0]).isoformat()}"
                    if cd is not None else ""
                )
                # 1.1：逐指纹原文摘录（缺省空串不追加，存量直构形态不变）
                + (f"；最近一次 ERROR 原文摘录：{excerpt}" if excerpt else "")
                for fp, count, last_str, _, cd, excerpt in escalating
            )
            + f"；升级条件：同指纹 ≥{DAEMON_ERROR_THRESHOLD} 次且最近两次间隔"
            f" ≤{DAEMON_ERROR_RECURRENCE_MAX_GAP_MINUTES} 分钟",
        )
        # 合并信号的 status_hash 判据 = 全部指纹排序后的稳定拼接（与日志
        # 首现顺序无关：同集合同 hash，沉淀合并语义与单指纹一致）
        sig["_fp"] = "|".join(sorted(fp for fp, *_ in escalating))
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
            ts_dt = parse_ts(str(ts))  # SPEC-B 批③收拢；失败 None 同路置 None
            ts_epoch = ts_dt.timestamp() if ts_dt is not None else None
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
                    start = size - _TAIL_ERROR_READ_BYTES
                    # 边界判定（code-review item 96293d84951d）：回看 start 前
                    # 一字节，恰为换行符说明 start 本身是完整行的起点——回退到
                    # 该换行符处再 readline，只吞掉行尾换行、保留这条完整 ERROR
                    # 行（否则同指纹窗口计数少 1，极端情形下升级延迟一轮巡检，
                    # 漏报方向与模块 fail-closed 取向相反）；mid-line 时 readline
                    # 照旧丢弃截断残行。
                    f.seek(start - 1)
                    if f.read(1) == b"\n":
                        f.seek(start - 1)
                    else:
                        f.seek(start)
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
        """构造待落库的 signal 记录（_handle_signal 两处 append 共用的字段集）。

        add-alert-self-heal-marking 4.1：经 attach_trigger 统一埋点——
        daemon_errors 等在册类型的 signal 记落 trigger，自愈判定以 trigger
        与注册表双轨识别；未注册类型 attach_trigger 原样返回（无感知）。
        merge_signal 既有 last_seen 复现刷新逻辑不受影响（合并仅改写
        last_seen，不动 trigger）。
        """
        return attach_trigger(
            {
                "kind": SIGNAL,
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec"),
                "severity": signal.get("severity"),
                "description": signal.get("description"),
                "evidence": signal.get("evidence"),
                "recommended_action": signal.get("recommended_action"),
                "escalated": escalated,
            }
        )

    def _instant_fail_gate(self, spec_name) -> tuple:
        """秒挂冷却 spec 作用域门控判定（evo-add-instant-fail-cooldown-full-lane-gate 1.3）。

        仅作用于带 spec 归属的处置唤起：spec 为空（daemon_errors 全局信号，
        spec=null）恒放行 ``(False, 0)`` —— 全局自救通道 MUST NOT 被任一 spec
        的秒挂冷却拦截。与既有 signal-kill 冷却检查同判定口径
        （``agent_runner.is_instant_fail_cooldown``，查询侧到期即先复诵后
        消费）；runner 不可用或判定异常 fail-open 放行（与
        pm_engine._instant_fail_cooled 同构）。

        Returns: ``(cooled, remaining_seconds)``——cooled=True 时 remaining 为
        该 spec 当前冷却剩余秒（向下取整、钳非负），供 INFO 跳过留痕。
        """
        if not spec_name:
            return False, 0
        runner = getattr(self, "agent_runner", None)
        checker = getattr(runner, "is_instant_fail_cooldown", None)
        if not callable(checker):
            return False, 0
        try:
            cooled = checker(spec_name) is True
        except Exception:
            return False, 0
        if not cooled:
            return False, 0
        remaining = 0
        until_fn = getattr(runner, "instant_fail_cooldown_until", None)
        if callable(until_fn):
            try:
                remaining = max(0, int(float(until_fn(spec_name)) - time.monotonic()))
            except Exception:
                remaining = 0
        return True, remaining

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
        """处理单条信号：状态沉淀记录 + 节流判定 + 唤起 Administrator。

        返回 True 仅当信号通过全部守卫且唤起未被跳过（code-review item
        78eb37d3b06b）；各守卫丢弃路径（节流/冻结/夹具抑制/在飞互斥/
        落库拒写）为裸 return（None = 未送达），invoke 阶段的信号死法冷却/
        夜间断窗跳过同样透传 None（item 05825b6fe4e0），供 run_once 回滚
        spec_amendment_inflight 的指纹备忘。
        """
        spec = signal.get("spec")
        signal_type = signal.get("signal_type")
        status_hash = self._signal_status_hash(signal)

        # 节流：冷却窗口内同 spec 同类信号已唤起过 / 已有未处理升级告警 → 跳过唤起
        if self._throttled(spec, signal_type):
            record, is_new = self.store.merge_signal(
                self._signal_record(signal, escalated=False), status_hash
            )
            if record is None:
                # 损坏留底拒写：记录未落盘（item 27c156cb5272），无从按
                # 「已沉淀」记日志；拒写已在 store._mutate 记 error，此处静默
                return
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
        # code-review item a1cab4f7bb6c：复查判据从仅认 frozen 字段对齐为与
        # _detect_blocked_stuck 同款三重判据（单点 _is_intentionally_paused）——
        # 存量 spec 可能仅以历史 error 文本（'frozen:' 前缀/「用户指令」子串）
        # 表达冻结，结构化字段未迁移时同样是有意等待态，不得自动唤起。
        if spec:
            try:
                _entry = self.state_machine.read_one(spec) or {}
            except Exception:
                _entry = {}
            if _is_intentionally_paused(_entry):
                self.logger.info(
                    "admin_monitor",
                    f"Skipping auto-invocation for intentionally-paused SPEC "
                    f"'{spec}' (frozen field / frozen: prefix / 用户指令) — "
                    f"signal '{signal_type}' dropped, not anchored",
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
        # code-review item 4907de93dfb3：损坏留底拒写判别与节流分支同款——
        # merge_signal 返回 (None, False) 说明锚点未落盘，若仍以 signal_rec=None
        # 传入 _invoke_administrator，会被按人工通道语义处理：派发失败升级不带
        # next_retry_at/retry_count（不自动重试）、处置终态不回写信号 handled，
        # 本次自动唤起的后半链路在 store 单点故障下整体降级。记 ERROR 留痕后
        # 按未送达丢弃（裸 return，即本方法 docstring 的「落库拒写」出口）。
        if signal_rec is None:
            self.logger.error(
                "admin_monitor",
                f"Signal anchor persist refused (store write-guard), "
                f"dropping auto-invocation: {signal_type} "
                f"for '{spec or 'daemon'}'（item 4907de93dfb3）",
            )
            return
        # fix-recovery-path-blockers D2b：唤起前与在飞 admin run 互斥——D1 生效后
        # 处置中的 spec 会在冷却窗（缺省 60 分钟）过期后重新成条，无本守卫即产生
        # 与在飞处置**并行**的第二个 Administrator run（写同一批 STATE/
        # test_scenarios.json）。守卫按 spec 单键聚合、覆盖**任意** signal_type
        # （admin 处置的 signal_type 不只有 orphaned_state）。为真 → 跳过
        # 本次唤起（信号仍按既有沉淀/节流语义落 store，不丢痕）并记 WARNING。
        #
        # evo-add-daemon-signal-spec-attribution-dedup 1.2/1.3：daemon 级信号
        # （spec=None，白名单=DAEMON_ATTRIBUTABLE_SIGNAL_TYPES——具检测循环重生
        # 命周期）派发判定前先按 evidence 原文摘录提取 spec 归属再互查，消除
        # 同源阻塞事件与 spec 级信号的双派。提取不到/归属 spec 无在飞 run 时
        # _mutex_spec 退化为 spec 本身，与现状完全一致（1.4 兜底）；既有
        # spec 键互斥分支的日志/留痕文案与字段逐字不动。
        _mutex_spec = spec or self._extract_daemon_signal_spec(signal)
        if _mutex_spec and self._has_active_admin_run_for_spec(_mutex_spec):
            if spec:
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
                # 字段拼装/异常留痕收敛到 _persist_skipped_disposition
                # （item 4d50570fd394），文案与字段不变。
                self._persist_skipped_disposition(
                    signal,
                    (
                        "已有在飞 admin run，跳过重复唤起"
                        "（fix-recovery-path-blockers D2b 互斥守卫）——"
                        "实际未派发，在飞处置完成后由检测循环自然重评"
                    ),
                    spec=spec,
                )
                return
            # 1.3：daemon 级信号按归属互查命中——跳过本次派发。信号保持未消费
            # （不 mark handled / 不 mark_escalated；上方 merge_signal 冷却锚点
            # 照旧落库、不丢痕），按 _persist_skipped_disposition 既有形态补写
            # result="skipped" 注记（DISPOSITION 不参与 unhandled_for 节流，
            # 不阻断自然重评）：在飞 run 终态后，阻塞 ERROR 持续则同指纹过冷却
            # 窗再升级重发；诉求已被在飞 run 满足则错误止息不再升级（等效
            # pre-probe 闭环）。留痕 spec 记归属 spec（该 spec 的处置历史下可
            # 查），无 admin_run_id 不会被 _merge_admin_runs 误并在飞组。
            self.logger.warning(
                "admin_monitor",
                f"daemon 级信号 {signal_type} 按 evidence 归属 spec "
                f"'{_mutex_spec}'，该 spec 已有在飞 admin run——跳过本次派发，"
                f"{DAEMON_SIGNAL_COVERED_NOTE}"
                "（evo-add-daemon-signal-spec-attribution-dedup 1.3）",
                {"signal": signal, "attribution": _mutex_spec},
            )
            self._persist_skipped_disposition(
                signal,
                (
                    f"daemon 级信号按 evidence 归属 spec '{_mutex_spec}'，"
                    f"该 spec 已有在飞 admin run——{DAEMON_SIGNAL_COVERED_NOTE}"
                    "（evo-add-daemon-signal-spec-attribution-dedup 1.3）："
                    "实际未派发，信号保持未消费，在飞 run 终态后由检测循环"
                    "自然重评"
                ),
                spec=_mutex_spec,
                error_label="mutex-skip",
                error_context={
                    "signal_type": signal_type,
                    "attribution": _mutex_spec,
                },
            )
            return
        self.logger.warning(
            "admin_monitor",
            f"Distress detected, invoking Administrator: {signal_type} for '{spec or 'daemon'}'",
            {"signal": signal},
        )
        # code-review item 05825b6fe4e0：invoke 阶段的信号死法冷却/夜间断窗
        # 跳过（False）同为「未送达」——透传 None，与上方各守卫丢弃路径同
        # 口径，供 run_once 回滚 spec_amendment_inflight 指纹备忘，冷却到期/
        # 断窗结束后同修订提交集合仍可再次成条（is False 严格比对：invoke
        # 其余路径返回 None、测试桩替换的 MagicMock 均不影响既有「已送达」
        # 判定）。
        if self._invoke_administrator(signal, signal_rec) is False:
            return None
        # code-review item 78eb37d3b06b：唯一送达出口——上方各守卫丢弃路径
        # 均为裸 return（None），run_once 据此区分「已唤起」与「被丢弃」。
        return True

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
        时长与信号首见时间；signal_type 恒为 blocked_stuck 维持消费侧路由
        口径，真实悬置信号类型经 underlying_signal_type 透传），
        **不重新唤起 Administrator**（重唤起即重复烧钱，
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
        # 入口快照复用（code-review item 41086d72c513，比照 _detect_family_
        # explosion 的 c0df5dd3dbbf 惯例）：本循环内所有记录判定共用同一份
        # read_all() 快照——原先每条悬置 spec 先对悬置族逐类型调 store.
        # unhandled_for（每次全文件读 + LOCK_EX + 全量解析）、再经
        # _stalled_signal_first_and_latest 补一次全库读，合计 O(悬置数×全库)
        # 互斥读；快照过滤后每轮巡检只读一次。循环体内的升级落盘写库不影响
        # 快照判定（本函数与 unhandled_for 均只消费既有记录，同 spec 一轮至
        # 多命中一次，无「读到自身刚写记录」的语义依赖）。
        records = self.store.read_all()
        # 未处理人工告警存在性索引（快照上一次构建）：kind=ESCALATION ∧ 未
        # handled 的 (spec, signal_type) 对集合——存在性语义与逐类型
        # store.unhandled_for 等价（本处 spec 恒非 None，判据为严格相等）。
        # 非 str 的 spec/signal_type（人工修补/外部写入的脏形态）与 str 键
        # 严格相等恒不命中、isinstance 过滤后集合保持可哈希。
        unhandled_pairs = {
            (rec.get("spec"), rec.get("signal_type"))
            for rec in records
            if (
                rec.get("kind") == ESCALATION
                and not rec.get("handled")
                and isinstance(rec.get("spec"), str)
                and isinstance(rec.get("signal_type"), str)
            )
        }
        for name, entry in specs.items():
            if entry.get("status") != "blocked":
                continue
            # 冻结/用户指令暂停豁免与 _detect_blocked_stuck 同判据（有意等待态
            # 不反复催办；三重判据单点 _is_intentionally_paused，code-review
            # item a1cab4f7bb6c）
            if _is_intentionally_paused(entry):
                continue
            updated_str = entry.get("updated") or entry.get("created") or ""
            updated = parse_ts(updated_str)  # SPEC-B 批③收拢 parse_ts；None 同路 continue
            if updated is None:
                continue
            stalled_minutes = (now - updated.timestamp()) / 60
            if stalled_minutes < STALLED_ESCALATION_MINUTES:
                continue
            # 未处理约束：同 spec 已有任一悬置类信号类型的未处理人工告警 → 跳过
            # （unhandled_for 存在性判定改在入口快照的 unhandled_pairs 上内存过滤）
            if any(
                (name, st) in unhandled_pairs
                for st in STALLED_ESCALATION_SIGNAL_TYPES
            ):
                continue
            # 单点扫描（code-review 0abcbd87e154）：一次遍历同时取「信号首见
            # 时间」与「最新底层信号类型」，不再对每条命中 spec 先后做两次
            # 全量扫描；悬置族过滤条件改动只落 _stalled_signal_first_and_latest
            # 一处。快照透传（item 41086d72c513）免每条命中 spec 再读全库。
            first_seen, underlying = self._stalled_signal_first_and_latest(
                name, records=records
            )
            first_seen = first_seen or updated_str
            # 真实根因透传（code-review d3006f6884e0）：落盘 signal_type 恒为
            # blocked_stuck（按 signal_type 路由的既有消费口径不变），因 ENV
            # 阻塞族悬置而被强制升级时，真实信号类型经 underlying_signal_type
            # 透传（对齐 disposition_signal_hits_auto_reset /
            # fix-manual-invoke-signal-type-passthrough 2.1 约定），并在 evidence
            # 中显式呈现供人工/看板归位。
            self.store.append(
                attach_trigger(
                    {
                        "kind": ESCALATION,
                        "signal_type": "blocked_stuck",
                        "underlying_signal_type": underlying,
                        "spec": name,
                        "severity": "critical",
                        "description": (
                            f"'{name}' 已 blocked 悬置 {int(stalled_minutes)} 分钟"
                            f"（≥{STALLED_ESCALATION_MINUTES} 分钟）未处置，自动通道已被"
                            f"冷却压制，强制升级人工介入"
                        ),
                        "evidence": (
                            f"updated={updated_str}；悬置时长 {int(stalled_minutes)} 分钟；"
                            f"底层信号类型 {underlying}；"
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

    def _stalled_signal_first_and_latest(
        self, spec: str, records: Optional[list] = None
    ) -> tuple[Optional[str], str]:
        """单次扫描返回 (最早悬置类信号 created, 最新悬置类信号 signal_type)。

        单点助手（code-review 0abcbd87e154：原 _first_signal_time 与
        _underlying_stalled_signal_type 是同一段「read_all + kind=SIGNAL +
        spec 相等 + 悬置族过滤」循环的两个副本，仅聚合方向不同——最早
        created / 最新 created 并取类型；合并为一次遍历后过滤条件改动只落
        此处，消费方 _force_escalate_stalled 对每条命中 spec 不再先后两次
        全量扫描）。records：调用方已持全库快照时透传（item 41086d72c513），
        免每条命中 spec 重复读库；缺省 None 时自读（既有调用形态不变）。

        created 语义（原两函数口径逐字保持）：状态沉淀后 created 保留首次
        语义（first_seen），多轮续报只刷 last_seen——最早一条即「信号首见」，
        最新一条的类型反映当前根因。_force_escalate_stalled 落盘的
        ESCALATION 恒写 signal_type=blocked_stuck，ENV 阻塞族
        （verify_env_blocked/verify_env_inconclusive）悬置的真实类型经
        underlying_signal_type 透传（消费约定见
        disposition_signal_hits_auto_reset）；无悬置族信号记录（或记录无
        created）时 created 为 None、类型回退 blocked_stuck。created 比较
        口径：store 统一生成同格式 UTC ISO 串，字典序即时间序。
        """
        earliest = None
        latest = None
        latest_type = "blocked_stuck"
        for rec in (records if records is not None else self.store.read_all()):
            if (
                rec.get("kind") != SIGNAL
                or rec.get("spec") != spec
                or rec.get("signal_type") not in STALLED_ESCALATION_SIGNAL_TYPES
            ):
                continue
            created = rec.get("created")
            # [fenix-ignore:a39572533269] store 侧 created 恒由 _utcnow_iso() 统一生成（UTC +00:00、微秒精度，无写入方显式传值），同偏移下该格式族字典序与时间序一致，不存在混用格式
            if not created:
                continue
            if earliest is None or created < earliest:
                earliest = created
            if latest is None or created > latest:
                latest = created
                latest_type = str(rec.get("signal_type") or "blocked_stuck")
        return earliest, latest_type

    # ── 派发失败重试巡检（admin-dispatch-failure-escalation D2） ──

    def _retry_due_dispatch_failures(self, now: float) -> int:
        """派发失败升级记录到期重试巡检（admin-dispatch-failure-escalation D2）。

        扫描 kind=escalation ∧ next_retry_at ≤ now ∧ retry_count < 1 ∧
        未 handled 的派发失败记录 → 重建原信号 → 直接调 _invoke_administrator
        重试派发一次（带 _dispatch_retry_id 标记）。

        MUST NOT 经 _handle_signal：节流（latest_signal/unhandled_for，
        见 _throttled）命中刚写的升级记录把重试吞掉；重试直接
        走派发链本身，等价于把「冷却后重试一次原信号」落在派发时刻。frozen
        spec 跳过（同 _handle_signal 冻结语义，人工等待态不自动重试）。
        manual 派发记录不带 next_retry_at，天然不在扫描范围。

        投递前先 bump 既有记录 retry_count 入扫描闸门占锚（code-review
        f286af2d657e：从 executor.submit 到 worker 实际执行 run_administrator
        落 pending DISPOSITION 之间无任何在飞记录，不占锚则下一巡检周期对同一
        条到期记录重复重派 → 并行 Administrator run 写同一批 STATE）；重试失败
        由 _invoke_administrator 内部 bump 既有记录 retry_count（上限
        DISPATCH_RETRY_MAX，不追加新记录，与占锚 bump 同键幂等）；重试成功由
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
            due = parse_ts(str(next_retry_at))  # SPEC-B 批③收拢；None 同路 continue
            if due is None:
                continue
            if due.timestamp() > now:
                continue
            # frozen spec 跳过：三重判据单点 _is_intentionally_paused（同
            # _handle_signal 唤起前复查），历史 error 文本表达冻结的存量 spec
            # 同样不自动重试（人工等待态语义，见模块级 docstring）
            spec = rec.get("spec")
            if spec:
                try:
                    entry = self.state_machine.read_one(spec) or {}
                except Exception:
                    entry = {}
                if _is_intentionally_paused(entry):
                    self.logger.info(
                        "admin_monitor",
                        f"Skipping dispatch retry for frozen SPEC '{spec}'",
                    )
                    continue
            signal = self._rebuild_dispatch_signal(rec)
            if signal is None:
                continue
            signal["_dispatch_retry_id"] = rec.get("id")
            # fix-recovery-path-blockers D2b 在飞互斥：本路径直接调
            # _invoke_administrator，绕过了 _handle_signal 的「已有在飞 admin
            # run 即跳过」守卫——到期重派若撞上同 spec 已有在飞 admin run（另
            # 一信号类型或人工通道），会与其并行写同一批 STATE/test_scenarios.json。
            # 守卫口径与 _recover_orphaned_dispositions 重派守卫对齐（spec 单键
            # 聚合、任意 signal_type 命中——fix-admin-cross-type-duplicate-
            # dispatch：注释中「另一信号类型或人工通道」的危害至此被真正守住；
            # 本路径无既有 run 可排除，不传 exclude_run_id）。为真 → 跳过本轮
            # 重试，不 bump retry_count（互斥非派发失败，下轮到期仍会重评）。
            # evo-add-daemon-signal-spec-attribution-dedup 1.2/1.3：daemon 级
            # 升级记录（spec=None，如 daemon_errors 派发失败重试）同样先按
            # evidence 归属再互查——否则归属 spec 的在飞 run 收口前，到期重派
            # 会与其并行双开（同源阻塞双派的派发失败重试变体）。spec 键记录
            # （spec or … 短路）行为逐字不变；互斥非派发失败：不 bump
            # retry_count，下轮到期仍会重评；重试车道按既有惯例不落处置痕
            # （同下方 fixture 抑制块「命中仅日志留痕，同互斥守卫不落处置痕」）。
            _retry_mutex_spec = spec or self._extract_daemon_signal_spec(signal)
            if _retry_mutex_spec and self._has_active_admin_run_for_spec(
                _retry_mutex_spec
            ):
                self.logger.info(
                    "admin_monitor",
                    f"Skipping dispatch retry for '{_retry_mutex_spec}' (signal "
                    f"{signal.get('signal_type')}): active admin run already in "
                    f"flight (escalation {rec.get('id')})"
                    + (
                        f"——daemon 级信号按 evidence 归属，"
                        f"{DAEMON_SIGNAL_COVERED_NOTE}"
                        "（evo-add-daemon-signal-spec-attribution-dedup 1.3）"
                        if not spec else ""
                    ),
                )
                continue
            # fixture 项目抑制（alert-noise-governance 5.1）：到期重派同属
            # 自动召唤，跳过（升级记录保留不删除，5.2）；不 bump retry_count
            # ——抑制非派发失败，下轮巡检到期仍会重评（窗内维持阻断）。
            if self._fixture_invocation_suppressed(signal):
                continue
            # 信号死法冷却与夜间断窗/provider 瞬断冻结的预判：两条跳过在
            # _invoke_administrator 内部均声明「非失败路径 MUST NOT 增
            # retry_count」，而下方占锚 bump 已先抬满 retry_count——bump 后
            # 才在其内部命中跳过则配额无回滚，下轮巡检 retry_count >=
            # DISPATCH_RETRY_MAX 永久跳过，断窗/冷却结束后的唯一一次自动
            # 重派静默丢失。与上方互斥/fixture 抑制同款：在 bump 之前
            # continue，不消耗重试配额，下轮到期重评（判定复用
            # _invoke_administrator 既有口径，预判未命中仍由其内部同判定
            # 把关；命中仅日志留痕，同互斥守卫不落处置痕）。
            # 判定谓词单源 _dispatch_precheck_guards（code-review item
            # 052de970a16f）：冷却与下方断窗两预判收编为同一辅助，上方
            # 「复用 _invoke_administrator 既有口径」的注释约定至此落到
            # 共享代码本身，不再靠三处手写同构对齐。
            _sig_spec = signal.get("spec")
            _sig_cooled, _block_reasons = self._dispatch_precheck_guards(signal)
            if _sig_cooled:
                self.logger.info(
                    "admin_monitor",
                    f"Skipping dispatch retry for '{_sig_spec}' (signal "
                    f"{signal.get('signal_type')}): signal-kill cooldown "
                    f"active (escalation {rec.get('id')})",
                )
                continue
            # evo-add-instant-fail-cooldown-full-lane-gate 1.3：秒挂冷却 spec
            # 作用域门控——与上方 signal-kill 冷却预判同点位并列、同款「bump
            # 之前 continue」语义（不消耗重试配额，下轮到期重评，命中仅日志
            # 留痕不落处置痕）；spec=null 全局信号放行（_instant_fail_gate
            # 恒返回 False）。
            _if_cooled, _if_remaining = self._instant_fail_gate(
                signal.get("spec"))
            if _if_cooled:
                self.logger.info(
                    "admin_monitor",
                    f"Skipping dispatch retry for '{signal.get('spec')}' (signal "
                    f"{signal.get('signal_type')}): instant-fail cooldown active, "
                    f"{_if_remaining}s remaining (escalation {rec.get('id')})",
                )
                continue
            # _block_reasons 已由上方 _dispatch_precheck_guards 一并求值。
            if _block_reasons:
                self.logger.info(
                    "admin_monitor",
                    f"Skipping dispatch retry for '{spec or 'daemon'}' (signal "
                    f"{signal.get('signal_type')}): night window/provider "
                    f"break avoidance (escalation {rec.get('id')})",
                )
                continue
            self.logger.warning(
                "admin_monitor",
                f"Dispatch failure retry due: re-invoking Administrator for "
                f"original signal {signal.get('signal_type')} on "
                f"'{spec or 'daemon'}' (escalation {rec.get('id')})",
            )
            # 投递锚（code-review f286af2d657e）：投递前先 bump retry_count 入
            # 扫描闸门（≥DISPATCH_RETRY_MAX）占位，覆盖 executor 饱和时 submit
            # 与 run_administrator 落 pending 之间的无锚窗口。投递失败（引擎
            # 不可用）本就 bump 同一键，终态语义不变；投递丢失（worker 长期
            # 饥饿未执行）不再自动重派，记录停留未处理升级待人工——保守方向：
            # 宁可少重试一次，不可并行 Administrator run 写同一批 STATE。
            self.store.bump_dispatch_retry(rec.get("id"), DISPATCH_RETRY_MAX)
            self._invoke_administrator(signal, rec)
            retried += 1
        return retried

    # ── 孤儿处置重派（admin-disposition-reschedule） ─────────────

    def _has_active_admin_run_for_spec(self, spec, exclude_run_id=None,
                                       records=None) -> bool:
        """该 spec 是否存在在飞/待派发的 Administrator run（任意 signal_type）。

        fix-recovery-path-blockers D2：守卫口径按 spec 单键聚合、覆盖**任意**
        signal_type（admin 处置的 signal_type 可能是 verify_env_blocked /
        manual-intervention / stuck，不只有 orphaned_state）。委托模块级
        ``_spec_has_active_admin_run``（单一归并实现，勿二次漂移）；判定异常
        fail-open 返回 False 并记 WARNING（守卫故障不阻断恢复路径）。

        exclude_run_id：透传归并本体同名参数——孤儿重派排除「正被孤儿处理的
        中断 run」自身，其 pending 记录是本判定的考察对象，不得把自己误判为
        「已有在飞 run」；仅排除该 run，同 spec 其他（跨类型）在飞 run 仍命中
        （fix-admin-cross-type-duplicate-dispatch：全部派发路径统一 spec 单键
        口径，按 (spec, signal_type) 精确匹配的窄口径方法已收敛删除）。

        records：透传模块级函数同名参数——已持全库快照的调用方（如
        _detect_family_explosion 摄取循环）免每候选一次重复读库。
        """
        return _spec_has_active_admin_run(
            self.store, spec, logger=self.logger, exclude_run_id=exclude_run_id,
            records=records,
        )

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
        # by_run 归并单点在 _merge_admin_runs（三处共用，勿二次漂移）；
        # 本消费方不过滤，只取每组首条记录与 final 标记。
        by_run = _merge_admin_runs(records)

        for rid, info in by_run.items():
            if info["final"]:
                # evo-add-admin-orphan-disposition-effect-check 1.1/1.2：final
                # 组不再无条件 continue——「组已终态 ∧ 关联底层 SIGNAL 仍未
                # 收口」是「动作已执行、终态未落账」窗口死亡（或回写门豁免
                # 形态）的永久滞留，扫描对其做只读生效核查：动作已实际生效
                # → 补记 resolved 并收口关联信号；未生效 → 维持滞留并走既有
                # 升级（fail-closed）。健康组（信号已收口）等条件不合者在
                # 分支内原样返回，行为与旧「直接 continue」一致。
                self._converge_final_orphan_group(rid, info, records, now, grace)
                continue
            pending = info["rec"]
            created = parse_ts(pending.get("created") or "")  # SPEC-B 批③收拢
            if created is None:
                continue
            if now - created.timestamp() < grace:
                continue
            spec = pending.get("spec")
            sig_type = pending.get("signal_type")
            # 组 spec 记法先归一（code-review item eec0928bc868，同
            # _converge_final_orphan_group 既有口径）：daemon 级孤儿组的
            # DISPOSITION 记 spec="global"、SIGNAL/其余 daemon 级写入记
            # spec=None，unhandled_for/unhandled_signal_for 严格相等匹配都以
            # 归一后的 None 为准——不归一则重派通道对 daemon 级信号恒不命中
            # （回落「终结 interrupted」静默失效）、本分支升级去重也看不见
            # spec=None 的既有未处理升级。组 DISPOSITION 落盘保留原形，不在
            # 归一范围（同 _converge_final_orphan_group 的既有写法）。
            sig_query = _normalize_orphan_group_spec(spec)
            if self.store.unhandled_for(sig_query, sig_type) is not None:
                continue

            # 死亡证据门（2026-09-18 误报取证修复，与 fix-graceful-shutdown-agents
            # 的 interrupted 判定同源扩展）：admin 处置耗时不受 grace 约束，故
            # 「超 grace 无最终记录」**不足以**推断 run 已死。仅当 run 文件同时
            # 满足 ① 存在 且 ② 末行是终态事件 时才确认死亡；文件存在但末行非
            # 终态（仍在跑）/读失败 → 本方法不是死亡判定器，跳过，不落告警。
            # 保守方向：宁可漏报（用户可见 admin run 仍在写流），不可拿「超时」
            # 冒充「被杀」——误报的措辞会误导人工去查根本不存在的 daemon 崩溃。
            #
            # ① 文件两处均缺失的分支（code-review item 8075b441970d）：run 文件
            # 被「runs 保留」规则连顶层与 archive 归档副本一起清理（或从未落盘）
            # 时，旧逻辑按「非终态 → 跳过」处理，该 pending 组每轮巡检都被
            # continue、永远拿不到非 pending 终结记录——_merge_admin_runs 的
            # 在飞判据（has_pending 且非 final）随之恒真，_handle_signal /
            # 家族爆炸摄取 / 派发失败重试 / 处置后复位四条自动通道全部被
            # _has_active_admin_run_for_spec 永久封死（仅人工通道可用）。文件全无
            # = 既无「仍在写流」证据、也无死亡证据，但 pending 不能永久占用在飞
            # 判定：补一条 result=interrupted 的非 pending 处置终结该 run（沿用
            # 既有中断词表，不落人工升级告警，保守取向不变；底层信号仍在 store，
            # 冷却过期后由既有检测自然重派）。
            if self._admin_run_file(rid) is None:
                self.store.append(
                    {
                        "kind": DISPOSITION,
                        "status": "interrupted",
                        "signal_type": sig_type,
                        "spec": spec,
                        "admin_run_id": rid,
                        "result": "interrupted",
                        "actions_taken": (
                            "AdminMonitor 孤儿检测：run 产物在顶层与 archive 两处均"
                            "不存在（保留规则已清理或从未落盘），无在写证据，"
                            "补非 pending 终结避免 pending 永久占用在飞判定"
                        ),
                        "description": (
                            f"Administrator 处置 run 产物缺失（run {rid}），"
                            f"pending 终结（不升级人工）"
                        ),
                    }
                )
                self.logger.info(
                    "admin_monitor",
                    f"Orphaned admin disposition terminated (run file missing "
                    f"from runs/ and archive/): {rid}",
                )
                continue
            if not self._run_file_has_terminal_state(rid):
                continue

            # fix-graceful-shutdown-agents：先验 run 文件是否含 interrupted 标记（daemon
            # 优雅退出所致已知中断）。含标记 → 判定已知中断：终结 pending disposition 且
            # 不产生人工升级告警；无标记 → 维持现有"疑似 daemon 崩溃"升级兜底
            # （保守方向：宁可多告警不漏告警；文件两处均缺失的形态已在上方
            # 死亡证据门①补终结，不再到达本分支）。
            #
            # admin-disposition-reschedule：已知中断分支前置回溯底层未处理信号——
            # 命中（kind=signal ∧ escalated ∧ 非 handled ∧ (spec, signal_type) 严格相等）
            # 且重派未超限时，重新入队 admin run 而非静默终结；超限则升级人工。
            # 信号未找到 / 信号重建失败 / 已有在飞 run → 回落原「终结 interrupted」逻辑。
            if self._run_has_interrupted_marker(rid):
                # 归一后查询（code-review item eec0928bc868）：daemon 级信号
                # 记录 spec=None，传原形 "global" 恒不命中 → 重派通道静默失效。
                sig_rec = self.store.unhandled_signal_for(sig_query, sig_type)
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
                                    # daemon 级升级落归一后值（None，其余 daemon 级
                                    # 写入口径），"global" 占位会被
                                    # unhandled_for(None,…) 类 daemon 级消费漏看
                                    # （code-review item eec0928bc868）
                                    "spec": sig_query,
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
                    # 在飞互斥守卫口径与 _retry_due_dispatch_failures 对齐
                    # （`if spec and ...`）：daemon 级记录 spec=None 时
                    # _merge_admin_runs 的 spec 过滤被 None 哨兵禁用（None =
                    # 不过滤），任意其他 spec 的在飞 pending 都会
                    # 令守卫误真 → 重派被放弃、原 run 落 interrupted 终结；
                    # spec 非空才判定，spec=None 跳过守卫（同款先例 2751/2971）。
                    # spec 单键聚合、任意 signal_type 命中（fix-admin-cross-type-
                    # duplicate-dispatch）；exclude_run_id=rid 仅排除被处理的中断
                    # run 自身，同 spec 其他（跨类型）在飞 run 仍命中守卫。
                    if signal is not None and (
                        not spec
                        or not self._has_active_admin_run_for_spec(
                            spec, exclude_run_id=rid
                        )
                    ):
                        # fixture 项目抑制（alert-noise-governance 5.1）：置于
                        # superseded 记录写入与重派之前——不写「已重派」审计、
                        # 不重入队 admin run；原 pending 记录保持待下一轮重评
                        # （人工显式触发不受限）。
                        if self._fixture_invocation_suppressed(signal):
                            continue
                        # 信号死法冷却与夜间断窗/provider 瞬断冻结的预判（code-review
                        # item 8c429de6762c，比照 _retry_due_dispatch_failures 既有
                        # 口径）：两条跳过在 _invoke_administrator 内部均只写 skipped
                        # 留痕，而下方 superseded 审计已先追加「自动重新入队」、
                        # reschedule_count 已抬到 next_count——写痕后才在其内部命中
                        # 跳过则审计与事实不符且重派配额无谓消耗。在写 superseded
                        # 记录之前 continue，原 pending 记录保持待下轮重评（预判未
                        # 命中仍由其内部同判定把关；命中仅日志留痕，同 fixture 抑制
                        # 不落处置痕）。
                        # 判定谓词单源 _dispatch_precheck_guards（code-review
                        # item 052de970a16f，与 _retry_due_dispatch_failures
                        # 同批收编）。
                        _sig_spec = signal.get("spec")
                        _sig_cooled, _block_reasons = self._dispatch_precheck_guards(signal)
                        if _sig_cooled:
                            self.logger.info(
                                "admin_monitor",
                                f"Skipping orphan reschedule for '{_sig_spec}' (signal "
                                f"{sig_type}): signal-kill cooldown active (run {rid})",
                            )
                            continue
                        # evo-add-instant-fail-cooldown-full-lane-gate 1.3：秒挂
                        # 冷却 spec 作用域门控——与上方 signal-kill 预判同点位
                        # 并列、同款「superseded 审计写入之前 continue」语义
                        # （不写「已重派」审计、不重入队 admin run）；spec=null
                        # 全局信号放行。
                        _if_cooled, _if_remaining = self._instant_fail_gate(
                            signal.get("spec"))
                        if _if_cooled:
                            self.logger.info(
                                "admin_monitor",
                                f"Skipping orphan reschedule for "
                                f"'{signal.get('spec')}' (signal {sig_type}): "
                                f"instant-fail cooldown active, "
                                f"{_if_remaining}s remaining (run {rid})",
                            )
                            continue
                        # _block_reasons 已由上方 _dispatch_precheck_guards
                        # 一并求值。
                        if _block_reasons:
                            self.logger.info(
                                "admin_monitor",
                                f"Skipping orphan reschedule for '{spec or 'daemon'}' (signal "
                                f"{sig_type}): night window/provider break avoidance "
                                f"(run {rid})",
                            )
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
                        # daemon 级升级落归一后值（None，其余 daemon 级写入口径），
                        # "global" 占位会被 unhandled_for(None,…) 类 daemon 级消费
                        # 漏看、_converge_final_orphan_group 随后再补一条重复升级
                        # （code-review item eec0928bc868）
                        "spec": sig_query,
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

    # ── 孤儿处置收敛的生效核查补记（evo-add-admin-orphan-disposition-effect-check）──

    def _converge_final_orphan_group(self, rid, info, records, now: float,
                                     grace: int) -> None:
        """final 处置组 ∧ 关联底层 SIGNAL 仍未收口 → 只读生效核查后收敛。

        「组已 final（_merge_admin_runs 口径：任一非 pending 记录在场）∧
        关联底层 SIGNAL 仍未收口（unhandled_signal_for 命中，escalated=true
        口径；组 spec 记法先经 _normalize_orphan_group_spec 归一 None↔
        "global"）」是「动作已执行、终态未落账」窗口死亡的永久滞留形态
        （2026-10-03 429 现场：partially-resolved 终态 + pending 占位 +
        信号 handled=false 滞留 21h+）。本分支按序设防：

        1. 幂等：组内已存在补记记录（source=orphan-backfill）→ 跳过；
        2. escalate=true 终结记录在场 → 升级人工是唯一出路（与回写门
           escalate 豁免同口径），不进入收敛；
        3. grace 门取组内最新记录时刻——刚落终态的组给 _worker 的回写窗口，
           避免与在飞收尾竞态（回写紧随终态 append，秒级窗口由 grace 兜住）；
        4. 健康组（信号已收口/已归档）在 unhandled_signal_for 未命中处
           原样返回——行为与旧「直接 continue」一致；
        5. 在飞互斥：同 spec 存在在飞 run（exclude_run_id=本组 rid）时信号
           归在飞 run 认领，不抢先收口；
        6. 生效核查通过 → append_orphan_backfill 补记 resolved（注明补记与
           依据）+ mark_signal_handled 收口关联信号；不通过 → 不补记，维持
           滞留并走既有孤儿升级路径（unhandled_for 已升级去重，fail-closed：
           宁可滞留升级，不可假闭环）。

        健康组不进入收敛分支的判据只用「关联 SIGNAL 未收口」——
        disposition 自身 handled 字段无 mutator（恒 false）、组内滞留
        pending 占位是健康组常态形，二者均不可作判据（design 判别锚点取证）。
        """
        group = [
            r for r in records
            if r.get("kind") == DISPOSITION and r.get("admin_run_id") == rid
        ]
        if not group:
            return
        # ① 幂等：已补记的组不再重复补记/收口（与信号已收口的天然幂等双保险
        # ——补记后 mark_signal_handled 收口，后续轮次在下方未命中处返回）
        if self.store.has_disposition_backfill(rid):
            return
        head = info["rec"] or {}
        group_spec = head.get("spec")
        sig_type = head.get("signal_type")
        if not sig_type:
            return
        # ② 组内已有 escalate=true 终结记录：升级人工是唯一出路，不收敛
        for r in group:
            status = r.get("status") or r.get("result")
            if status and status != "pending" and r.get("escalate"):
                return
        # ③ grace 门（组内最新记录时刻）：终态刚落账时 _worker 的信号回写
        # 可能仍在途，此时收口会与在飞收尾竞态
        created_ts = []
        for r in group:
            dt = parse_ts(str(r.get("created") or ""))
            if dt is not None:
                created_ts.append(dt.timestamp())
        if not created_ts or now - max(created_ts) < grace:
            return
        # ④ 健康组/信号已归档：关联 SIGNAL 已收口 → 与旧「直接 continue」一致
        sig_rec = self.store.unhandled_signal_for(
            _normalize_orphan_group_spec(group_spec), sig_type
        )
        if sig_rec is None:
            return
        # ⑤ 在飞互斥：同 spec 在飞 run（排除本组 rid）在场时不抢先收口；
        # spec 传组记录原形（"global" 占位参与精确过滤，None 哨兵退化为
        # 宽口径——宁可漏收敛不可抢在飞 run 的信号，方向 fail-closed）
        if self._has_active_admin_run_for_spec(group_spec, exclude_run_id=rid):
            return
        effective, evidence = self._orphan_group_effect_evidence(
            group, group_spec, now, sig_rec=sig_rec
        )
        if not effective:
            # ⑥ fail-closed：不补记，维持滞留，走既有孤儿升级路径
            # （unhandled_for 已升级去重——升级告警未被人工处理前不重复成条）；
            # 同时补 escalate=true 终结记录，本组此后整体进入 ② 豁免，
            # 不因人工 handled 后失去去重锚点而逐轮重复升级。
            # 去重查询与升级记录落盘统一经 _normalize_orphan_group_spec 归一
            # （daemon 级写 spec=None，同 _detect_restart_failure 等升级路径口径，
            # "global" 占位记录会被 unhandled_for(None,…) 等 daemon 级查询漏掉）；
            # 组 DISPOSITION 保留 "global" 既有形态，不在归一范围
            escal_spec = _normalize_orphan_group_spec(group_spec)
            if self.store.unhandled_for(escal_spec, sig_type) is None:
                self.store.append(
                    attach_trigger(
                        {
                            "kind": ESCALATION,
                            "signal_type": sig_type,
                            "spec": escal_spec,
                            "severity": "critical",
                            "description": (
                                f"Administrator 处置终态未收口（run {rid}）：处置组已终态但底层信号 "
                                f"{sig_type} 仍未收口，生效核查未找到动作已实际生效的真实状态证据，"
                                f"需人工介入"
                            ),
                            "evidence": (
                                f"final disposition group admin_run_id={rid}；"
                                f"关联信号未收口（escalated=true）；生效核查：{evidence}"
                            ),
                            "action_taken": (
                                "AdminMonitor 孤儿处置收敛核查：生效核查未通过，"
                                "不补记 resolved，升级人工（fail-closed）"
                            ),
                            "admin_run_id": rid,
                            "recommended_action": (
                                "人工核实处置动作是否实际生效：已生效可手动 resolve 收口信号，"
                                "未生效请人工处置该信号"
                            ),
                        }
                    )
                )
                self.store.append(
                    {
                        "kind": DISPOSITION,
                        "status": "escalated",
                        "signal_type": sig_type,
                        "spec": group_spec,
                        "admin_run_id": rid,
                        "result": "escalated",
                        # escalate=true 终结记录：本组此后进入 ② 豁免（升级
                        # 人工是唯一出路，与回写门 escalate 豁免同口径）
                        "escalate": True,
                        "actions_taken": (
                            "AdminMonitor 孤儿处置收敛核查：生效核查未通过，"
                            "维持滞留并升级人工，终结收敛尝试"
                        ),
                        "description": (
                            f"孤儿处置组（run {rid}）生效核查未通过，已升级人工"
                        ),
                        "evidence": evidence,
                    }
                )
                self.logger.warning(
                    "admin_monitor",
                    f"Orphaned final disposition group not effective, escalated "
                    f"to human: {rid} (signal {sig_type} still unhandled)",
                )
            return
        # ⑦ 补记 resolved（append 新记录、注明补记与依据）+ 收口关联信号。
        # 按 _close_signal_preprobed 先例：留痕失败不阻断收口本身（反方向：
        # 收口失败也不回滚补记——补记是事实落账，信号下一轮仍会在此被重试）。
        backfill = self.store.append_orphan_backfill(
            rid,
            sig_type,
            group_spec,
            actions_taken=(
                "AdminMonitor 孤儿处置收敛：生效核查通过，补记 resolved "
                "（evo-add-admin-orphan-disposition-effect-check）"
            ),
            description=(
                f"孤儿处置组（run {rid}）动作经真实状态核查已实际生效，"
                f"补记终态并收口关联信号 {sig_type}"
            ),
            evidence=evidence,
        )
        if backfill is None:
            # 记录未落盘（文件损坏留底被拒写）：不收口信号，待下一轮重试
            self.logger.error(
                "admin_monitor",
                f"Orphan disposition backfill not persisted (refused), "
                f"signal left unhandled: {rid}",
            )
            return
        handled = self.store.mark_signal_handled(
            sig_rec.get("id"),
            action_taken="orphan-backfill：生效核查通过，补记 resolved 收口",
            result="resolved",
        )
        self.logger.info(
            "admin_monitor",
            f"Orphaned final disposition group backfilled resolved: {rid} "
            f"(signal {sig_type} handled={'ok' if handled else '未命中'})",
            {"evidence": evidence},
        )

    def _orphan_group_effect_evidence(self, group, group_spec, now: float,
                                      sig_rec=None):
        """只读核查处置组动作是否已实际生效。返回 (effective: bool, evidence: str)。

        证据源只看真实状态（禁止以处置记录文本自证——记录 summary 声称
        「已计划/已执行」不构成证据，spec「生效核查不看记录自证」场景）。
        证据为按处置动作类型的家族并集，依序尝试、任一家族命中即判定生效；
        全部家族未命中维持 fail-closed（宁可滞留升级，不可假闭环）：

        - 组 spec 为具体 spec：STATE 的 frozen 标记与 status 推进——解冻类
          动作生效签名 = frozen=False 且 status 离开 blocked（design D2）；
          STATE 是该形态的持久真实状态源（日志轮转不丢），单源即可判定。
          STATE 无条目（被并发软删等）→ 回退 global/None 同门（下方家族）。
        - ①解冻留痕（日志候选集）：组记录 created 邻域时间窗内的解冻族
          Transition 留痕（blocked → 其他，channel=manual/recovery），检索
          面覆盖 fenixd.log 及轮转备份（evo-admin-orphan-effect-evidence-
          expansion）。
        - ②提交类旁证（新增）：对账窗口内 git log——merge commit 提交消息
          含目标 spec 名（合并目标分支名），或归档收尾提交（非 merge，消息
          同时含 spec 名、家族前缀与收尾关键词；单一条件不命中防假阳性）。
        - ③STATE 旁证（新增，仅 global/None 组）：从组记录 actions_taken/
          evidence 或关联 SIGNAL 记录提取明确 spec 名 token（提取不到不猜、
          跳过本家族），回退 state_machine.read_one 按同门判据核查；STATE
          无条目/读取失败按无证据处理（fail-closed）。

        处置记录文本仅可作提取 spec 名与建立对账窗口的指针，不构成生效
        证据本身（「禁止记录自证」约束对新增家族同样适用）。
        """
        sig_spec = _normalize_orphan_group_spec(group_spec)
        if sig_spec is not None:
            try:
                entry = self.state_machine.read_one(sig_spec)
            except Exception as e:  # noqa: BLE001 — 状态读取失败按无状态对账
                self.logger.debug(
                    "admin_monitor",
                    f"orphan effect check: STATE read failed for '{sig_spec}': {e}",
                )
                entry = None
            if entry:
                frozen = bool(entry.get("frozen"))
                status = str(entry.get("status") or "")
                if not frozen and status and status != "blocked":
                    return True, (
                        f"STATE '{sig_spec}' frozen=False status={status}（已解冻推进）"
                    )
                return False, (
                    f"STATE '{sig_spec}' frozen={frozen} "
                    f"status={status or '缺失'}（未见解冻推进）"
                )
        # 日志对账窗（组记录 created 邻域）：下界 = 最早记录 − 松弛，上界 = now
        starts = []
        for r in group:
            dt = parse_ts(str(r.get("created") or ""))
            if dt is not None:
                starts.append(dt.timestamp())
        if not starts:
            return False, "组记录无可解析 created 时刻，无法建立日志对账窗口"
        window_start = min(starts) - _ORPHAN_EFFECT_LOG_SLACK_SECONDS
        # ① 解冻留痕（日志候选集：fenixd.log + 轮转备份）
        hits = self._read_recent_unfreeze_transitions(window_start, now)
        if hits:
            return True, (
                f"日志对账窗口内解冻族 Transition 留痕 {len(hits)} 条"
                f"（首条：{hits[0]}）"
            )
        # ②③ 提交类/STATE 旁证都以「目标 spec 名」为匹配锚点：先做不猜提取
        # （组记录文本 → 关联 SIGNAL 记录）；具体 spec 组的 spec 名本身即锚点
        spec_names = self._extract_orphan_group_spec_names(group, sig_rec)
        if sig_spec is not None and sig_spec not in spec_names:
            spec_names.insert(0, sig_spec)
        if spec_names:
            # ② 提交类旁证：merge commit / 归档收尾提交（git 只读查询）
            commit_ev = self._orphan_commit_evidence(window_start, now, spec_names)
            if commit_ev:
                return True, commit_ev
            # ③ STATE 旁证（仅 global/None 组：具体 spec 组上方已按单源判定）
            if sig_spec is None:
                state_ev = self._orphan_state_corroboration_evidence(spec_names)
                if state_ev:
                    return True, state_ev
        miss = "对账窗口内无解冻族 Transition 留痕/提交类旁证/STATE 旁证"
        if not spec_names:
            miss += "（spec 名不可提取，STATE/提交家族无锚点跳过）"
        return False, (
            f"{miss}（window_start={from_epoch(window_start).isoformat()}）"
        )

    def _extract_orphan_group_spec_names(self, group, sig_rec=None) -> list:
        """从组记录文本提取目标 spec 名候选（提取不到不猜，仅作匹配指针）。

        提取顺序（design「spec 名提取」节）：组内 DISPOSITION 记录
        actions_taken/evidence 文本 → 关联 SIGNAL 记录 description/evidence
        文本。token 形态为 ≥3 段小写 kebab-case；fenix/<spec>-<ts> 分支记法
        剥尾部 ≥10 位纯数字派发时间戳得 spec 名（-7c1997 类十六进制短后缀
        是 spec 名组成部分，不剥）；admin-global-<ts> run id 剥 ts 后的占位
        残渣丢弃。去重保序并截断到 _ORPHAN_SPEC_NAME_TOKEN_LIMIT。误取由
        STATE 无条目/提交消息不匹配兜底（fail-closed），提取结果本身不构成
        生效证据。
        """
        texts = []
        for r in group:
            texts.append(str(r.get("actions_taken") or ""))
            texts.append(str(r.get("evidence") or ""))
        if sig_rec is not None:
            texts.append(str(sig_rec.get("description") or ""))
            texts.append(str(sig_rec.get("evidence") or ""))
        names = []
        placeholder_residue = f"admin-{_ORPHAN_GLOBAL_SPEC_PLACEHOLDER}"
        for text in texts:
            for tok in _ORPHAN_SPEC_NAME_TOKEN_RE.findall(text):
                name = _ORPHAN_SPEC_TOKEN_DISPATCH_TS_RE.sub("", tok)
                if not name or name == placeholder_residue:
                    continue
                if name not in names:
                    names.append(name)
                if len(names) >= _ORPHAN_SPEC_NAME_TOKEN_LIMIT:
                    return names
        return names

    @staticmethod
    def _is_orphan_finalize_commit(subject: str, spec_name: str) -> bool:
        """归档收尾提交判定：spec 名 ∧ 家族前缀 ∧ 收尾关键词三条件同时在场。

        单一条件（仅 spec 名或仅前缀）不命中——防提交消息假阳性误收口
        （spec「提交消息假阳性不误判」场景）。spec 名匹配与
        _is_orphan_merge_commit 同款 token 边界负向前后视（code-review item
        9251b2fb3793）：裸 ``name in subject`` 子串匹配在 spec 名互为前缀
        （fix-x vs fix-x-y）时，窗口内前缀兄弟 spec 的归档收尾提交三条件全
        中、被当本组处置旁证假闭环收口；仅放宽名后紧跟 ``-<≥10 位数字>``
        派发时间戳分支记法（_ORPHAN_MERGE_TS_LOOKAHEAD），不命中由调用方
        回落其余家族，fail-closed 取向不变。
        """
        if re.search(
            r"(?<![\w-])" + re.escape(spec_name) + _ORPHAN_MERGE_TS_LOOKAHEAD,
            subject,
        ) is None:
            return False
        if not any(p in subject for p in _ORPHAN_EFFECT_FINALIZE_COMMIT_PREFIXES):
            return False
        return any(k in subject for k in _ORPHAN_EFFECT_FINALIZE_COMMIT_KEYWORDS)

    @staticmethod
    def _is_orphan_merge_commit(subject: str, spec_name: str) -> bool:
        """merge commit 家族锚点判定（code-review item f12f9a282a95）。

        裸 ``name in subject`` 子串匹配在 spec 名互为前缀（fix-x vs fix-x-y）
        时，窗口内合并的是另一 spec 的分支（"Merge branch 'fenix/fix-x-y-…'"
        含 "fix-x" 子串）也会命中本组——被当「处置动作已实际生效」的提交类
        旁证收口底层信号，正是本机制 fail-closed 要防的假闭环。此处对齐
        _ORPHAN_SPEC_NAME_TOKEN_RE 的负向前后视做 token 边界匹配，仅放宽名后
        紧跟 ``-<≥10 位数字>``（分支记法 fenix/<name>-<派发时间戳> 的既有形态，
        纯 token 边界会把真实 merge-back 误拒；≥10 位口径与
        _ORPHAN_SPEC_TOKEN_DISPATCH_TS_RE 一致，-7c1997 类十六进制短后缀仍算
        spec 名组成部分、不误放行；数字段尾锚定到串尾或引号/空白/常见标点
        分隔符（code-review f87ef32726a2，模式见
        _ORPHAN_MERGE_TS_LOOKAHEAD），「时间戳段后仍有后缀」形态与该剥离
        正则同向不误放行）。不命中由调用方回落其余家族，fail-closed
        取向不变。
        """
        return re.search(
            r"(?<![\w-])" + re.escape(spec_name) + _ORPHAN_MERGE_TS_LOOKAHEAD,
            subject,
        ) is not None

    def _git_log_commit_subjects(self, extra_args: list) -> list:
        """只读 git log（HEAD 历史），返回 [(committer_ts, subject)]；失败返回 []。

        通道参照 core/code_review._git / core/deliverables._git_log_path_history
        既有先例（subprocess git -C <project_root>，硬超时）；git 不可用/非
        仓库/查询失败一律返回空列表（提交类家族按无证据处理，fail-closed）。
        """
        try:
            proc = subprocess.run(
                ["git", "-C", str(self.project_root), "log",
                 "--format=%ct%x1f%s"] + list(extra_args),
                capture_output=True,
                text=True,
                timeout=_ORPHAN_EFFECT_GIT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            self.logger.debug(
                "admin_monitor",
                f"orphan effect check: git log {extra_args} failed: {e}",
            )
            return []
        if proc.returncode != 0:
            self.logger.debug(
                "admin_monitor",
                f"orphan effect check: git log exit={proc.returncode} "
                f"stderr={(proc.stderr or '').strip()[:200]}",
            )
            return []
        out = []
        for line in proc.stdout.splitlines():
            ts_s, sep, subject = line.partition("\x1f")
            if not sep or not ts_s.strip().isdigit():
                continue
            out.append((int(ts_s.strip()), subject))
        return out

    def _orphan_commit_evidence(self, window_start: float, now: float,
                                spec_names: list):
        """提交类旁证：对账窗口内 merge commit / 归档收尾提交（只读 git log）。

        (a) merge commit：``git log --merges`` 窗口内提交且消息含目标 spec 名
        （合并目标分支名；token 边界锚定见 _is_orphan_merge_commit，item
        f12f9a282a95）；(b) 归档收尾提交：非 merge 提交且消息同时含目标
        spec 名与归档收尾家族前缀（+收尾关键词）。两类均须提交时间（committer
        ts）落在对账窗内。命中返回证据字符串，全不命中/git 失败返回 None
        （该家族按无证据处理，不阻塞其余家族，fail-closed）。

        git 侧窗口剪枝（code-review item 503369e85097）：两条 log 均带
        ``--since``（git 按提交者时刻剪枝，与 %ct 同字段、与 Python 侧窗口
        过滤同口径），避免大仓库先枚举全部历史后才在 Python 侧过滤；Python
        侧窗口过滤保留作双保险（git --since 在乱序日期的历史拓扑上有漏提交
        可能，漏判方向与「无证据」同路 fail-closed，不加严）。
        """
        since = datetime.fromtimestamp(window_start, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S+00:00"
        )
        merges = self._git_log_commit_subjects(["--merges", f"--since={since}"])
        finalizes = self._git_log_commit_subjects(["--no-merges", f"--since={since}"])
        for name in spec_names:
            for ts, subject in merges:
                if (window_start <= ts <= now
                        and self._is_orphan_merge_commit(subject, name)):
                    return (
                        f"对账窗口内 merge commit 提交消息含目标 spec 名 '{name}'"
                        f"（{from_epoch(ts).isoformat()}：{subject[:120]}）"
                    )
            for ts, subject in finalizes:
                if (window_start <= ts <= now
                        and self._is_orphan_finalize_commit(subject, name)):
                    return (
                        f"对账窗口内归档收尾提交命中目标 spec 名 '{name}'"
                        f"（{from_epoch(ts).isoformat()}：{subject[:120]}）"
                    )
        return None

    def _orphan_state_corroboration_evidence(self, spec_names: list):
        """STATE 旁证（global/None 组末位家族）：提取的 spec 名回退 read_one
        按「frozen=False 且 status 离开 blocked」同门判据核查。

        STATE 无条目/读取失败按无证据跳过该候选（不猜、不假闭环）；任一候选
        命中返回证据字符串，全不命中返回 None。
        """
        for name in spec_names:
            try:
                entry = self.state_machine.read_one(name)
            except Exception as e:  # noqa: BLE001 — 读取失败按无证据跳过
                self.logger.debug(
                    "admin_monitor",
                    f"orphan effect check: STATE read failed for '{name}': {e}",
                )
                continue
            if not entry:
                continue
            frozen = bool(entry.get("frozen"))
            status = str(entry.get("status") or "")
            if not frozen and status and status != "blocked":
                return (
                    f"STATE '{name}'（提取 spec 名旁证）frozen=False "
                    f"status={status}（已解冻推进）"
                )
        return None

    def _read_recent_unfreeze_transitions(self, since_epoch: float,
                                          until_epoch: float) -> list:
        """日志候选集尾部（逐文件 ≤256KB）检索时间窗内解冻族 Transition 留痕。

        候选集 = fenixd.log + fenixd.log.1.._LOG_ROTATION_BACKUPS（日志轮转
        不丢证据：解冻留痕可能已轮转出当前日志尾部，落入备份文件，evo-admin-
        orphan-effect-evidence-expansion）。按对账窗口过滤：mtime 早于窗口
        起点的文件整体跳过（只含更老条目，与跨日复发检索 :3449 同款剪枝），
        行级再按时间戳窗内截取；逐文件尾部限量（_TAIL_ERROR_READ_BYTES）与
        单文件时代同语义，最坏成本与跨日复发检索同量级。

        匹配 _finish_transition 成功行形态 ``Transition: <spec> blocked →
        <new>`` 且 context.channel ∈ {manual, recovery}（人为裁决通道）；
        刻意不匹配 "Gate transition: " 前缀（门禁自动逃生门非人为证据）。
        返回人类可读留痕摘要列表（日志时序序——轮转文件从最老 .N 起迭代）；
        读取/解析失败按无证据返回空列表（fail-closed：不补记，维持滞留升级）。
        """
        log_dir = self.project_root / ".fenix" / "logs"
        # 轮转序倒序迭代（fenixd.log.5 最老 → … → .1 → 当前），命中摘要保持
        # 日志时序序（首条 = 窗内最老留痕，与单文件时代语义一致）
        candidates = [f"fenixd.log.{i}" for i in range(_LOG_ROTATION_BACKUPS, 0, -1)]
        candidates.append("fenixd.log")
        hits = []
        for name in candidates:
            log_file = log_dir / name
            try:
                st = log_file.stat()
            except OSError:
                continue  # 文件不存在/不可 stat：候选集按实际在场的文件算
            if st.st_mtime < since_epoch:
                continue  # mtime 剪枝：最后写入早于窗口起点 → 只含更老条目
            try:
                size = st.st_size
                with log_file.open("rb") as f:
                    if size > _TAIL_ERROR_READ_BYTES:
                        start = size - _TAIL_ERROR_READ_BYTES
                        # 边界判定与 _read_tail_error_entries 同款（code-review
                        # item 96293d84951d）：回看一字节保住完整行起点
                        f.seek(start - 1)
                        if f.read(1) == b"\n":
                            f.seek(start - 1)
                        else:
                            f.seek(start)
                        f.readline()  # 丢弃 seek 可能截断的首行
                    data = f.read().decode("utf-8", "replace")
            except OSError:
                continue
            for line in data.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                if entry.get("component") != "state_machine":
                    continue
                if entry.get("level") != "INFO":
                    continue
                m = _ORPHAN_UNFREEZE_TRANSITION_RE.match(str(entry.get("message") or ""))
                if m is None:
                    continue
                ctx = entry.get("context")
                channel = str(ctx.get("channel") or "") if isinstance(ctx, dict) else ""
                if channel not in _ORPHAN_EFFECT_DELIBERATE_CHANNELS:
                    continue
                ts = parse_ts(str(entry.get("timestamp") or ""))
                if ts is None or not since_epoch <= ts.timestamp() <= until_epoch:
                    continue
                note = ctx.get("note") if isinstance(ctx, dict) else None
                hits.append(
                    f"{m.group(1)} blocked → {m.group(2)} "
                    f"(channel={channel}, note={note or ''})"
                )
        return hits

    def _run_has_interrupted_marker(self, admin_run_id: str) -> bool:
        """检查 admin_run_id 对应的 run 产物是否含 interrupted 标记（已知 daemon 中断）。

        fix-graceful-shutdown-agents：admin agent 被 daemon 优雅退出终止时，agent_runner
        会向 `.fenix/runs/<admin_run_id>.jsonl` 追加 `{"type": "interrupted"}` 记录。孤儿
        检测据此区分"已知中断"（与 run 共存）与"疑似崩溃"（run 无标记）。run 文件被 prune
        删除或读不到标记，一律按 False（无证据 → 升级兜底，保守方向）。

        路径解析复用 `_admin_run_file`（含 archive 回退）——run 被「runs 保留」规则
        移入 `archive/` 后，只看顶层会漏掉标记，使已知中断被误判为疑似崩溃。

        code-review item 346ecee6af03：只做尾部限量读（``_RUN_TAIL_READ_WINDOW``
        窗口，边界判定范式同 ``_run_terminal_status``）——标记由 daemon 退出路径
        O_APPEND 追加，其后 run 进程已死不再有新写入（启动补写扫描只对**无**终态
        事件的文件追加，含标记的文件不会被再写），标记恒在文件尾部。孤儿巡检每轮
        对每个超宽限 pending 组各调一次，全量逐行读的 IO 开销随转录体积（admin
        处置实测数十 MB）线性增长，无必要。窗口未命中 → False，仍走「疑似崩溃 →
        升级兜底」的既有保守方向，不损失正确性。

        Args:
            admin_run_id: admin disposition 的 admin_run_id（形如 admin-<spec>-<ts>）。
        """
        run_file = self._admin_run_file(admin_run_id)
        if run_file is None:
            return False
        try:
            size = run_file.stat().st_size
            first_line_truncated = False
            with run_file.open("rb") as f:
                if size > _RUN_TAIL_READ_WINDOW:
                    start = size - _RUN_TAIL_READ_WINDOW
                    # 边界判定（code-review item 190881dd0168 同款，对齐
                    # _run_terminal_status）：回看 start 前一字节，恰为换行说明
                    # start 本身是完整行的起点，该行须保留；仅 mid-line 切入时
                    # 丢截断残段（残段 JSON 解析失败本就跳过，显式丢弃不靠
                    # 解析失败兜底）。
                    f.seek(start - 1)
                    first_line_truncated = f.read(1) != b"\n"
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            return False
        lines = tail.split("\n")
        if first_line_truncated:
            lines = lines[1:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and entry.get("type") == "interrupted":
                return True
        return False

    def _admin_run_file(self, admin_run_id: str):
        """定位 admin run 产物文件：先顶层 `.fenix/runs/`，再 `archive/`。

        run 收工后被「runs 保留」清理移入 `archive/`（见 fenixd 主循环
        runs_retention_check），届时顶层已不存在——只 glob 顶层会让所有依赖
        run 文件的死亡判定突然失明（文件缺失）。归档副本也不再永久保留（SPEC
        归档即清理、无主产物天龄兜底，fix-run-cleanup-attach-spec-archive D1/D2），
        两处均无 → None。

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
        """run 产物文件存在且**末条非空行**为终态事件 → 确认该 admin run 已死。

        终态事件类型取自 `core/agent_runner/liveness.py:RUN_TERMINAL_EVENT_TYPES`
        真源（result/interrupted/error/cancelled 等）。判定用**末行**而非全文，
        委托 liveness 的末行语义原语 ``_file_tail_is_terminal``（64KB 尾读窗口
        + 全量逐行回退，对齐 dashboard classify_run 只看末行）：末行终态即 run
        已明确终结；「早先写过终态又被后续事件续写」的形态末行非终态 → 不判死
        （code-review c2f94a923839：旧实现委托 _file_has_terminal_event 逐行
        扫描、任一行命中即真，实为任意行口径——终态后被续写的文件会把仍存活
        的 admin run 误判死亡，落「疑似 daemon 重启/崩溃」误报；末行口径不依赖
        写入侧「终态后置」不变式）。读失败/无末行 → False（非死亡证据，保守
        不升级）。

        Args:
            admin_run_id: admin disposition 的 admin_run_id。
        """
        run_file = self._admin_run_file(admin_run_id)
        if run_file is None:
            return False
        try:
            from core.agent_runner.liveness import _file_tail_is_terminal
        except Exception:
            return False
        try:
            return bool(_file_tail_is_terminal(run_file))
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

    def _dispatch_precheck_guards(self, signal: dict) -> tuple:
        """唤起前预判守卫判定单源（code-review item 052de970a16f）。

        信号死法冷却与夜间断窗/provider 瞬断冻结两个预判此前在
        _retry_due_dispatch_failures（占锚 bump 前）、孤儿处置重派
        （superseded 审计写入前）与 _invoke_administrator（权威判定）三处
        各手写一份同构 try 兜底，判定口径靠注释约定一致——单点演进漏改
        任一副本即出现「预判放行而权威拦截」或反向的口径漂移。收编为本
        辅助后三处复用同一谓词；各调用点保留差异化日志、落痕与控制流
        （continue / return False），取用次序与原手写序一致（冷却在前、
        断窗在后，两预判之间的秒挂冷却门控留在各调用点原位）。

        返回二元组 ``(sig_cooled, block_reasons)``：

        - ``sig_cooled``：spec 处信号死法冷却期为 True（spec 为空/替身缺
          方法/调用异常一律 False，fail-open 不误伤半初始化实例）。
        - ``block_reasons``：夜间断窗/provider 瞬断冻结命中原因短语列表
          （``_night_dispatch_block_reasons`` 的 try 兜底结果，异常按空表
          处理）。两谓词均先行求值，调用点按各自原次序取用。

        只判定不落痕——落痕与控制流由调用方按通道形态补。
        """
        try:
            _sig_spec = signal.get("spec")
            sig_cooled = (
                bool(_sig_spec)
                and callable(getattr(self.agent_runner, "is_signal_kill_cooldown", None))
                and self.agent_runner.is_signal_kill_cooldown(_sig_spec) is True
            )
        except Exception:
            sig_cooled = False
        try:
            block_reasons = self._night_dispatch_block_reasons()
        except Exception:
            block_reasons = []
        return sig_cooled, block_reasons

    def _night_dispatch_block_reasons(self) -> list:
        """admin 唤起避让判定（evo-add-night-window-inflight-guard 2.1）。

        两不派条件（design D2，与信号死法冷却同位、同样作用于人工显式
        触发——本闸语义是「保护 run 不进必死窗口」而非「抑制噪音召唤」，
        断窗/冻结期内人工唤起同样必死）：

        - provider 瞬断冻结态：复用
          ``agent_runner.is_global_transient_break_active``（
          provider_circuit.is_global_transient_break 的委托别名）；替身缺
          该方法/调用异常按未冻结处理（fail-open，替身/半初始化实例不误伤）。
        - 夜间断窗期：窗配置与解析复用 core.code_fix 单源（design D3，不
          引入第二份窗配置），键 ``admin.code_review_fix.night_quiet_window``
          （与 code-fix 车道同键同缺省）；本地时区当前时刻落任一窗
          ``[start, end)`` 即命中；多窗列表（evo-add-review-night-defer-
          snapshot-writeoff 1.3）命中任一窗即避让，原因短语含全部命中窗
          区间；空串/off 显式禁用窗则不避让。配置读取/解析/导入异常一律
          按无窗处理——观测失败 MUST NOT 阻断唤起主路径。

        返回命中原因短语列表（空＝不避让）。只判定不落痕——落痕由调用方
        ``_invoke_administrator`` 按通道形态补（自动路径补 DISPOSITION、
        人工路径仅日志）；跳过 MUST NOT 增 retry_count、MUST NOT 落升级告警。
        """
        reasons: list = []
        try:
            frozen = (
                callable(getattr(
                    self.agent_runner, "is_global_transient_break_active", None))
                and self.agent_runner.is_global_transient_break_active() is True
            )
        except Exception:
            frozen = False
        if frozen:
            reasons.append("provider 瞬断冻结态")
        try:
            from .code_fix import (
                NIGHT_QUIET_WINDOW_DEFAULT,
                _parse_night_quiet_windows,
            )

            raw = self._get_config(
                "admin.code_review_fix.night_quiet_window",
                NIGHT_QUIET_WINDOW_DEFAULT,
            )
            windows = _parse_night_quiet_windows(raw)
            if windows:
                lt = time.localtime()
                cur = lt.tm_hour * 60 + lt.tm_min
                hits = [w for w in windows if w[0] <= cur < w[1]]
                if hits:
                    joined = ", ".join(w[2] for w in hits)
                    reasons.append(f"夜间静默窗内（窗区间 {joined}）")
        except Exception:
            pass
        return reasons

    def invoke_manual(self, signal: dict):
        """手动唤起入口（fenixd 主循环拾取 .fenix/admin_invoke_request.json）。

        与自动检测共用 _invoke_administrator 的唤起+落痕路径：run_administrator
        完成后落最终 DISPOSITION（终结 run_administrator 开头落的 pending 记录；
        executor 可用时唤起+落痕在后台 worker 内完成，同步回退态返回即已完成），
        escalate 时落升级告警。此前手动路径直接调 run_administrator 并丢弃返回值，
        pending 永无终态、处置叙述从不入告警时间线，dashboard 上显示「处置中」
        导致用户反复手动重呼（2026-08-29 v2-cutover-main-entry 三连呼实证）。

        不检查 enabled：用户显式呼叫应始终响应（enabled 只约束自动巡检）。
        唯一例外是夜间断窗/provider 瞬断冻结避让闸（
        evo-add-night-window-inflight-guard 2.1，design D2）：断窗/冻结期内
        唤起注定被断网/熔断击杀，人工呼叫同样避让本轮跳过，窗末/解冻后
        重新呼叫即生效。
        """
        self._invoke_administrator(signal, None)

    def _persist_skipped_disposition(
        self, signal: dict, action_taken: str, spec=None,
        severity=None, description=None, error_label: str = "mutex-skip",
        error_context: dict = None,
    ) -> None:
        """补写 result="skipped" 说明性 DISPOSITION（「实际未派发」留痕单点）。

        四处近似重复块（_detect_family_explosion 在飞互斥 / _handle_signal
        在飞互斥 / _invoke_administrator 信号死法冷却与夜间断窗避让）的公共
        字段拼装与异常留痕集中于此（code-review item 4d50570fd394）：调用点
        只传差异化 action_taken 文案与 error_label。result="skipped" 不命中
        任何 result 消费分支，DISPOSITION 不参与 unhandled_for 节流。

        severity/description 显式传参则覆盖 signal 同名字段（_detect_family_
        explosion 的源记录兜底形态）；spec 缺省回落 signal.get("spec")；
        error_label 用于落盘失败日志文案区分（mutex-skip / cooldown-skip /
        window-avoidance）；error_context 为落盘失败日志附加上下文。
        """
        try:
            self.store.append(
                {
                    "kind": DISPOSITION,
                    "signal_type": signal.get("signal_type"),
                    "spec": spec if spec is not None else signal.get("spec"),
                    "severity": (
                        severity if severity is not None
                        else signal.get("severity")
                    ),
                    "description": (
                        description if description is not None
                        else signal.get("description")
                    ),
                    "action_taken": action_taken,
                    "result": "skipped",
                }
            )
        except Exception as e:
            self.logger.error(
                "admin_monitor",
                f"Failed to persist {error_label} disposition for "
                f"'{spec or 'daemon'}': {e}",
                error_context,
            )

    def _invoke_administrator(self, signal: dict, signal_rec: dict):
        """唤起 Administrator 处置；失败或升级时落升级告警。

        唤起+落痕整体经 ``_code_review_executor`` 投递后台 worker 执行（巡检
        线程不同步等待小时级 admin run，否则 run_once 同线程的审查看门狗等
        检查点停摆）；executor 不可用（测试/禁用态）回退同步执行，返回即
        落痕完成。

        返回值约定（code-review item 05825b6fe4e0）：信号死法冷却与夜间断窗/
        瞬断冻结两个跳过路径返回 False（实际未派发 = 未送达，供 _handle_signal
        透传 None 触发 run_once 的指纹备忘回滚）；其余路径（正常投递、
        agent_runner 缺失升级、守卫拒写）维持返回 None，语义不变。
        """
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
        # 判定谓词单源 _dispatch_precheck_guards（code-review item
        # 052de970a16f）：冷却与下方断窗两预判收编为同一辅助，
        # _retry_due_dispatch_failures 占锚前预判与孤儿重派车道复用本
        # 权威判定同一口径，不再靠三处手写同构对齐。
        _sig_spec = signal.get("spec")
        _sig_cooled, _block_reasons = self._dispatch_precheck_guards(signal)
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
                # 字段拼装/异常留痕收敛到 _persist_skipped_disposition
                # （item 4d50570fd394），文案与字段不变。
                self._persist_skipped_disposition(
                    signal,
                    (
                        "信号死法冷却中，跳过 Administrator 唤起"
                        "（evo-sigterm-source-tracking-cooldown）——"
                        "实际未派发，冷却到期由恢复定时器/检测循环自然恢复"
                    ),
                    error_label="cooldown-skip",
                )
            # code-review item 05825b6fe4e0：向调用方回传「未送达」——否则
            # 被冷却跳过的修订告警在冷却期内不再成条，违背上方「冷却到期
            # 自然恢复」文案的承诺。
            return False

        # evo-add-instant-fail-cooldown-full-lane-gate 1.3：秒挂冷却 spec 作用域
        # 门控——与上方信号死法冷却检查同点位并列（该 spec 连续秒挂达阈值，
        # 反复唤起只会再次撞运气烧预算）。spec=null 的 daemon_errors 全局信号
        # 唤起恒放行（_instant_fail_gate 对空 spec 返回 False），不锁死故障期
        # 的自救通道。留痕 INFO（spec 名、车道、剩余冷却秒数）+ skipped 处置痕，
        # 同款「不虚报已唤起」约定。
        _if_cooled, _if_remaining = self._instant_fail_gate(signal.get("spec"))
        if _if_cooled:
            self.logger.info(
                "admin_monitor",
                f"秒挂冷却中，跳过 Administrator 唤起 '{signal.get('spec')}'"
                f"（剩余 {_if_remaining}s，到期自动恢复；"
                f"evo-add-instant-fail-cooldown-full-lane-gate）",
            )
            if signal_rec is not None:
                self._persist_skipped_disposition(
                    signal,
                    (
                        "秒挂冷却中，跳过 Administrator 唤起"
                        "（evo-add-instant-fail-cooldown-full-lane-gate）——"
                        "实际未派发，冷却到期由恢复定时器/检测循环自然恢复"
                    ),
                    error_label="cooldown-skip",
                )
            return False

        # evo-add-night-window-inflight-guard 2.1：夜间断窗/provider 瞬断冻结
        # 避让（design D2）——与上方信号死法冷却同位并列，同样作用于人工显式
        # 触发（先例：code-fix 静默窗对手动触发同样生效，手动授权仅越过
        # enabled 总开关）。跳过属非失败路径：MUST NOT 增 retry_count、
        # MUST NOT 落升级告警，仅留痕原因；spec 保持原状，下一轮盘点/检测
        # 循环自然重试。
        # _block_reasons 已由上方 _dispatch_precheck_guards 一并求值。
        if _block_reasons:
            _reason_text = "、".join(_block_reasons)
            self.logger.info(
                "admin_monitor",
                f"夜间断窗/瞬断冻结避让，跳过 Administrator 唤起 "
                f"'{signal.get('spec') or 'daemon'}'（{_reason_text}）——"
                "留待下一轮盘点重试"
                "（evo-add-night-window-inflight-guard）",
            )
            # 对齐上方冷却跳过的落痕纪律：自动巡检路径唤起前 _handle_signal
            # 已落 escalated=True 的 signal 记录（虚报「已唤起」锚点），本路径
            # 实际未派发——补写说明性处置记录（result="skipped" 不命中任何
            # result 消费分支、不参与 unhandled_for 节流）。人工通道
            # （signal_rec=None）无该虚报锚点，仅日志留痕。
            if signal_rec is not None:
                # 字段拼装/异常留痕收敛到 _persist_skipped_disposition
                # （item 4d50570fd394），文案与字段不变。
                self._persist_skipped_disposition(
                    signal,
                    (
                        "夜间断窗/瞬断冻结避让，跳过 Administrator 唤起"
                        f"（{_reason_text}）——实际未派发，留待下一轮"
                        "盘点/检测循环自然重试"
                        "（evo-add-night-window-inflight-guard）"
                    ),
                    error_label="window-avoidance",
                )
            # code-review item 05825b6fe4e0：向调用方回传「未送达」——否则
            # 被断窗跳过的修订告警到窗末/下一轮盘点仍不再成条，违背上方
            # 「留待下一轮盘点/检测循环自然重试」文案的承诺。
            return False

        # 巡检线程 MUST NOT 同步等待 admin run：处置实测可跑百轮/小时级（152
        # 轮/63 分钟），同步执行会令 run_once 同线程的 code-review stall 检查、
        # 审查 run 看门狗等全部检查点在处置期间整体停摆。与
        # _run_code_review_checkpoint 同形态经 ``_code_review_executor`` 投递
        # 后台 worker 执行完整唤起+落痕；executor 不可用（测试/禁用态）回退
        # 同步执行（行为不变，保逃生门）。多 worker 并行处置为 fenixd D6 既有
        # 决策（不建 worktree、容忍主树写冲突风险）；节流锚点与在飞互斥守卫
        # 仍由调用方在投递前的调用线程完成。
        def _worker():
            try:
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

                # fix-global-signal-choice-execution 2.2：choice 执行结果前置——
                # 在处置留痕与终态回写判定之前执行 choice。原序（先回写后执行）
                # 会把尚未执行/注定失败的 choice 当已闭环收口（2026-10-02
                # ce27a93f9dca：retry_review 执行报错的同一秒信号已被记
                # handled=true/resolved）。执行失败/全局跳过时终态回写被收紧
                # 拦截，信号保留待重审。
                choice_outcome = self._apply_choice_execution(signal, disp)
                choice_failed = (
                    choice_outcome is not None and not choice_outcome.get("ok")
                )
                # evo-add-admin-orphan-disposition-effect-check 2.1（小步落账）：
                # choice 动作执行完即落逐动作 DISPOSITION 事件并（整体 ok 时）
                # 提前收口信号——缩短「执行成功→落账」窗口，run 在 final 落账
                # 前死亡不再丢失已执行事实。失败/跳过不预写 resolved（2.2
                # fail-closed 红线，见方法 docstring）。
                self._persist_choice_step_records(signal, signal_rec, disp, choice_outcome)
                # 处置记录 error 并入 choice 执行失败/跳过原因（2.2 留痕可溯源）
                disp_error = disp.error or ""
                if choice_failed:
                    _cnote = str(choice_outcome.get("error") or "执行失败")
                    _caction = (
                        choice_outcome.get("action")
                        or getattr(disp, "choice_id", "")
                        or ""
                    )
                    disp_error = (
                        (f"{disp_error}；" if disp_error else "")
                        + f"choice 执行未生效（{_caction}）：{_cnote}"
                    )

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
                            "error": disp_error,
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

                # 终态回写（evo-signal-preprobe-handled-writeback R5）：处置 run 写入
                # 非 pending 的最终处置结果后，回写对应信号 handled=true——原信号不再
                # 永挂未处理（此前 mark_signal_handled 仅有 dashboard 人工 alert-resolve
                # 调用方，处置 run 自动链路上无人回写）。三类豁免：escalate=true 属
                # 升级人工（人工处置是唯一出路，由人工 alert-resolve 闭环）；人工显式
                # 触发路径 signal_rec=None 无关联记录，跳过；success=False 的处置
                # （code-review item 14ce3542d2b9）不回写——run 失败/产物硬门拦截时
                # result 是框架兜底的 "failed"（零动作），只看 result 会把这类失败
                # 终态也当处置完成回写 handled，信号被零动作误闭环且不再升级；管理员
                # 显式宣告 failed（success=True、有真实动作）照常回写。getattr 保底
                # True 仅为替身兼容（真实 AdminDisposition 恒有 success，同上方
                # failure_evidence 类型守卫动机）。回写失败仅记警告日志，
                # 不阻塞处置结果落盘。
                # fix-global-signal-choice-execution 2.2：choice 执行失败/全局
                # 跳过（choice_failed）时本门收紧——不回写 handled=true/resolved，
                # 信号保留待重审，另走下方失败留痕分支（result=failed + 动作名，
                # handled=False 形态写入）。
                if (
                    disp.result
                    and disp.result != "pending"
                    and not disp.escalate
                    and getattr(disp, "success", True)
                    and signal_rec is not None
                    and not choice_failed
                ):
                    try:
                        if self.store.mark_signal_handled(
                            signal_rec.get("id"),
                            action_taken=(
                                choice_outcome.get("action")
                                if choice_outcome is not None
                                else None
                            ),
                            result=(
                                "resolved" if choice_outcome is not None else None
                            ),
                        ):
                            self.logger.info(
                                "admin_monitor",
                                f"处置终态（result={disp.result}）已回写信号 handled=true"
                                f"（id={signal_rec.get('id')}，"
                                f"{signal.get('signal_type')}）",
                            )
                    except Exception as e:
                        self.logger.warning(
                            "admin_monitor",
                            f"处置终态回写信号 handled 失败（不阻塞处置结果落盘）: {e}",
                            {"record_id": signal_rec.get("id"), "run_id": disp.run_id},
                        )
                elif choice_failed and signal_rec is not None:
                    # fix-global-signal-choice-execution 2.2：告警记录留痕但
                    # 不闭环（handled 不置位，信号保留待重审）——失败原因已在
                    # 处置记录 error 字段与上方 ERROR/INFO 日志留痕。
                    try:
                        self.store.mark_signal_handled(
                            signal_rec.get("id"),
                            action_taken=(
                                choice_outcome.get("action")
                                or getattr(disp, "choice_id", "")
                                or None
                            ),
                            result="failed",
                            handled=False,
                        )
                    except Exception as e:
                        self.logger.warning(
                            "admin_monitor",
                            f"choice 失败留痕写告警记录失败（不阻塞处置收尾）: {e}",
                            {"record_id": signal_rec.get("id"), "run_id": disp.run_id},
                        )

                # family_explosion 处置：Administrator「放行一次」→ 设置父 SPEC 豁免位
                # （fix-family-convergence-governor / design D4）。结构字段优先级最高；
                # 文本动作（放行 / _family_waiver / waive）兜底，兼容自由文本处置。
                self._apply_family_waiver(signal, disp)

                # infra 回拨处置（evo-infra-failure-budget-exempt R3）：Administrator
                # 文本显式声明「回拨 N 轮」→ 从 _verify_fail_rounds 减回误计入的
                # infra 轮次并解冻（幂等，审计留痕 admin_store DISPOSITION）。
                self._apply_infra_reclassification(signal, disp)

                # add-human-adjudication-choices 4.2 的 choice 执行已前置到处置
                # 留痕之前（fix-global-signal-choice-execution 2.2：执行结果并入
                # 终态回写判定），此处不再重复执行。

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
            except Exception as e:  # noqa: BLE001 — 后台 worker 兜底，异常不随线程静默
                self.logger.error(
                    "admin_monitor",
                    f"Administrator 后台处置异常（唤起/落痕）: {e}",
                )

        if self._code_review_executor is not None:
            try:
                self._code_review_executor.submit(_worker)
            except Exception as e:
                # 投递失败（executor 已 shutdown 等）回退同步执行：唤起不丢，
                # 对齐 executor 不可用分支的逃生门口径
                self.logger.error(
                    "admin_monitor",
                    f"Administrator 处置后台投递失败，回退同步执行: {e}",
                )
                _worker()
        else:
            # executor 不可用（测试/禁用态）：同步执行（行为不变，保逃生门）
            _worker()

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
        entry["next_retry_at"] = from_epoch(next_retry).isoformat()
        entry["retry_count"] = 0

    def _close_dispatch_failures_on_success(self, signal: dict) -> None:
        """dispatch 成功（run_administrator 正常返回）→ 关闭未处理的
        派发失败升级记录（admin-dispatch-failure-escalation D2）。

        仅关闭带 next_retry_at 字段的未处理 kind=escalation 记录（两条分流
        路径：admin_dispatch_programming_error 与原类型记录均带该字段；手动
        唤起的记录不带，天然不关）；其他升级记录（人工处置中/其他原因）不受
        影响。闭环发生在 dispatch 时刻，不扩 alert_lifecycle._SIGNAL_CONDITIONS。

        spec 路径按 spec 名下过滤；daemon 级路径（spec=None，如 daemon_errors）
        按重派链携带的 _dispatch_retry_id 精确闭环对应记录——否则重派成功
        不闭环，_retry_due_dispatch_failures 每轮巡检都会命中该到期记录，
        无限重复唤起 Administrator（code-review 58c9fd5dfeb9）。
        """
        spec = signal.get("spec")
        if not spec:
            # daemon 级记录 spec 恒为 None，无法按 spec 过滤闭环；改按
            # 记录 id 闭环（重派链信号必带 _dispatch_retry_id）。此处先
            # 复核派发失败记录口径（kind=escalation ∧ 未 handled ∧ 带
            # next_retry_at，与 spec 路径 close_dispatch_failure_alerts
            # 的过滤集一致），再经 auto_resolve 写 handled_by="auto-resolve"
            # + resolve_note，与 spec 路径闭环形态同形。
            retry_id = signal.get("_dispatch_retry_id")
            if not retry_id:
                return
            try:
                rec = next(
                    (r for r in self.store.read_all() if r.get("id") == retry_id),
                    None,
                )
            except Exception as e:
                self.logger.error(
                    "admin_monitor",
                    f"Failed to read dispatch-failure escalation {retry_id}: {e}",
                )
                return
            if (
                rec is None
                or rec.get("kind") != ESCALATION
                or rec.get("handled")
                or not rec.get("next_retry_at")
            ):
                return
            try:
                closed = self.store.auto_resolve(
                    [{"id": retry_id, "resolve_note": "后续派发成功"}]
                )
                if closed:
                    self.logger.info(
                        "admin_monitor",
                        f"Dispatch succeeded for daemon-level signal "
                        f"{signal.get('signal_type')}, closed dispatch-failure "
                        f"escalation {retry_id}",
                    )
            except Exception as e:
                self.logger.error(
                    "admin_monitor",
                    f"Failed to close dispatch-failure escalation {retry_id}: {e}",
                )
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
        recommended_action/evidence，store 读侧已把 evidence 归一为
        字符串，与首次派发 _make_signal 形态一致）。原信号 signal_type
        必须存在（否则判定解析失败返回 None，跳过该条记录）。
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
        # code-review b61e0c5a7387：补齐 evidence——升级记录两条分流路径落库
        # 均保留 evidence（原始型存原信号 evidence 串；编程错误型存含异常
        # 类型/消息/调用点的 JSON 串，store 读侧已归一为字符串），缺失时
        # 重派 run 的 {evidence} 占位符被填成空串，Administrator 看不到
        # 原始失败证据（排障主线索）。
        signal.setdefault("evidence", rec.get("evidence"))
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
        # 守卫半段（code-review 9e2916c4f8cf）：read_one / resolve_env_blocked_
        # reset_path 的编程错误（TypeError/AttributeError 等签名漂移形态）同样
        # 属 D3「复位路径编程错误必升级」口径——裸调在 try 之外时只会被
        # _invoke_administrator 外层通用兜底吞成一行 ERROR，复位静默失败、
        # spec 滞留原状态。编程错误走同一 critical 升级（reset_path 记为
        # guard，标注失败落在守卫半段），运维类异常仍走既有 WARNING 语义。
        try:
            spec_entry = sm.read_one(spec)
            if not spec_entry:
                return
            reset_path = resolve_env_blocked_reset_path(spec_entry, self.project_root)
        except (TypeError, AttributeError, NameError) as pe:
            self._escalate_reset_programming_error(pe, signal, "guard")
            return
        except Exception as e:
            self.logger.warning(
                "admin_monitor",
                f"env 阻塞处置复位守卫读取失败 '{spec}': {e}",
            )
            return
        if reset_path is None:
            return
        # fix-recovery-path-blockers D2（code-review 195f2fa7ddef）：与
        # _reset_orphaned_after_disposition 同款在飞互斥——同 spec 任意
        # signal_type 已有在飞/待派发 admin 处置（正在写 STATE/
        # test_scenarios.json）时，本复位（transition + 清 error）与 verifier
        # 重验会与之互相踩踏、重验可能读到半成品场景文件。命中 → 记 INFO
        # 跳过本次复位（保持原状态、MUST NOT 写额外状态），在飞 run 收尾后
        # 下一巡检周期自然重评。本 run 自身刚落盘的 final 处置记录非 pending，
        # 不会自证在飞（_merge_admin_runs 组内非 pending 即 final）。
        if self._has_active_admin_run_for_spec(spec):
            self.logger.info(
                "admin_monitor",
                f"env 阻塞处置复位跳过 '{spec}': admin 处置在飞，"
                f"复位/重验派发互斥（fix-recovery-path-blockers D2）",
            )
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
                    # verify 单飞守卫（evo-add-verify-dispatch-single-flight 1.2）：
                    # 本复位直通道经 handle_event("spec_implemented") 汇聚
                    # _on_spec_implemented → _enqueue，未引入旁路入队——同 spec
                    # 在飞验证时的重复入队由 _enqueue/_enqueue_front/出队分流的
                    # verify_single_flight 守卫拒绝并结构化留痕；在飞 run 收工后
                    # 重试本处置即显式放行（合法重验不被阻塞）。
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
          重派前复核在飞 in-process 验证（inprocess_verify_active），命中即
          跳过本次重派（复位语义保留，evo-inprocess-verify-activity-signal
          1.3——本出口不经 spec_is_undriven，须单独堵口）；
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
        # 守卫半段（code-review 9e2916c4f8cf）：同 _reset_env_blocked_after_
        # disposition——read_one/状态读取的编程错误（TypeError/AttributeError
        # 等签名漂移形态）走 D3 critical 升级（reset_path 记为 guard），不被
        # 外层通用兜底吞掉；运维类异常仍走既有 WARNING 语义。
        try:
            spec_entry = sm.read_one(spec)
            if not spec_entry:
                return
            status = spec_entry.get("status")
        except (TypeError, AttributeError, NameError) as pe:
            self._escalate_reset_programming_error(pe, signal, "guard")
            return
        except Exception as e:
            self.logger.warning(
                "admin_monitor",
                f"孤儿状态处置复位守卫读取失败 '{spec}': {e}",
            )
            return
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
                # 在飞 in-process 验证复核（evo-inprocess-verify-activity-signal
                # 1.3，第三放大器出口）：本直通道不经 spec_is_undriven，2026-10-02
                # cimbar-airgap-transfer 09:58:19Z 第三批重派即来源于此。验证在飞
                # 时跳过本次 handle_event 重派——在飞验证本身即重验，其结果路径
                # 照常推进状态；复位语义保留（下方 transition_gate 幂等 + 清
                # error 照常执行）。MUST NOT 设延迟队列或新增状态：处置复位经
                # _apply_choice_execution 单次消费、无重扫回放机制，「延后重派」
                # 无人触发；且在飞验证收尾后再派会重新制造重复批。
                verify_inflight = inprocess_verify_active(self.project_root, spec)
                # fix-observability-gaps 2.1：transition_gate 带 context（恢复来源；
                # 正常路径为幂等 old==new，state_machine 幂等分支不产生日志；
                # 兜底真实转换时也带上恢复来源）
                sm.transition_gate(
                    spec, "testing",
                    trigger_run_id=None, agent_type=None, channel="recovery",
                )  # 幂等（already testing）
                sm.update_spec(spec, {"error": None})
                if self.pm_engine is not None:
                    if verify_inflight:
                        self.logger.info(
                            "admin_monitor",
                            f"孤儿 testing 复位 '{spec}': in-process 验证在飞，"
                            "跳过本次 verifier 重派（在飞验证本身即重验，"
                            "evo-inprocess-verify-activity-signal 1.3）",
                        )
                    else:
                        self.pm_engine.handle_event("spec_implemented", spec, spec_entry)
                self.logger.info(
                    "admin_monitor",
                    f"孤儿 testing 复位：'{spec}' transition_gate(testing)幂等"
                    " + verifier 入队重验",
                )
            except (TypeError, AttributeError, NameError) as pe:
                # 编程错误升级（code-review fbb968de7b0e，对齐
                # _reset_env_blocked_after_disposition 的 D3 分流）：三类异常是
                # 代码缺陷典型签名，只记 WARNING 会让孤儿 spec 停留原状态、冷却
                # 过期后 orphaned_state 重新成条再唤起、再次复位失败——每冷却
                # 周期空转一次 admin run 且无 critical 提示。落 critical 告警
                # （_escalate_reset_programming_error 内 unhandled_for 去重）。
                self._escalate_reset_programming_error(pe, signal, "testing")
            except Exception as e:
                # 运维失败（OSError/子进程/网络）保持既有 WARNING 语义，不升级
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
            except (TypeError, AttributeError, NameError) as pe:
                # 编程错误升级（同 testing 分支，code-review fbb968de7b0e）
                self._escalate_reset_programming_error(pe, signal, "ready")
            except Exception as e:
                # 运维失败保持既有 WARNING 语义，不升级
                self.logger.warning(
                    "admin_monitor",
                    f"孤儿 implementing 复位失败 '{spec}': {e}",
                )
        else:
            self.logger.debug(
                "admin_monitor",
                f"孤儿信号但 spec '{spec}' 状态 {status} 无需复位（可能已被处置）",
            )

    def _apply_choice_execution(self, signal: dict, disp) -> "dict | None":
        """Administrator 处置 choice_id 非空 → 执行注册表动作映射（4.2）。

        与人工 alert-resolve 端点共用 ``execute_adjudication_choice``：同一
        动作映射、同一留痕格式。执行结果只记审计日志（最终 DISPOSITION
        记录已含 choice_id 留痕，动作步骤入日志 context）；执行失败记
        ERROR 不阻塞后续收尾（escalation 闭环 / 升级告警），失败状态由
        日志与既有告警面呈现。

        fix-global-signal-choice-execution 2.1/2.2：返回执行结果 dict 供终态
        回写判定——``{"ok": bool, "action": str|None, "error": str|None,
        "skipped": bool}``；未尝试执行（choice_id 为空 / 无关联 spec）返回
        None。全局信号（spec 为空或占位 'global'）的 spec_scoped choice 在此
        提前跳过并留 INFO（与上方『无关联 spec 跳过』分支同型；执行器守卫
        1.2 为正确性兜底），跳过形态返回 ok=False + skipped=True——信号保留
        待重审，不闭环。
        """
        choice_id = str(getattr(disp, "choice_id", "") or "").strip()
        if not choice_id:
            return None
        spec = signal.get("spec") or disp.spec
        # fix-global-signal-choice-execution 2.1：全局信号 × spec_scoped choice
        # 提前跳过（双层设防的消费端一层），避免无谓执行报错；INFO 留痕。
        # 守卫须先于『无关联 spec 跳过』分支——spec 为空同样属全局形态，此
        # 形态下 spec_scoped choice 的跳过 MUST 以 not-ok 结果上报（拦截终态
        # 回写，信号保留待重审），不能走 None 短路被回写门视为已执行成功。
        # 未知 choice_id 不在此拦截——交执行器报非法 choice（走失败留痕）。
        _resolved_choice = None
        try:
            from core.dashboard.data.adjudication_choices import (
                is_global_spec,
                resolve_choice,
            )

            _resolved_choice, _resolve_reason = resolve_choice(
                choice_id, str(signal.get("signal_type") or "")
            )
            # scoped-no-reverse（未注册 signal_type 的 spec_scoped 动作被反查
            # 收紧拒解析）同属作用域拒入形态——全局信号照此提前跳过
            _globally_scoped = bool(
                is_global_spec(spec)
                and (
                    (
                        _resolved_choice
                        and _resolved_choice.get("spec_scoped", True)
                    )
                    or _resolve_reason == "scoped-no-reverse"
                )
            )
        except Exception as e:  # noqa: BLE001 — 守卫不可用不阻塞执行（执行器兜底）
            self.logger.debug(
                "admin_monitor",
                f"choice 作用域预判不可用（执行器守卫兜底）: {e}",
            )
            _resolved_choice = None
            # code-review d5edc8ac335e：降级分支对全局形态 spec（空值或占位
            # 'global'，同 is_global_spec 口径）保守沿用 not-ok skipped 语义，
            # 与非降级路径 fail-closed 方向一致——否则空 spec × spec_scoped
            # choice 会落入下方「无关联 spec」分支返回 None，终态回写门把
            # None 视为未执行无阻塞、信号按 resolved 收口，违背 docstring 的
            # fail-closed 承诺（该形态下执行器守卫兜底不被触达）。具体 spec
            # 不受影响，照常放行执行器兜底。占位常量复用本模块既有定义
            # （导入失败场景不能依赖 adjudication_choices 的
            # GLOBAL_SPEC_PLACEHOLDER）。
            _spec_form = str(spec or "").strip().lower()
            _globally_scoped = (
                (not _spec_form)
                or _spec_form == _ORPHAN_GLOBAL_SPEC_PLACEHOLDER
            )
        if _globally_scoped:
            self.logger.info(
                "admin_monitor",
                f"处置 choice_id={choice_id} 为 spec 作用域动作，全局信号"
                f"（spec={spec!r}）无 spec 可操作，跳过执行（信号保留待重审）",
            )
            return {"ok": False, "skipped": True,
                    # 未注册 signal_type 的 scoped 动作被反查收紧拒解析，动作名
                    # 以 choice_id 兜底（留痕 action_taken 不缺位）
                    "action": ((_resolved_choice or {}).get("action") or choice_id),
                    "error": (f"全局信号（spec={spec!r}）不可执行 spec 作用域"
                              f"动作，已跳过")}
        if not spec and not (
            _resolved_choice and not _resolved_choice.get("spec_scoped", True)
        ):
            # 无关联 spec（信号与处置记录均空）且动作语义需要具体 spec
            # （spec_scoped / 注册表未知 id）——跳过执行。非作用域动作放行
            # （1.3：全局/空 spec 信号的非作用域收口不断路，执行器守卫 1.2
            # 兜底正确性）。
            self.logger.warning(
                "admin_monitor",
                f"处置 choice_id={choice_id} 无关联 spec，跳过执行",
            )
            return None
        # 依据原文随执行留痕（截断防日志膨胀；完整依据已在 DISPOSITION 记录）
        basis = str(getattr(disp, "actions_taken", "") or "")[:200]
        # 陈旧代码预检（evo-add-key-path-stale-code-preflight 2.3）：choice 执行
        # 前查询进程代码陈旧旗标；陈旧则请求重启（一条 WARNING + daemon 侧
        # .fenix/restart_request 防重）并照常执行——执行结果与留痕不受预检影响。
        # 导入/调用与相邻 adjudication_choices 导入同款受守卫（code-review item
        # 17d5aecc7009）：异常按失败留痕上报（ok=False），不穿透本函数令终态
        # 回写与失败留痕双双缺席（pending 处置记录滞留孤儿）。
        try:
            from core.code_stale_flag import request_restart

            request_restart(
                lambda msg: self.logger.warning("admin_monitor", msg),
                "admin 处置 choice 执行",
            )
        except Exception as e:  # noqa: BLE001 — 预检失败按失败留痕，不穿透
            self.logger.error(
                "admin_monitor",
                f"陈旧代码预检（request_restart）异常 choice_id={choice_id} "
                f"spec='{spec}': {e}",
            )
            return {"ok": False, "action": None,
                    "error": f"陈旧代码预检异常: {e}"}
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
            # fix-global-signal-choice-execution 2.2：异常按失败上报——终态回写
            # 被拦截（fail-closed，信号保留待重审）
            return {"ok": False, "action": None, "error": f"choice 执行异常: {e}"}
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
        return {"ok": bool(result.get("ok")), "action": result.get("action"),
                "error": result.get("error"),
                "steps": result.get("steps") or []}

    def _persist_choice_step_records(self, signal: dict, signal_rec, disp,
                                     choice_outcome) -> None:
        """结构化 choice 通道小步落账（evo-add-admin-orphan-disposition-effect-check 2.1）。

        choice 执行返回后、final append 前落一条逐动作 DISPOSITION 事件
        （含 action_taken 与结果）：run 在 final 落账前死亡时已执行事实不丢
        （「执行成功→落账」窗口从秒级收敛到零）。两条硬约束：

        - 事件 MUST NOT 携带 admin_run_id（循 _close_signal_preprobed 无
          run_id 留痕先例）——携带会被 _merge_admin_runs 并入本组使组提前
          final，破坏「在飞 = has_pending 且非 final」判据（
          _spec_has_active_admin_run 的重派/节流护栏失守）；
        - 提前收口以 choice 整体执行 ok 为准（outcome["ok"]=True 才
          mark_signal_handled(result="resolved")），不按单动作成功收口；
          任一步骤失败（整体非 ok）不收口、不预写 resolved（保
          evo-fix-global-signal-choice-execution 2.2「信号保留待重审」的
          fail-closed 语义），失败形态落 result=failed 审计事件（非
          resolved，不触发任何回写门/静默期语义）。全局跳过形态
          （skipped=True）未执行任何动作，不落事件。

        落账/收口失败仅记日志，不阻塞 final 落账主链路。
        """
        if choice_outcome is None or choice_outcome.get("skipped"):
            return
        ok = bool(choice_outcome.get("ok"))
        action = (
            choice_outcome.get("action")
            or str(getattr(disp, "choice_id", "") or "")
            or ""
        )
        try:
            self.store.append(
                {
                    "kind": DISPOSITION,
                    "signal_type": signal.get("signal_type"),
                    "spec": signal.get("spec") or disp.spec,
                    "severity": signal.get("severity"),
                    "description": disp.problem or signal.get("description") or "",
                    "action_taken": action,
                    "result": "resolved" if ok else "failed",
                    "error": "" if ok else str(choice_outcome.get("error") or "执行失败"),
                    # 刻意不携带 admin_run_id：见 docstring 硬约束①
                }
            )
        except Exception as e:
            self.logger.error(
                "admin_monitor",
                f"choice 逐动作小步落账写入失败（不阻塞 final 落账）: {e}",
            )
        if not ok:
            return
        if signal_rec is not None:
            try:
                if self.store.mark_signal_handled(
                    signal_rec.get("id"),
                    action_taken=action,
                    result="resolved",
                ):
                    self.logger.info(
                        "admin_monitor",
                        f"choice 整体执行 ok，已提前收口信号 handled=true"
                        f"（id={signal_rec.get('id')}，"
                        f"{signal.get('signal_type')}，action={action}）",
                    )
            except Exception as e:
                self.logger.warning(
                    "admin_monitor",
                    f"choice 提前收口信号失败（不阻塞 final 落账）: {e}",
                    {"record_id": signal_rec.get("id"), "run_id": disp.run_id},
                )

    def _apply_family_waiver(self, signal: dict, disp) -> None:
        """family_explosion 处置「放行一次」→ 设置父 SPEC 豁免位 _family_waiver=true。

        判定：结构字段 disp.family_waiver 为 True；或自由文本
        actions_taken/summary/recommended_action/problem 含显式放行语义（赋值型
        _family_waiver=true、「设置 _family_waiver 为 true」「放行一次」等），
        且不含否定短语（未放行/不再放行/不发放/暂不发放…）。放行模式按句
        判定，命中句须为本次处置的显式放行表述（含「本次/该族」限定词或与本
        spec 名同现）——仅叙述中提及豁免位字面令牌、他族谱或历史放行不构成
        放行。豁免位由 pm_engine 族谱门在下一轮实际创建工作开始时消费并复位
        （单次）。
          仅 result=resolved/partially-resolved 时触发（处置未成功不执行），
        对齐 ``_apply_infra_reclassification`` 的 result 闸门——失败 run 已落盘
        的放行表述不构成放行指令。

        Args:
            signal: 本次唤起信号 dict（含 signal_type/spec）。
            disp: AdminDisposition 处置结果。
        """
        if getattr(disp, "result", None) not in ("resolved", "partially-resolved"):
            return
        if signal.get("signal_type") != "family_explosion":
            return
        spec = signal.get("spec")
        if not spec:
            return
        # problem 字段一并纳入（code-review item 6621319f7aae）：与
        # _apply_infra_reclassification 的文本兜底四字段拼装对齐——Administrator
        # 可能把「放行一次」表述写进 problem，缺该字段时文本兜底识别不到，
        # 豁免位不落、父 SPEC 派生口子不开（漏放行方向）。
        text = (
            f"{(disp.actions_taken or '')}\n{(getattr(disp, 'summary', '') or '')}\n"
            f"{(disp.recommended_action or '')}\n{(getattr(disp, 'problem', '') or '')}"
        )
        # 否定语义优先：任何位置出现否定短语即不放行（保守方向：宁可漏放行、
        # 不可给未放行的父 SPEC 错开派生口子）。结构字段 family_waiver=True
        # 优先级最高（Administrator 结构化回填不受文本兜底影响）；文本兜底
        # 判定（否定拦截 + 分句放行模式 + 赋值型同句兜底）单源在
        # admin_monitor_text_rules.family_waiver_granted。
        if bool(getattr(disp, "family_waiver", False)):
            waived = True
        else:
            waived = family_waiver_granted(text, spec)
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

        判定（对齐 ``_apply_family_waiver`` 文本识别范式）：
          - 结构字段 ``disp.infra_reclassify_rounds`` > 0 优先级最高；
          - 否则文本兜底：actions_taken / summary / recommended_action 含
            「回拨 N 轮」/「reclassify N rounds」等显式回拨语义，且不含否定短语；
            命中句须含「本次」类限定词或与本次 spec 名同现（与
            family_waiver_granted 同范式，历史/他 spec 回拨叙述不构成回拨指令）。
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
            # ── 文本模式兜底（否定拦截 + 模式匹配判定单源在
            # admin_monitor_text_rules，本处只承载拦截日志）──
            text = (
                f"{(disp.actions_taken or '')}\n{(getattr(disp, 'summary', '') or '')}\n"
                f"{(disp.recommended_action or '')}\n{(getattr(disp, 'problem', '') or '')}"
            )
            if is_reclassify_negated(text):
                self.logger.info(
                    "admin_monitor",
                    f"infra 回拨被否定短语拦截 '{spec}'（保守不触发回拨）",
                )
                return
            n = infra_reclassify_rounds(text, spec)
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
            self.logger.info(
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

        口径为 classify_run 的**子集**（code-review item dff59c9ccf3d）：仅按
        末行 type=result→done / type=error→error 二分，其余一律 running——
        classify_run 的完整终态集（interrupted/cancelled/superseded 等）在此
        不区分、全落 running。当前唯一消费方 _detect_repeated_failures 只认
        error，不受影响；复用做通用终态判定前须按此子集口径复核。与
        classify_run 一致的只是「尾部窗口取末行完整事件」的读取范式，避免
        跨层 import dashboard。
        """
        # code-review item a10425b71546：尾读窗口对齐 liveness._TAIL_READ_WINDOW
        # （模块顶部单源 import 的 _RUN_TAIL_READ_WINDOW，64KB）——旧值 4096 下，
        # 末条 JSON 事件（如携带长 stderr 摘录的 error 终态行）自身超窗时 seek
        # 落点在该行内部，该行被当截断首行丢弃/解析失败，last 退化为更早的完整
        # 事件，已失败 run 被误判 running/empty，_detect_repeated_failures 漏计
        # 失败次数（repeated_failures 信号在该形态下失明）。不复用
        # _file_tail_is_terminal：其只返回「末行是否终态」的 bool，区分不了
        # error/done（本方法的返回值语义），故只对齐窗口口径。
        try:
            size = run_file.stat().st_size
            first_line_truncated = False
            with run_file.open("rb") as f:
                if size > _RUN_TAIL_READ_WINDOW:
                    start = size - _RUN_TAIL_READ_WINDOW
                    # 边界判定（code-review item 190881dd0168，同
                    # _read_tail_error_entries 的 96293d84951d 修正）：回看
                    # start 前一字节，恰为换行符说明 start 本身是完整行的
                    # 起点——该完整行必须保留解析（若它是尾部唯一终态 error
                    # 事件，误丢会让 last 退化到更早事件、已失败 run 被误判
                    # running）；仅 mid-line 切入时才丢截断残行。读完这一字节
                    # 后文件指针恰停在 start，下方 f.read() 仍从 start 起读。
                    f.seek(start - 1)
                    first_line_truncated = f.read(1) != b"\n"
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            return "empty"
        last = None
        # 仅 seek 分支且 mid-line 切入时，窗口首行是从字节窗口切入的上一行
        # 残段，必须丢弃（对齐 liveness _file_tail_is_terminal 与 dashboard
        # _read_run_lines 读取范式）；边界恰落行首或 size <= 窗口（全量读）
        # 时首行完整，保留。
        lines = tail.split("\n")
        if first_line_truncated:
            lines = lines[1:]
        for line in lines:
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

    # ── 每轮扫描缓存（code-review item cfa277dc36e7）────────────

    def _round_runs_activity(self) -> dict:
        """本轮 runs 目录活跃快照（spec → 最近 mtime），轮首失效、轮内惰性构建。

        _detect_stuck 与 _detect_orphaned_state 共用同一次 glob+stat，替代
        逐 spec 全量扫描（O(spec 数 × run 文件数) → O(run 文件数)）；失效由
        run_once 轮首复位承担（生命周期不跨轮）。半初始化实例（测试用
        __new__ 绕过 __init__）与未过 run_once 的直接调用经 getattr 兜底。
        """
        snap = getattr(self, "_runs_activity_cache", None)
        if snap is None:
            snap = self._runs_activity_cache = _build_runs_activity_snapshot(
                self.project_root
            )
        return snap

    def _round_pgrep_cache(self) -> dict:
        """本轮 pgrep 结果缓存（spec → bool），轮首失效；同轮内同 spec 幂等。"""
        cache = getattr(self, "_pgrep_round_cache", None)
        if cache is None:
            cache = self._pgrep_round_cache = {}
        return cache

    def _has_recent_progress(self, spec: str, now: float, window: float) -> bool:
        """该 spec 是否存在窗口内有写活动的 run 文件（有进度）——非 admin 前缀。

        fix-recovery-path-blockers D1：与模块级 `_has_recent_spec_run` 同语义，
        排除 `admin-` 前缀（`_is_admin_run_id` 单点判定）——Administrator 的
        处置 run 是处置者的活动，不是被处置 SPEC 的驱动证据。

        code-review item 43b4ca8a059e：扫描本体已并入模块级
        `_has_recent_spec_run` 单一实现，本方法仅做参数适配（直接传
        project_root，勿从 runs_dir 路径组件反推），勿再复制第二份扫描体。
        """
        return _has_recent_spec_run(self.project_root, spec, now, window)

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
                # 与 store 层落盘口径一致（AdminStore._write_unlocked 同款）：
                # flush+fsync 后才 replace，崩溃不丢最近一轮 flapping 历史
                # （写盘仅发生在边界时刻，开销可忽略）。
                f.flush()
                os.fsync(f.fileno())
            tmp_path.replace(self._history_path)
            # rename 后刷父目录项（_write_unlocked 同款收尾）：目录项变更落盘，
            # 掉电重启后不整体回退为旧历史
            _fsync_parent_dir(self._history_path)
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
            # code-review f9814702b128：rec 为 dict 但缺 "changes" 键或值为
            # null/非列表（手工编辑、旧版本残留）时，原样透传会在下方
            # append/迭代处 AttributeError/TypeError，沿 _detect_flapping
            # 中断整轮信号检测——非 list 一律按空历史处理（读侧对空
            # changes 本就跳过，口径一致；本轮回写即洗成合法形状）。
            raw_changes = rec.get("changes") if isinstance(rec, dict) else None
            changes = raw_changes if isinstance(raw_changes, list) else []
            if last_status is not None and last_status != status:
                changes.append([now, status])
                changed = True
            elif not rec:
                changed = True
            elif not isinstance(rec, dict) or rec.get("inactive_since") is not None:
                # 暂离归来：重写记录时丢弃过期计时戳（一次性写盘）
                changed = True
            elif last_status is None:
                # code-review 69e57a219b75：rec 为 dict 且含合法 changes 但缺
                # last_status（手工编辑、旧版本残留）时，上方三分支均不置
                # changed——内存中已重建的合法形态（见下方 history[name] = ...）
                # 不落盘，下一轮重读仍是畸形形状，该 spec 后续真实状态切换持续
                # 被当首见建档漏记（flapping 失明），直到另一 spec 恰好触发写盘
                # 才自愈。此处置位使修复形态当轮落盘（与其他守卫分支同款的一次性
                # 自愈写盘，不破坏「写盘只发生在边界时刻」口径）。
                changed = True
            # code-review 9063aad172d4：裁剪不再只挂在追加分支——每轮对读到的
            # changes 统一按 cutoff 过滤后再回写，spec 长期停留同一状态时旧条目
            # 同样被 24h 窗淘汰。过滤为空转（未删任何条目）时 changed 不置位，
            # 不产生额外写盘，维持「写盘只发生在边界时刻」的口径。
            # code-review e459e98bf6f8：与 _detect_flapping 读侧形状守卫
            # （f67ba8199742）口径对齐——历史文件被手工编辑或旧版本残留出
            # 畸形条目（非二元 list/tuple 或时间戳非数值）时直接淘汰，
            # 避免 c[0] TypeError 沿 _detect_flapping 中断整轮信号检测。
            pruned = [
                c
                for c in changes
                if isinstance(c, (list, tuple))
                and len(c) == 2
                and isinstance(c[0], (int, float))
                and c[0] >= cutoff
            ]
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
