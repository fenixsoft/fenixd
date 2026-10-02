# 验证报告：add-mergeback-wip-active-coordination

> ⚠️ 本报告由框架于 2026-09-25T07:34:26Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-25T07:34:26.773256+00:00

## 结论：✅ 通过（verified）

**状态：verified — 20/20 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 20/20 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 20 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.88M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| wipc-identify-holder-implementer | 占用者识别正向路径：主树 WIP overlap 文件与在飞 implementer 车道分支改动集求交命中 → 判为在飞持有者，run/spec/分支/命中文件全部可追溯、describe 含「占用者=在飞车道」（SPEC Requirement 占用者识别 Scenario 在飞持有者被识别；tasks 3.1a；出处 core/worktree_manager/mergeback.py:586 identify_wip_occupant、tests/test_mergeback_wip_coordination.py:181） | pass | 0/3 | - |
| wipc-identify-holder-codefix-bridge | code-fix 车道识别：code-fix run_id 无 spec 段，经固定 spec 名桥接（code-fix-* → code-review-fix）同样可被识别为在飞持有者（design D1 覆盖双实现车道；出处 core/worktree_manager/mergeback.py:584 _LANE_RUN_SPEC_BRIDGE、tests/test_mergeback_wip_coordination.py:197） | pass | 0/3 | - |
| wipc-identify-orphan-zero-hit | 无主陈旧 WIP 识别：overlap 文件不在任何在飞车道分支改动集（零命中）、以及无任何在飞 run 两形态 → 均判无主，describe/to_dict 携带 D1 已知盲区注记（admin/人工会话主树直改形态按无主走宽限升级）随识别结果留痕（SPEC Requirement 占用者识别 Scenario 无主陈旧 WIP 被识别；出处 core/worktree_manager/types.py:26 BLIND_SPOT_NOTE、tests/test_mergeback_wip_coordination.py:207、:221） | pass | 0/5 | - |
| wipc-event-retry-on-terminal | 事件驱动合回重试主路径：被挡批识别出在飞持有者即注册其 run 终态监听（不立即触发）；持有者 run 终态事件到达后秒级（<5s，不等待轮询周期）重试合回，合回成功批核销出台账、事件消费即摘除监听（无泄漏）（SPEC Requirement 事件驱动合回重试 Scenario 持有车道收尾即重试合回；tasks 3.1b；出处 core/agent_runner/runner.py:5158 register_run_terminal_callback、core/code_fix.py:2314、tests/test_mergeback_wip_coordination.py:231） | pass | 0/4 | - |
| wipc-event-retry-lock-yield | 并发互斥守卫（D5）：事件重试 MUST 复用既有单一重试入口 checkpoint（其唯一调用点在 self._lock 段内）——锁占用时回调让位不重入（不可重入 Lock 重入即自锁死），锁空闲才投递 checkpoint（design D5；出处 core/code_fix.py:2270 _make_holder_retry_callback、tests/test_mergeback_wip_coordination.py:269） | pass | 0/5 | - |
| wipc-reblocked-recoordinate-trace | 轮询兜底重试仍被挡：识别结果（占用者=在飞车道）随台账 owner_kind=holder/owner_holders 字段与进度 current 双留痕，且仍注册持有者终态监听（事件通道不因轮询兜底先试而丢失）（SPEC Requirement 占用者识别「落盘留痕」+design D2 轮询随之更新；出处 core/code_fix.py:2412 _retry_one_deferred、tests/test_mergeback_wip_coordination.py:290） | pass | 0/4 | - |
| wipc-orphan-no-alert-within-grace | 无主宽限内静默：识别为无主后宽限计时起点随台账 owner_orphan_since 留痕，宽限（30 分钟）内 MUST NOT 发出 mergeback_wip_orphan_stuck 升级告警；无主无可订阅对象 MUST NOT 注册终态监听（SPEC Requirement 无主陈旧 WIP 升级——宽限内继续事件驱动等待；出处 core/code_fix.py:2250 _orphan_grace_minutes、tests/test_mergeback_wip_coordination.py:365） | pass | 0/4 | - |
| wipc-orphan-escalate-after-grace | 宽限耗尽升级人工：无主宽限（回拨 31 分钟 > 30）耗尽后恰发出一次 mergeback_wip_orphan_stuck major 告警，evidence 附重叠文件清单与 D1 盲区注记、recommended_action 按批语义适配（无 spec 可重派，指向提交/stash）；批保持保留待自动合回（不丢弃）、主树 status/HEAD 零触碰、owner_escalated_at 去重保证二次协调不重复升级（SPEC Requirement 无主陈旧 WIP 升级 Scenario 宽限耗尽升级人工；tasks 3.2；出处 core/code_fix.py:1595 _write_defer_orphan_alert、tests/test_mergeback_wip_coordination.py:390） | pass | 0/7 | - |
| wipc-orphan-grace-zero-immediate | 宽限配置可收紧边界：admin.mergeback_wip_orphan_grace_minutes=0 时首次识别即升级 major 告警（耗尽即升级；非法负值回退 30 由解析器保证，不放大成秒升级或无限静默两个错误极端）（design D4 可配置宽限；出处 core/code_fix.py:2250-2264、tests/test_mergeback_wip_coordination.py:433） | pass | 0/2 | - |
| wipc-orphan-to-holder-clock-reset | 识别结果变化回归点：无主宽限计时进行中（5 分钟<30 不告警）持有者出现在飞 → 宽限计时清零（owner_orphan_since 置空）并转注册持有者终态监听（design D2 轮询时识别结果变化随之更新；出处 tests/test_mergeback_wip_coordination.py:448） | pass | 0/2 | - |
| wipc-register-after-terminal-immediate | 监听泄漏防线：注册监听时该 run 已终态（run 文件终态行、不在在飞进程表）→ 立即触发回调并消费注册项（不依赖后续事件、不留死监听）（design Risks 第 3 条；tasks 3.3；出处 core/agent_runner/runner.py:5158、tests/test_mergeback_wip_coordination.py:503） | pass | 0/3 | - |
| wipc-register-inflight-no-premature-fire | 在飞 run 注册不误触发：run 文件有旧 attempt 终态行但在飞进程表在场 → 注册时不立即触发；终态收口 _fire_run_terminal_callbacks 才触发已注册回调（双轨防漏触发；出处 core/agent_runner/runner.py:5168-5183、tests/test_mergeback_wip_coordination.py:516） | pass | 0/2 | - |
| wipc-register-attempt-id-normalized | attempt 形态归一：注册用 base run_id、触发用 attempt 形态（-r1 后缀）→ 内部归一到 base 后正确匹配触发（a1/r1 后缀剥离；出处 core/agent_runner/runner.py:5176、tests/test_mergeback_wip_coordination.py:528） | pass | 0/3 | - |
| wipc-register-overwrite-and-isolation | 回调表健壮性：同 run 同订阅方重复注册覆盖不累积（轮询重复注册只保留最后回调且只触发一次）；单回调异常被 fire 侧 try/except 兜底、MUST NOT 阻断其余回调与 run 收尾（出处 core/agent_runner/runner.py:5208、tests/test_mergeback_wip_coordination.py:540、:552） | pass | 0/4 | - |
| wipc-no-overlap-zero-overhead | 无 overlap 零变化（SPEC Requirement 事件驱动合回重试 Scenario 无 overlap 零变化；tasks 3.4）：空 overlap 时识别短路零 git 探测 subprocess 调用、合回成功路径与现状逐字一致（合回一次、核销出台账、零终态订阅开销）、协调调用零识别且不写任何 owner_* 台账字段（出处 tests/test_mergeback_wip_coordination.py:568-635） | pass | 0/4 | - |
| wipc-config-template-grace-key | 配置模板落盘：.fenix/config.template.yaml 存在 admin.mergeback_wip_orphan_grace_minutes: 30（缺省 30 对齐 escalation cooldown 量级），注释说明语义——宽限耗尽升级 mergeback_wip_orphan_stuck major、绝不自动 stash/丢弃主树改动、在飞持有者场景不受本宽限约束（tasks 2.3；出处 .fenix/config.template.yaml:379-385） | pass | 0/5 | - |
| wipc-source-anchors-identification | 识别链源码锚点（机械兜底）：mergeback.py 存在占用者识别入口 identify_wip_occupant、在飞实现车道前缀过滤（impl-/code-fix-，planner/verifier/admin 不参与）、code-fix 固定 spec 名桥接、git worktree list --porcelain 真相源、三点式分支 diff（HEAD...<branch>）、纯机械红线（MUST NOT LLM 推导路径名）；types.py 存在 WipOccupantInfo 数据类（holders 可追溯 + holder_run_ids + describe + BLIND_SPOT_NOTE）（tasks 1.1；出处 core/worktree_manager/mergeback.py:577-586、core/worktree_manager/types.py:13-90） | pass | 0/10 | - |
| wipc-source-anchors-subscription-alert | 订阅与升级链源码锚点（机械兜底）：agent_runner/runner.py 存在 per-run 终态回调表（__init__ 建态、注册即查已终态、终态收口 _execute_agent 处 fire、整键 pop 消费）；code_fix.py 存在协调入口 _coordinate_blocked_merge、持有者回调工厂（锁占用让位）、宽限解析（admin.mergeback_wip_orphan_grace_minutes 缺省 30）、无主升级告警 _write_defer_orphan_alert（signal_type=mergeback_wip_orphan_stuck、severity=major、evidence 附盲区注记、指引含「该批无 spec 可重派」）；admin_monitor.py 已登记该信号 major 分级与批语义适配指引（tasks 2.1/2.2；出处 core/agent_runner/runner.py:612、:1980、:5146-5214、core/code_fix.py:1595-1653、:2250、:2270、:2314、core/admin_monitor.py:311、:376） | pass | 0/10 | - |
| wipc-full-suite-green | 交付单测整体绿（回归点）：tests/test_mergeback_wip_coordination.py 全部 19 例通过（识别 4 + 事件重试 3 + 无主宽限 4 + 终态注册 5 + 零开销 3），实测 19 passed（tasks 3.1-3.4 全量；出处 tests/test_mergeback_wip_coordination.py:178-635，PASSED 行实测照抄） | pass | 0/21 | - |
| wipc-family-regression-green | 家族回归：本 SPEC 触碰面的存量语义零回归——WIP overlap precheck 拦截（evo-add-codefix-batch-wip-precheck 语义不变）、defer 合回重试消费者（evo-add-wip-defer-merge-retry-consumer）、agent_runner 整体（终态回调表新增不破坏存量）全部绿，实测 62 passed（出处 tests/test_code_fix_wip_precheck.py、tests/test_wip_defer_merge_retry.py、tests/test_agent_runner.py，实测输出照抄） | pass | 0/7 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

