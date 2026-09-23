# design：alert-noise-governance

## Context

- 闸门：core/pm_engine/spec_integrity.py——check_spec_content_missing（约 82-134 行）仅对 status == blocked 幂等短路，命中空判定只有「冻结 + spec_content_missing major 告警」一个出口；spec_has_content（38-69 行）四选一派发内容判据。调用点 core/pm_engine/dispatch/queue.py:761,783 与 core/pm_engine/recovery.py:878-879 复用同一方法。
- 恢复路径：core/event_bus.py _recover_ready（446-503）早退清单仅 start_after 与存活子进程；recover_orphan_ready（505-594）早退仅 status 筛选/_cancelled_hold/派发退避；全文件 grep frozen 零命中。
- 派发链：core/pm_engine/engine.py _on_spec_ready（约 656-880）守卫链（shutting_down/冷却/单飞/worktree 锁/退避/start_after/依赖/在飞评审）无 frozen 检查；_frozen_state 助手（约 1172 行）现有消费点不在派发/恢复端。_diff_specs（event_bus.py）纯 status diff，daemon 重启空快照整批回放 spec_ready。
- 升级路径：core/admin_monitor.py _detect_daemon_errors（约 1683-1733）——DAEMON_ERROR_THRESHOLD=2、10 分钟窗、末两次间隔 ≤5 分钟（常量与语义注释 106-109），无指纹冷却；告警写路径裸追加，同轮孪生指纹各产一条 escalation；召唤入口 distress→_invoke_administrator 无夹具识别。与既有 _throttled（按 spec+signal_type，:1910）的关系：daemon 级信号 spec=None 无 status_hash，既有节流覆盖不完整。
- 日审：core/self_review.py _collect_admin_summary（约 724-765 行）直读 self.store.read_all()，无 fixture 概念。
- 标记权威源：dashboard.yaml 项目条目 fixture:true（fix-fixture-project-alert-noise 落地，core/dashboard/registry.py 既有读取入口）。
- 实证链（2026-09-22，showcase）：9 轮重放、18 条闸门 ERROR、3 笔 admin-global 召唤（1790077896 计 45 轮被停机截断）；09-12 链：已交付 spec 重置→闸门冻结反向处置、06:33Z 盲目重实现 05:42Z 已合并成果。

## Goals / Non-Goals

**Goals**

1. 已交付/终态 spec 不再被闸门反向冻结（源头分类）。
2. 冻结 spec 不再被恢复/派发链重放（断链）。
3. 重启回放噪音不再升级成 Administrator 召唤（降敏）。
4. 夹具告警退出日审计数与自动召唤（消费端过滤）。
5. 非夹具项目的全部既有行为不变。

**Non-Goals**

1. 不改 spec_has_content 判据与闸门拦截/解冻契约本体（见 proposal 非目标）。
2. 不做派发前主动探测、不改 _diff_specs 机制本体。
3. 不迁移验证场景隔离方式、不改交付链落盘行为。

## 改动点

1. core/pm_engine/spec_integrity.py：check_spec_content_missing 入口终态（done/archived）短路（与既有 status==blocked 幂等短路并列，同一 STATE 读取路径，无新增竞态面）；命中空判定后、冻结动作前加分类分支——目录存在 verification-report.md → 产 spec_delivered_no_content（新常量）不冻结，否则维持既有 spec_content_missing + 冻结路径；spec_has_content 不动，注释固化「验证报告不进认可名单」理由。分类分支 MUST 自带幂等短路（写告警前查 admin store 已有同 spec 同 signal_type 未处理告警则跳过，对齐 admin_monitor._throttled 的「已存在未处理升级告警」判据）——既有 spec_content_missing 的幂等完全依赖「冻结改 blocked → 下次短路」（spec_integrity.py:99-101），本分支放弃冻结即失去该保护，spec 保持 ready 会被恢复精触发（60s）与 full_scan 每轮重命中，无幂等则每分钟追加一条 major 告警。
2. core/alert_lifecycle.py：注册独立闭环条件 spec_delivered_adjudicated（新常量）并加入 _SIGNAL_CONDITIONS（约 44-50 行）；evaluate_alert 为其新增判定分支——仅当关联 SPEC 到达终态（done/archived）才闭环，非终态（含 ready/blocked）保持原状。MUST NOT 复用 CONDITION_SPEC_TERMINAL_OR_UNBLOCKED：该条件在 evaluate_alert 中仅以 blocked 为未解除出口（alert_lifecycle.py:135-138），对非 blocked spec 一律判「已解除」，而本信号产生时 SPEC 停在 ready 待裁决，复用会被下一轮 auto_resolve 立即闭环、人工无从看见；且「补齐认可内容」维度 evaluate_alert 只读状态表不读目录、无法判定，补内容裁决路径由人工 handled 或置终态收口。pm_engine 写入点经 _send_human_escalation_alert 的 build_trigger 统一推导，调用点无需改动。
3. core/event_bus.py：_recover_ready 读 entry 后、清 error 前加 frozen 早退（True 即 INFO 跳过，含 spec 名与原因）；同步 recover_orphan_ready docstring 早退清单；早退路径零 STATE 写入（该函数仅在 error 非空时写 STATE）。
4. core/pm_engine/engine.py：_on_spec_ready（约 660-789）守卫链在既有 read_one（约 720 行）之后、闸门内容校验之前加 frozen 检查（可复用 _frozen_state 助手保持 legacy 文本契约兼容，recovery.py:865 的 in-place redispatch 已有同款先例），命中即 INFO 跳过派发。
5. core/admin_monitor.py（两处正交治理）：_detect_daemon_errors 增加指纹级冷却（记录指纹上次唤起时间戳，daemon 启动后冷却窗内已知指纹不计满）+ 同轮孪生/成对指纹按 fp 聚合合并为一条召唤信号（冷却常量与 DAEMON_ERROR_THRESHOLD 同层声明，不入 config）；distress 升级召唤决策点查项目 fixture 标记，命中记 INFO（含指纹与抑制原因）并跳过自动召唤，人工显式触发通道不在该决策点、不受限。两处落点锚定：冷却的「已知指纹」MUST 覆盖跨重启识别（治理目标正是重启后首扫回放）——store 记录无结构化指纹字段（_fp 仅内存传递不落库，admin_monitor.py:1728-1731），须以 description 内嵌指纹前缀对账或为 daemon_errors 告警 entry 增补结构化指纹字段（任务内定其一）；fixture 抑制判定置于各自动检测路径调用 _invoke_administrator 之前（自动调用点 admin_monitor.py:1352/1908/2085/2332），MUST NOT 放进 _invoke_administrator 本体——人工显式触发（run_administrator）与自动检测共用该入口（:2539）。
6. core/self_review.py：_collect_admin_summary 装配前识别项目 fixture 标记（复用 registry 既有读取入口，依赖方向不允许时经配置层注入，核对 import 方向避免反向依赖环）；标记项目告警不进未处理计数，摘要以 fixture 标注单独呈现。
7. core/dashboard/registry.py：fixture:true 标记权威读取源，只读不改（reference）。

## 与既有机制的关系

- add-spec-content-integrity-gate（归档 2026-09-17）：终态豁免与分类分支扩展其「冻结处置」Requirement；派发前校验与幂等语义不变，其 Scenario「只有无关文件」语义不变（verification-report.md 不属无关文件，按独立分支处理）。
- fix-fixture-project-alert-noise（活跃）：提供标记、看板读侧过滤与 --reset 基线复位；本 SPEC 把同一标记延伸到日审读侧与召唤通道，同一治理线补口。
- fix-redispatch-loop-governance（活跃）：同 spec 同终局重派熔断，scoped 在 run 失败重派；本 SPEC 是事件/恢复入口的 frozen 复核，互补。add-freeze-stop-inflight-agents（活跃）：冻结时在飞 agent 终止语义；本 SPEC 是冻结后不再新派，互补。
- C（指纹冷却）与 E（fixture 抑制）正交并存：一个按指纹时间窗、一个按项目属性。

## 设计决策

- D1｜终态豁免不等于放行派发：只免冻结与告警，派发拦截仍由 spec_has_content 管辖；终态 spec 出现在派发队列本身属异常，由派发层状态机语义管辖。
- D2｜「已交付未落盘」走引导裁决而非自动放行：verification-report.md 在场但 spec 实为废弃半成品时，信号文案引导裁决（补 tasks.md 归档凭据或明确废弃），派发仍被拦，最坏多一条待裁决告警，无预算损失。
- D3｜frozen 复核与升级冷却两条腿缺一不可：外部回置可能整文件重置抹掉 frozen 字段，日志无法区分残留/抹除——复核断「部分回置」腿，冷却兜「整文件重置」腿。
- D4｜夹具抑制 fail-open：标记读取失败或项目未标记一律按非夹具处理，MUST NOT 因标记异常让召唤/摘要失效。
- D5｜冷却仅约束重启后首扫窗口：重启前已召唤过一次（记账在案），同批指纹重启后短期重复召唤收益趋零；窗后复现照常升级。抑制可能掩盖夹具内真故障的对照：抑制必留 INFO 痕、告警原样可见，且历史三笔召唤均为夹具噪音点燃、召唤收益本来就低。

## 风险

- 冷却窗掩盖真实故障：仅约束「重启后首扫回放的已知指纹」，全新指纹与窗后复现照常升级（D5）。
- 分类分支误放行：派发仍拦（D2），无预算损失路径。
- frozen 复核对人工 kick 的影响：人工 kick 走同一 _on_spec_ready 入口，冻结 spec 的人工重派本就该先解冻（「唯一出路是补内容后人工 unfreeze_spec」契约），INFO 留痕保证操作者可见跳过原因。
- 备选落点（非本 SPEC 交付物）：dispatch/queue.py _process_queue 候选筛选区加 frozen 跳过可兜住绕过 _on_spec_ready 的直入队路径；当前无实证路径，留作后续观察。
