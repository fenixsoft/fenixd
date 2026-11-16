# Design: admin-orphan-effect-generation-aware

## 现状与根因

core/admin_monitor.py `_orphan_group_effect_evidence`（≈L7561）对具体 spec 处置组走 STATE 单源判定：STATE entry 在场时仅当 `not frozen and status != blocked` 才判生效，frozen=True 直接 return False。2026-11-11 事故中该短路把「处置生效→新代际再冻结」误判为「处置未生效」，假告警直链烧掉 2 次 arbiter 调查。

框架已有的 gate transition 日志家族（解冻族 Transition 留痕，含轮转备份，行含时间戳与 channel=recovery 等标记）足以重构「处置后推进轨迹」，但被 STATE 短路挡在门外——修复以读侧证据解除短路，无需新写入面。

## 方案

三级判定替换单源短路：

1. 代际锚点：处置组完成时间戳（处置记录已有终态时间字段）。
2. 推进轨迹核查：在日志窗（含轮转备份）检索该 spec 在处置完成之后的 gate transition 行（blocked→testing 复位、testing→verified 等合法前移）；命中即判「已生效、被新代际取代」。
3. fail-closed 兜底：无轨迹或日志不可用 → 维持现行升级人工语义，行为零变化。

判「被新代际取代」时：旧处置组转记已消解（附轨迹证据行引用），为当前 frozen 状态开新信号条目并回链旧组 id。

## 取舍

- 不在 STATE 写入侧新增水位线字段（避免状态面 schema 变更与迁移成本），日志轨迹为读侧证据。
- 日志轮转窗口覆盖不到的更旧处置组：维持 fail-closed，不豁免。
- 不改 arbiter 回扫候选筛选：重复仲裁的上游抑制由 add-arbiter-blacklist-disposition 的防抖与本 spec 的假告警消解共同收敛，两者互补。