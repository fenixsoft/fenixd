# 主树 untracked 散件盘点时钟持久化

<!-- knowledge: capability=stray-escalation-clock-persistence rev=1
     sources=spec/archive/2026-10-30-evo-persist-stray-escalation-clock -->

主树 untracked 散件盘点注册表（滞留计时与升级标记）落盘持久化，使 24 小时滞留升级与体积升级的时钟跨 daemon 重启连续——重启不再击穿一次性告警去重与升级判定。与 [stray-untracked-escalation](stray-untracked-escalation.md) 同属一个 sweeper，本页只承载时钟存续介质与恢复语义。

## 规则

### 注册表持久化

- untracked 盘点注册表持久化到 `.fenix/` 运行时状态区（与 restart_history.jsonl 同区；gitignored 不入库，也不会被 untracked 盘点计入散件），内容为指纹→条目映射，条目字段为 first_seen / first_seen_iso / files / escalated_at / escalated_signal_at；体积字段（sizes_bytes/total_bytes）每轮盘点现采、不持久化。
- `escalated_signal_at` MUST 随注册表持久化：该标记丢失时恢复的 first_seen（往往已满 24 小时）会在重启后首轮盘点重复发出 `maintree_untracked_stray_escalated`，违背「同一滞留集合只升级一次」。
- 写时机：每轮盘点完成且注册表变更时原子落盘（临时文件 + rename）；读时机：盘点开始时载入并与内存态合并。

### 时钟跨重启连续

- daemon 重启后的盘点以恢复的 first_seen 计算 elapsed：滞留满 24 小时即触发 `maintree_untracked_stray_escalated`，不因中途重启而重新宽限。
- 同一路径集合的散件信号按指纹跨重启去重：集合未变化的周期盘点复用既有告警、仅做留痕更新，重启前后连续盘点不产生第二条新告警（info 档一次性语义在持久化时钟下自然成立，无新信号类型）。
- 已触发过升级的集合经历重启且集合指纹未变时不再重复升级，升级标记随注册表恢复保持置位。

### 损坏降级与惰性清理

- 持久化文件缺失或损坏时回退内存注册表、重新宽限，并留一条告警；主盘点流程 MUST NOT 被阻断（fail-open）。
- 载入与每轮盘点对盘上已消失的路径做惰性清理，集合为空的指纹整条删除；已处置（删除/归档）散件的指纹不再参与后续去重与升级，已清理散件不复燃。

### 范围与介质裁定

- 仅 untracked 注册表持久化；tracked 散件注册表维持 daemon 进程内存态（重启重置宽限，损失仅时效，见 [maintree-stray-wip-sweep](maintree-stray-wip-sweep.md)）。
- 计时连续性以持久化 first_seen 为准，不采用 mtime 判定——散件目录 mtime 会被部分写入刷新，时钟连续性不可靠。

## 溯源

- 2026-10-30 evo-persist-stray-escalation-clock（spec/archive/2026-10-30-evo-persist-stray-escalation-clock） — 新建本页：untracked 注册表落盘持久化（escalated_signal_at 随持久化、变更即原子写、损坏 fail-open 降级、消失路径惰性清理），24h 滞留升级、体积升级与同指纹一次性告警恢复跨重启有效性；裁定 tracked 注册表维持内存态、拒绝 mtime 计时方案。
