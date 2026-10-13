## 背景

evo-add-admin-orphan-disposition-effect-check 落地后，孤儿处置组终态的生效核查在 global 组上持续误报「无生效证据」：核查的日志证据源只读当前 fenixd.log 尾部 256KB，且只认 blocked→X 手动解冻一种留痕。实测三类漏判：解冻留痕轮转进 fenixd.log.1（组 admin-global-1791056118）；治愈动作是归档收尾提交+合并（组 admin-global-1791144077）；治愈动作是分支合并（组 admin-global-1791154704）。三条 daemon_errors 源信号自 2026-10-03T19:31Z 起滞留未收口超 46 小时，连环升级三次吸引人工。

## 问题

证据源设计未考虑日志轮转与处置动作多样性，fail-closed 语义把「证据查不到」一律当成「未生效」，落地效果是「无限期 pending」变成「无限期 escalated」，台账收口目标未达成。

## 目标

把生效核查从「单一解冻留痕」扩为「按处置动作类型的证据家族」：日志对账覆盖轮转文件、新增合并/归档收尾类动作证据、支持从组记录提取具体 spec 名回退读 STATE 旁证；未命中任何家族时维持 fail-closed 升级不变。

## 非目标

- 不改 fail-closed 语义：证据不足仍升级，绝不假闭环。
- 不改升级去重与冷却（记录级/信号级/指纹级三层去重现状工作正常）。
- 不处理 global 组之外的归组逻辑，不动收口侧存储方法。
- 不为已升级组翻案：组内已有 escalate=true 终结记录的组按既有守卫②（_converge_final_orphan_group，core/admin_monitor.py:4532-4536「升级人工是唯一出路」）豁免生效核查，本 SPEC 新增的证据家族不追溯。背景中的三条存量组已全部升级，落地后仍走人工 resolve 收口；本 SPEC 防的是后续同形态组再被误升级。