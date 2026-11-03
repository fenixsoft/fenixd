# 升级处置链（Admin→Arbiter→人工）

<!-- knowledge: capability=escalation-chain rev=2
     sources=spec/changes/add-escalation-chain-admin-arbiter,spec/knowledge/_inbox/done/escalation-chain-orphan-watchdog-double-path.md -->

升级边信号的默认消费通道：两级自动化处置（Admin 受限运维先行、Arbiter 全局拍板兜底）逐级收敛，人工裁决只是链终点失败后的例外出口。

## 规则

- 链序固定 Admin→Arbiter→人工。升级边信号（`StateMachine.freeze_for_human` 全族与 `PMEngine._send_human_escalation_alert` 全部调用点）默认入链头 Admin；链内任一级处置成功即闭环（信号收口 + spec 状态恢复可运行），人工队列零痕迹；仅链终点（Arbiter 失败）产生人工告警。
- 链契约按发射通道治理而非告警语义：入链面即上述两个咽喉层的注册点；`admin_monitor` 孤儿看护是链外豁免的第三条发射通道（pending 超时升级语义不变）。豁免是防自环的必要设计——链无法处置自己的死讯，看护对链死讯报警若入链即自环；但看护对链在办件开火时完全链盲，对链在办件重复出件是实现缺口。
- 各信号既有自愈/重试梯子（transient backoff、verify 重验、severity 批闸、同因重派熔断）原样保留；处置链只接管梯子耗尽那一刻的去向。
- 链入口按信号来源判定防自环：只收框架/runner 侧产生的信号；链成员的处置输出永远是链内转单边（Admin 超范围→Arbiter、处置失败→下一级），不作为新信号重新入链。`admin_dispatch_programming_error` 等框架自指类照常入链头。
- Admin 链上语义：以既有受限形态处置（受限工具、只见当前 run 注入结果）；尝试配额 2 次/签名，run 崩溃/超时计一次，自判超范围转单不计失败；处置成功的终态收口同时完成信号收口与 spec 状态恢复可运行（框架侧 side-effects 显式 status 解冻、拒绝 parse 兜底，与 Arbiter `_apply_disposition_side_effects` 同型纪律）。
- Admin 超范围转单是结构化产出：disposition 写 `handoff: "arbiter"` + `handoff_reason`，直达 Arbiter 单飞队列，不重载 `result=escalate` 的既有语义（「需人工决策」），不计 Admin 失败。
- Arbiter 链上语义：以全局视野接单，转单载荷含 Admin 尝试痕（run 摘要与失败原因）；获得预算豁免拍板动作面——可写 spec 预算 override 字段（`impl_run_budget_override` 等既有字段复用，不新增 schema）并落台账留痕；复现配额 2 次/签名，第 3 次复现强制上升人工（告警附 Admin 尝试痕 + Arbiter 台账五段 + choices）。
- 配额复位双通道：签名连续 7 天无复现清零，或该 spec 状态发生迁移清零。dead-man/停机类基础设施死亡签名维持永久单次、不适用复位。
- 签名遵循「同一个问题」语义：spec=null 信号的签名含主体键（从信号 payload 提取，如蒸馏欠账归档名、triage 场景集指纹）；提取不到时退化为类型级并在台账标注粒度。
- 配额计数是状态不是台账事实：独立状态文件 `.fenix/escalation_chain_state.json`（gitignored）按签名记 Admin 尝试/Arbiter 拍板计数与最近复现，不入 arbiter ledger；主树运行时写入仅 daemon 执行。
- 链派发器事件驱动直派（`core/pm_engine/escalation_chain.py`），对齐 arbiter lane 单飞队列形态（同签名 dedup + 复用在飞互斥守卫 + 队列深度上限），不走 admin_monitor 5 分钟巡检；admin_monitor 保留兜底看护——pending 超时升级语义不变，看护对象扩展全链在办件。
- 看护不感知链内转级：链已把在办件转派 Arbiter（在飞调查中）时，看护仍按 pending 处置条目的宽限独立升级人工，产出与链终点裁决包平行的重复人工告警；链感知钩子（`_reap_chain_inflight`）只用于超时清除在办登记，孤儿接管开火前不查链/Arbiter 状态，链让行时还清空 in_flight 登记不留转级痕迹，无从查起。「链上任一级后续成功闭环时自动收口」只覆盖链终点上升件，不覆盖看护件。
- 链让行（deferred）无唤醒路径：链头失败后命中「同 spec 在飞 admin run」互斥守卫即让行退出，信号若复发由下一次触发重新入链；被让行对象不是链成员，其死亡不回喂链、信号也不复发——链静默挂起，直到 daemon 重启的启动回扫才把在办件转派 Arbiter。
- 冻结×链头派发竞态烧配额：spec frozen 落盘后毫秒级内链头 Admin run spawn 即被 frozen-terminated（0 轮空壳），链仍记一次失败——一次尝试配额被纯竞态烧掉。
- 失败双轨上升：(a) Arbiter 自判无法处理/无法决策/尝试无效（含 run 崩溃超时，沿用同签名失败重试 1/2 次与半成品调查包机制）；(b) 复现配额耗尽（2 次拍板后第 3 次复现）。
- 上升件必附全链痕迹（Admin 尝试痕、Arbiter 台账五段、剩余 choices）与全链关联键（链 run_id 族）；上升件在人工队列期间，链上任一级后续成功闭环时自动收口（`close_cause` 族标记，含 `CLOSED_BY_CHAIN`），不滞留。
- 触发面为黑名单制：黑名单内信号绕过全链直达人工队列（写入即按降级态降噪分级标记 handled 的既有语义），初始为空集。
- 链入口不按 severity 过滤：minor 预算循环等低严重度信号同样入链。降噪分级是「人工队列」的属性而非「信号」的属性——降级态保留原降噪（critical/major 进 pending、warning/minor 写入即 handled）。
- 降级 fail-open：`arbiter.enabled=false` 或 Admin+Arbiter 车道双双失能（链级判定，如 harness 级 spawn 失败，非单件失败）时，整体退回无链时代的升级边行为——直达人工队列（既有降噪生效）+ narrative 补叙，逐字节一致；链级失能不逐件烧配额，一次性 WARN 留痕；配置修复后自动恢复入链，无需人工干预。
- 存量迁移：启用链路由的首个 daemon 启动执行一次性迁移（版本哨兵防重跑）——存量 pending escalation 中能判定「底层已闭环」（同签名 spec 已终态或处置已 resolved）的自动收口（`close_cause=migrated`），其余保留人工队列；迁移不回填入链。回扫哨兵与迁移哨兵互不重入：回扫消费在案 pending 入链派发，迁移只收口已闭环 pending。

## 溯源

- 2026-11-03 add-escalation-chain-admin-arbiter（spec/changes/add-escalation-chain-admin-arbiter/） — 新增本页：处置链路由与防自环、Admin/Arbiter 双车道链上语义与配额、失败双轨上升、黑名单 kill switch 与 fail-open 降级、配额状态文件、存量迁移
- 2026-11-03 escalation-chain-orphan-watchdog-double-path（spec/knowledge/_inbox/done/escalation-chain-orphan-watchdog-double-path.md） — 折叠首例链路事件结论：孤儿看护第三发射通道豁免定性、看护链盲重复出件、链 deferred 无唤醒路径静默挂起、冻结×链头派发竞态烧配额（三缺口治理立项 fix-escalation-chain-watchdog-yield-gaps）
