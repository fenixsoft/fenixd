# 人工升级告警

<!-- knowledge: capability=human-escalation-alerts rev=9
     sources=spec/archive/2026-09-02-add-administrator-agent,spec/archive/2026-09-02-fix-graceful-shutdown-agents,spec/changes/add-escalation-chain-admin-arbiter,spec/knowledge/_inbox/done/escalation-chain-orphan-watchdog-double-path.md,spec/changes/fix-escalation-chain-watchdog-yield-gaps,spec/knowledge/_inbox/done/escalation-chain-disposition-ledger-gap.md,spec/changes/fix-escalation-chain-ledger-closure,spec/knowledge/_inbox/done/alert-narrative-generation-chain-retired.md,spec/changes/consolidate-alerts-to-ops-page -->

处置链终点的例外出口：链上两级自动化（[escalation-chain](escalation-chain.md)）都无法收敛时把事件升级给人类——结构化告警持久化、Dashboard 运维页呈现（告警记录页签 + 运维菜单徽标）、孤儿检测升级口径。

## 规则

- 告警写入时机：处置链终点（Arbiter 自判失败/复现配额耗尽）、黑名单信号、降级态（`arbiter.enabled=false` 或链失能）判定须人工出场时写入升级告警，以及孤儿看护 pending 超时（链外豁免通道，受链痕抑制与链事件对账兜底约束）；自愈不可达不让事件静默丢失，链内任一级处置成功即终态化、零人工感知。
- 机器发起的升级信号默认走处置链：处理中件不产生用户可感知告警（不推送、不进 pending、不落 admin_alerts 条目），可见性由链状态文件与 SPEC 时间轴/处置链视图承载。
- 告警记录字段：`id`、`created`、`severity`、`spec`、`description`、`evidence`、`action_taken`、`recommended_action`，并附全链痕迹（Admin 尝试痕、Arbiter 台账五段关联、链 run_id 族关联键）与剩余 choices；人工处置后可全链回溯。
- 持久化到 `.fenix/admin_alerts.json`（gitignore），daemon 重启后仍可读取。
- 记录数上限：admin_alerts.json 任何写回时自动裁剪，只保留最近 150 条；消费方（冷却去重、自动闭环）只依赖近期记录，裁剪最旧历史不影响语义。
- Dashboard 消费面唯一化：告警展示唯一面=运维页「告警记录」页签（告警列表与「标记已处理」操作；侧栏运维菜单徽标为待裁决计数提示位，细则见 [ops-alert-badge](ops-alert-badge.md)）；概览页不渲染告警信息面与告警操作入口（横幅、列表、裁决控件、「清理所有事件」入口均不承载）。处置后记录保留可追溯。
- 全局清理入口唯一：「清理所有事件」入口仅在运维页告警记录页签（桌面操作栏与移动端工具行两形态），全系统仅此一处。确认弹窗明示三要点——范围为全部项目的未处理告警、操作不可撤销、AdminMonitor 不会对同一告警重新升级（确认计数取后端全量口径 `total_unhandled`，不做可见列表钳制）；确认后经既有 `POST /api/alerts/clear` 逐条标记已处理，成功提示并刷新列表，徽标经既有刷新管线自然归零；取消不发起任何请求。
- 人工冻结与定时冻结不进链：`freeze_spec`（dashboard 人工冻结）与 `frozen_until` 定时冻结的告警直接等待人工处置，与链无关。
- 黑名单信号与降级态直达人工队列，按既有降噪分级生效（critical/major 进 pending、warning/minor 写入即 handled），零叙事生成调用。
- 合成兜底类告警静默化：框架自身合成的兜底提示不进入人工升级通道。
- 孤儿检测升级口径（链痕抑制前置）：admin 处置 pending 超时（孤儿）时，开火前先查链痕——同签名存在链 in_flight 条目、deferred 让行条目、或 arbiter 单飞队列在飞调查任一命中时，不产生升级告警且不终结 pending disposition（保持原状，待链痕消失后下一轮巡检重判）；链痕全部消失且 pending 仍超时，再经链事件对账兜底（见下条）仍零命中才升级。升级判定仍以 run 文件（`.fenix/runs/<admin_run_id>.jsonl`）为准：含 `{"type": "interrupted"}` 判定为已知中断（daemon 关闭所致）——追加 status=interrupted 终结记录终结该 pending disposition 且不产生告警，后续巡检因已终结不再处理；不含 interrupted 标记才进入归因与升级。
- 孤儿看护链事件对账兜底：升级人工前按 admin run id 联查链事件台账（经链单例 `chain_events_for_run` 只读查询口，monitor 不直读台账内部结构）——存在 chain-closed/chain-handoff 事件即补写非 pending 终结 DISPOSITION 闭合该 pending、不产生升级告警：`result=resolved`、`admin_run_id` 必须落该 run id（by_run 归并仅认「非 pending 记录带同 run id」为终结，补记缺该字段则 pending 不闭合、兜底空转）、`actions_taken` 注明「链侧已闭环但 final 记录缺失，由看护对账补记」，后续巡检不再重判；台账文件缺失/损坏按零命中放行升级（fail-open，宁多告警不漏告警）。
- 兜底语义保守：pending 超时且 run 文件不存在或已被清理（无证据可查）时，按「无 interrupted 标记」处理——升级人工并追加终结记录防止循环告警，宁多告警不漏告警。
- 孤儿看护是链外直写出口：pending 超时升级由 AdminMonitor 以 `store.append(kind=ESCALATION)` 直写人工队列，不经 Arbiter——链契约按发射通道治理，孤儿看护为链外豁免发射通道（链无法处置自己的死讯）；链痕抑制与链事件对账的判定单源见 [escalation-chain](escalation-chain.md)。
- 归因按 run 文件末事件终态分派文案：frozen-terminated 写明 spec 冻结击杀（附 reason）、cancelled 写明取消/击杀来源（附 by）、error 与 gate-blocked 写明对应终态、无终态证据可查保守写「死因不明（run 证据缺失）」，终态原文摘录附入 evidence。
- result 终态分支归因读子型：subtype=success 写「处置结论成功但 final 处置记录缺失（落账缺口或收尾中断）——先核对处置台账与链事件再定处置」，不写与事实相反的「非成功结论」文案；非 success 子型保持既有「run 以 result 终态退出但处置未完成（非成功结论）」文案（回归锚，不得回退）。success 子型只修正归因方向性、不抑制升级——落账缺失可能伴随真收尾中断，人工仍应知情；终态原文摘录照常附入 evidence。

## 溯源

- 2026-09-02 史前复原 — 迁移期已存在的基线：自愈不可达时升级人工告警；合成兜底类告警静默化，不进入人工升级通道
- 2026-09-02 add-administrator-agent（spec/archive/2026-09-02-add-administrator-agent） — 固化升级告警 8 字段结构与 admin_alerts.json 持久化、150 条写回裁剪、Dashboard 横幅与「标记已处理」闭环
- 2026-09-02 fix-graceful-shutdown-agents（spec/archive/2026-09-02-fix-graceful-shutdown-agents） — 孤儿检测升级口径收窄：run 文件含 interrupted 标记的已知中断终结而不告警，无证据场景保守维持升级
- 2026-11-03 add-escalation-chain-admin-arbiter（spec/changes/add-escalation-chain-admin-arbiter/） — 升级告警改为链终点例外出口：机器升级信号默认入链零落盘（不推送/不进 pending/不落条目），仅链终点失败、黑名单、降级态落告警；上升件附全链痕迹（Admin 尝试痕/台账五段/链 run_id 关联键）与剩余 choices
- 2026-11-03 escalation-chain-orphan-watchdog-double-path（spec/knowledge/_inbox/done/escalation-chain-orphan-watchdog-double-path.md） — 折叠孤儿看护链外豁免通道定性（设计内 vs 链盲重复出件缺口）与告警归因模板不可信排查纪律（先查 run 终态与链状态文件）
- 2026-11-03 fix-escalation-chain-watchdog-yield-gaps（spec/changes/fix-escalation-chain-watchdog-yield-gaps/） — 孤儿升级开火前链痕抑制（链在办/deferred 留痕/arbiter 在飞任一命中即抑制，链痕消失兜底保留），归因改为按 run 终态证据生成并废弃固定归因模板
- 2026-11-04 escalation-chain-disposition-ledger-gap（spec/knowledge/_inbox/done/escalation-chain-disposition-ledger-gap.md） — 折叠归因口径修正：result 终态分支固定文案不读 success 子型（成功 run 归因文案与事实相反），排查纪律以台账 final 记录与链状态文件为准
- 2026-11-04 fix-escalation-chain-ledger-closure（spec/changes/fix-escalation-chain-ledger-closure/） — result 终态归因改读 success 子型（success→「final 处置记录缺失」族文案、非 success 文案不变、升级行为不变）；孤儿升级新增链事件对账兜底（chain-closed/chain-handoff 命中补终结记录不升级、admin_run_id 必落、查询异常 fail-open）——上条折叠的「归因文案与事实相反不可判」缺陷随之废除
- 2026-11-12 alert-narrative-generation-chain-retired（spec/knowledge/_inbox/done/alert-narrative-generation-chain-retired.md） — 折叠告警消费面收敛（consolidate-alerts-to-ops-page）：概览告警横幅退役、展示唯一面=运维页告警记录页签、「清理所有事件」入口迁运维页（桌面+移动端两形态）、运维菜单红点徽标计数口径（未处理且携带 choices；知情/已处理/失效不计、归零隐匿、壳级刷新管线）；降噪直达不再附叙事补叙
- 2026-11-12 consolidate-alerts-to-ops-page（spec/changes/consolidate-alerts-to-ops-page/） — 消费面收敛以 SPEC 定案入库：概览告警面退役（组件/样式/专属管线删除）、清理入口迁告警页签成全系统唯一全局清理入口（确认三要点与 total_unhandled 全量计数、清理端点语义不变）、徽标细则独立成页 ops-alert-badge（本页只留消费面定位交叉引用）
