# 主树散件盘点时钟持久化（untracked 与 tracked 注册表）

<!-- knowledge: capability=stray-escalation-clock-persistence rev=2
     sources=spec/archive/2026-10-30-evo-persist-stray-escalation-clock,spec/changes/evo-persist-stray-tracked-registry -->

主树散件盘点注册表（滞留计时与升级标记）落盘持久化，使滞留升级与告警节奏的时钟跨 daemon 重启连续——重启不再击穿一次性告警去重与升级判定。untracked 流先行落地（evo-persist-stray-escalation-clock），tracked 流于 2026-11-27 evo-persist-stray-tracked-registry 补齐同构落盘并引入同指纹 24 小时静默窗。与 [stray-untracked-escalation](stray-untracked-escalation.md) 同属一个 sweeper，本页只承载时钟存续介质与恢复语义。

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

- ~~仅 untracked 注册表持久化~~ **已被推翻**：tracked 散件注册表自 evo-persist-stray-tracked-registry（2026-11-27）起同样落盘持久化，不再维持进程内存态。原「重启重置宽限的损失仅时效」假设被两窗处置 run 空烧实证推翻：2026-11-21..22 窗 4 次 daemon 重启后 69-71 秒内必重登记 first_seen（4/4 命中），30 分钟宽限耗尽即兑现为完整 administrator 处置 run（单次 120-232 秒、约 0.8 美元），两窗 14 次 run 约 11.8 美元外加零新信息知识回写 commit——损失不是时效而是完整处置预算与重复升级提请。
- 计时连续性以持久化 first_seen 为准，不采用 mtime 判定——散件目录 mtime 会被部分写入刷新，时钟连续性不可靠。

### tracked 注册表持久化与同指纹 24h 静默窗（evo-persist-stray-tracked-registry）

- tracked 注册表落盘 `.fenix/stray_tracked_registry.json`（.fenix 运行时状态区，gitignored 不入库、不计入 untracked 盘点、不扰动零触碰对账），顶层两分区：`tracked` 计时注册表（键=改动指纹，条目字段白名单 first_seen/first_seen_iso/files/escalated_at——不写 escalated_signal_at，双档升级属 untracked 语义）与 `alert_history` 同指纹静默窗台账（键=同一指纹，值 {"last_alert_at": epoch 秒, "suppressed_count": int}）。
- 写时机/读时机/原子写/无变更跳过/损坏降级与 untracked 注册表同构：盘点开始每进程一次载入、收尾（含本轮放弃路径）原子落盘；载入遇 OSError/字节层损坏置「本进程禁写」哨兵不覆写盘上完好文件（JSON 层真损坏仍覆写自愈）；缺失/损坏回退空表重新宽限（fail-open 不阻断主盘点）。
- 同指纹静默窗（24 小时滚动冷却）取代 tracked 流一次性 escalated_at 门槛：同指纹（同 fp ⟺ diff 字节级零演进）距上次告警不足 24h MUST NOT 重发 maintree_stray_wip_stale、MUST NOT 写 AdminStore/唤起 admin run，仅 suppressed_count 累计与 60 分钟聚合 info 日志；满 24h 可再发一条，evidence 携带「静默窗抑制轮数=N」（与 AdminStore 台账的复发处置轮数分列、语义不混），随后刷新 last_alert_at、suppressed_count 归零。指纹演进（新指纹）按常规宽限正常告警。escalated_at 仍随条目写入并持久化（审计与既有断言兼容），但告警门槛 MUST NOT 再以它一次性禁告——否则持久化的 escalated_at 会把「满 24h 可再告」永久锁死。
- 台账与计时条目分账：在飞车道命中/会话归因分支 pop 计时条目、指纹当轮不在场的计时条目清除，均 MUST NOT 删除 24h 静默窗内的台账条目（归因瞬时 pop 后同指纹重登记仍在窗内不重告——旧「归因出现→消失转换再升级」噪音形态由此封顶）；台账条目仅在该指纹当轮不在场且 last_alert_at 超 24h 后淘汰；散件提交/还原后计时条目照旧清除。抑制轮 sweep 返回 status 维持 orphan-timed、返回键集不变。

## 溯源

- 2026-10-30 evo-persist-stray-escalation-clock（spec/archive/2026-10-30-evo-persist-stray-escalation-clock） — 新建本页：untracked 注册表落盘持久化（escalated_signal_at 随持久化、变更即原子写、损坏 fail-open 降级、消失路径惰性清理），24h 滞留升级、体积升级与同指纹一次性告警恢复跨重启有效性；裁定 tracked 注册表维持内存态、拒绝 mtime 计时方案。
- 2026-11-27 evo-persist-stray-tracked-registry（spec/changes/evo-persist-stray-tracked-registry） — 修改本页：推翻「tracked 注册表维持内存态/损失仅时效」裁定（两窗 14 次处置 run 约 11.8 美元、重启后 4/4 命中 69-71 秒重登记 first_seen 实证），tracked 注册表同构落盘 `.fenix/stray_tracked_registry.json` 两分区；引入同指纹 24h 滚动静默窗（alert_history 台账为告警门槛单源、escalated_at 降为审计字段、台账与计时条目分账、抑制轮数随 evidence 下发），长滞留散件复发上界收敛为每指纹每 24 小时至多一条告警。
