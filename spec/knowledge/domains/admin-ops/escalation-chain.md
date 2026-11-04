# 升级处置链（Admin→Arbiter→人工）

<!-- knowledge: capability=escalation-chain rev=5
     sources=spec/changes/add-escalation-chain-admin-arbiter,spec/knowledge/_inbox/done/escalation-chain-orphan-watchdog-double-path.md,spec/changes/fix-escalation-chain-watchdog-yield-gaps,spec/knowledge/_inbox/done/chain-arbiter-rulings-default-3.md,spec/knowledge/_inbox/done/escalation-chain-disposition-ledger-gap.md -->

升级边信号的默认消费通道：两级自动化处置（Admin 受限运维先行、Arbiter 全局拍板兜底）逐级收敛，人工裁决只是链终点失败后的例外出口。

## 规则

- 链序固定 Admin→Arbiter→人工。升级边信号（`StateMachine.freeze_for_human` 全族与 `PMEngine._send_human_escalation_alert` 全部调用点）默认入链头 Admin；链内任一级处置成功即闭环（信号收口 + spec 状态恢复可运行），人工队列零痕迹；仅链终点（Arbiter 失败）产生人工告警。
- 链契约按发射通道治理而非告警语义：入链面即上述两个咽喉层的注册点；`admin_monitor` 孤儿看护是链外豁免的第三条发射通道（pending 超时升级仍是链外直写，受链痕抑制约束）。豁免是防自环的必要设计——链无法处置自己的死讯，看护对链死讯报警若入链即自环。看护与链的协调以「链痕」为判据：链痕在场时看护不开火，链痕消失后兜底升级语义保留（升级口径见 [human-escalation-alerts](human-escalation-alerts.md)）。
- 各信号既有自愈/重试梯子（transient backoff、verify 重验、severity 批闸、同因重派熔断）原样保留；处置链只接管梯子耗尽那一刻的去向。
- 链入口按信号来源判定防自环：只收框架/runner 侧产生的信号；链成员的处置输出永远是链内转单边（Admin 超范围→Arbiter、处置失败→下一级），看护触发的 deferred 重派同属链内恢复动作——均不作为新信号重新计签入链。`admin_dispatch_programming_error` 等框架自指类照常入链头。
- Admin 链上语义：以既有受限形态处置（受限工具、只见当前 run 注入结果）；尝试配额 2 次/签名——run 崩溃/超时计一次，自判超范围转单不计失败；链头派发前查 spec 冻结态，frozen 时不派发、不计尝试、不记失败，该件转 deferred 留痕（解冻后由看护扫描重派）；run 终态 frozen-terminated 空壳击杀（0 API 轮次即被冻结终止）视为未尝试不计配额，跑过若干轮后被冻结击杀仍计真实失败；处置成功的终态收口同时完成信号收口与 spec 状态恢复可运行（框架侧 side-effects 显式 status 解冻、拒绝 parse 兜底，与 Arbiter `_apply_disposition_side_effects` 同型纪律）。
- Admin 超范围转单是结构化产出：disposition 写 `handoff: "arbiter"` + `handoff_reason`，直达 Arbiter 单飞队列，不重载 `result=escalate` 的既有语义（「需人工决策」），不计 Admin 失败。
- Arbiter 链上语义：以全局视野接单，转单载荷含 Admin 尝试痕（run 摘要与失败原因）；获得预算豁免拍板动作面——可写 spec 预算 override 字段（`impl_run_budget_override` 等既有字段复用，不新增 schema）并落台账留痕；复现配额缺省 3 次/签名，第 4 次复现强制上升人工（告警附 Admin 尝试痕 + Arbiter 台账五段 + choices）。拍板成功即闭环不计「复现」，连续复现才逐次烧拍板配额——复现配额只决定自动化兜底深度，不改变链序与人工出口语义。
- Arbiter 复现配额缺省值单源 `ConfigLoader.CHAIN_ARBITER_RULINGS_DEFAULT`（`core/config.py`），两处运行时兜底（`arbiter.py _arbiter_rulings_quota`、`escalation_chain.py quota_config` except 字典）与 Dashboard ChainPanel 缺省同值对齐；链配置可在 Dashboard 设置页编辑并经热更新生效。Admin 尝试配额（2 次/签名）与配额复位通道不受该缺省影响。
- 配额复位双通道：签名连续 7 天无复现清零，或该 spec 状态发生迁移清零。dead-man/停机类基础设施死亡签名维持永久单次、不适用复位。
- 签名遵循「同一个问题」语义：spec=null 信号的签名含主体键（从信号 payload 提取，如蒸馏欠账归档名、triage 场景集指纹）；提取不到时退化为类型级并在台账标注粒度。
- 配额计数是状态不是台账事实：独立状态文件 `.fenix/escalation_chain_state.json`（gitignored）按签名记 Admin 尝试/Arbiter 拍板计数与最近复现，不入 arbiter ledger；主树运行时写入仅 daemon 执行。
- 链派发器事件驱动直派（`core/pm_engine/escalation_chain.py`），对齐 arbiter lane 单飞队列形态（同签名 dedup + 复用在飞互斥守卫 + 队列深度上限），不走 admin_monitor 5 分钟巡检；admin_monitor 保留兜底看护——pending 超时升级语义不变；链感知钩子（`_reap_chain_inflight`）负责在办登记超时清除与 deferred 扫描重派。
- 链痕单源查询口：看护升级抑制与 deferred 重派判定共用同一查询函数（输入签名，输出 in_flight/deferred/arbiter_active 三态命中）；in_flight/deferred 读链状态文件同名区，arbiter 在飞读 arbiter 单飞队列既有注册（只读访问，不新建注册表）；链状态文件缺失/损坏按零命中降级（fail-open，对齐看护链缺席既有口径）。
- 链让行留痕与唤醒：链在办互斥守卫命中（同 spec 在飞 admin run 且该 run 非本链成员）时链让行（deferred），in_flight 区留 `phase: deferred` 条目（含被让行对象标识 `yield_to` 与让行时间戳 `deferred_at`），不整条清除登记。看护巡检扫描 deferred 条目：被让行 run 已终态且该签名信号未收口（spec 仍 blocked/冻结或 pending 告警在场）时重新触发该件链派发——走链派发器既有单飞/互斥守卫，不绕过；信号已收口仅清条目。frozen 预检转入的条目（`yield_to` 为空）以「spec 已解冻」为重派条件，同一扫描覆盖。deferred 条目纳入既有 in_flight 超时 reap，超时无进展照常清理，不产生永久滞留条目。
- 链路由 admin run 的处置台账闭合责任分两径、仅一径尽责：admin run 派发时无条件落一条 pending DISPOSITION 记录，闭合由消费路径负责——直接信号路径在收尾写带 `admin_run_id` 的 final 处置记录，`_merge_admin_runs` 的 by_run 归并按「非 pending 记录带同 run id」判 run 已终结，pending 不再孤儿；链路由路径的全部出口（closed/handoff/exhausted/deferred）都不写 final 处置记录——链闭环副作用只有解冻恢复 spec 状态、收口在队上升件、写链事件三件事，不含处置台账闭合，pending 自派发起即为永久孤儿。
- 链路由 pending 孤儿是结构性误报源：孤儿看护按 `admin.escalation_cooldown_minutes` 宽限（代码缺省 60 分钟，本项目配置 15 分钟）后扫到「pending 超时 + run 文件终态 + 链痕三态全无」——链 success 时已清 in_flight，链痕抑制不命中——升级 critical「处置中断」。每例链路由 admin run（成功或转单）在派发宽限到期后必然产出一条假「处置中断」。
- 「处置中断」告警排查判据：先查该 run 名下有无 final 处置记录与链状态文件终态——有 final 即直接路径已正常收尾（健康）；无 final 且链已闭环/转单即链路由孤儿 pending（结构性误报），勿信告警 description 归因文案。
- 链成功路径不执行 choice 载荷：链上对 `disp.choice_id` 只做越界复核（注册表 allowlist 之外转单 Arbiter），无载荷执行等效物——payload 型 choice 的真实修复动作只有直接信号路径执行。信号若仅经链路由单通道处置，链闭环后修复动作被静默跳过：spec 停滞且零告警，是比误报告警更重的功能缺口。
- 逐动作 DISPOSITION 记录不带 `admin_run_id`（同秒 final 记录带）：逐动作记录不能终结 pending；逐动作记录先于 final 落盘而 final 因故缺失时，by_run 归并同样断裂。
- 链状态文件条目形态向后兼容：in_flight 区条目 `phase` 取值 admin/arbiter/deferred；缺 `yield_to`/`deferred_at` 的既有条目按 admin/arbiter 相待，缺 `phase` 的历史残留按 admin 兼容。
- 失败双轨上升：(a) Arbiter 自判无法处理/无法决策/尝试无效（含 run 崩溃超时，沿用同签名失败重试 1/2 次与半成品调查包机制）；(b) 复现配额耗尽（缺省 3 次拍板后第 4 次复现）。
- 上升件必附全链痕迹（Admin 尝试痕、Arbiter 台账五段、剩余 choices）与全链关联键（链 run_id 族）；上升件在人工队列期间，链上任一级后续成功闭环时自动收口（`close_cause` 族标记，含 `CLOSED_BY_CHAIN`），不滞留。
- 触发面为黑名单制：黑名单内信号绕过全链直达人工队列（写入即按降级态降噪分级标记 handled 的既有语义），初始为空集。
- 链入口不按 severity 过滤：minor 预算循环等低严重度信号同样入链。降噪分级是「人工队列」的属性而非「信号」的属性——降级态保留原降噪（critical/major 进 pending、warning/minor 写入即 handled）。
- 降级 fail-open：`arbiter.enabled=false` 或 Admin+Arbiter 车道双双失能（链级判定，如 harness 级 spawn 失败，非单件失败）时，整体退回无链时代的升级边行为——直达人工队列（既有降噪生效）+ narrative 补叙，逐字节一致；链级失能不逐件烧配额，一次性 WARN 留痕；配置修复后自动恢复入链，无需人工干预。
- 存量迁移：启用链路由的首个 daemon 启动执行一次性迁移（版本哨兵防重跑）——存量 pending escalation 中能判定「底层已闭环」（同签名 spec 已终态或处置已 resolved）的自动收口（`close_cause=migrated`），其余保留人工队列；迁移不回填入链。回扫哨兵与迁移哨兵互不重入：回扫消费在案 pending 入链派发，迁移只收口已闭环 pending。

## 溯源

- 2026-11-03 add-escalation-chain-admin-arbiter（spec/changes/add-escalation-chain-admin-arbiter/） — 新增本页：处置链路由与防自环、Admin/Arbiter 双车道链上语义与配额、失败双轨上升、黑名单 kill switch 与 fail-open 降级、配额状态文件、存量迁移
- 2026-11-03 escalation-chain-orphan-watchdog-double-path（spec/knowledge/_inbox/done/escalation-chain-orphan-watchdog-double-path.md） — 折叠首例链路事件结论：孤儿看护第三发射通道豁免定性、看护链盲重复出件、链 deferred 无唤醒路径静默挂起、冻结×链头派发竞态烧配额（三缺口治理立项 fix-escalation-chain-watchdog-yield-gaps）
- 2026-11-03 fix-escalation-chain-watchdog-yield-gaps（spec/changes/fix-escalation-chain-watchdog-yield-gaps/） — 三缺口收口：Admin 配额语义收窄（frozen 预检不派发不计尝试 + frozen-terminated 空壳视为未尝试）、deferred 让行由静默丢弃改为 in_flight 留痕 + 看护扫描重派或超时清理、链痕单源查询口确立（看护抑制与重派共用）
- 2026-11-03 chain-arbiter-rulings-default-3（spec/knowledge/_inbox/done/chain-arbiter-rulings-default-3.md） — 折叠 Arbiter 复现配额缺省调整为 3 次/签名（第二次裁决仍白名单外时留第三次自主处置机会，不提前落人工）：缺省单源 CHAIN_ARBITER_RULINGS_DEFAULT、两处运行时兜底与 ChainPanel 同值对齐；Admin 尝试配额 2 与复位窗 7 天不变
- 2026-11-04 escalation-chain-disposition-ledger-gap（spec/knowledge/_inbox/done/escalation-chain-disposition-ledger-gap.md） — 折叠链路由处置台账缺口取证（链上线首日 4 例同根因）：链全出口不写 final 处置记录致 pending 永久孤儿（宽限后必然假「处置中断」）、链成功路径不执行 choice 载荷（单通道修复静默跳过）、逐动作记录无 run id 的 by_run 归并盲区、排查判据=run 名下有无 final
