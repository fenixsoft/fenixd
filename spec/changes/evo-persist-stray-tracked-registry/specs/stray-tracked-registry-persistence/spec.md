# 能力：stray-tracked-registry-persistence（tracked 流散件注册表持久化）

## 术语
- tracked 流散件：主树 git 已跟踪文件的未提交改动，由 maintree_stray_wip_stale 周期盘点告警。
- 改动指纹：路径排序集 + `git diff HEAD` 内容哈希 + 二进制内容补全段（stray_wip.py `_fingerprint`）；同指纹即 diff 字节级零演进。
- first_seen 注册表：以改动指纹为键、记录首次发现时刻的跨重启状态文件。
- 同指纹静默窗：同一改动指纹距上次告警不足 24 小时期间的告警抑制（24 小时滚动冷却）。

## 行为规范
1. tracked 流散件首次盘点发现时登记 `.fenix/stray_tracked_registry.json`，文件两分区：`tracked`（键=改动指纹，条目字段白名单 first_seen/first_seen_iso/files/escalated_at，与 untracked 计时条目一致；不写 escalated_signal_at——该档属 untracked 升级语义）与 `alert_history`（键=同一指纹，值含 last_alert_at/suppressed_count）。
2. 写入必须原子（tmp+replace，payload 无变更跳过）；文件缺失或 JSON 层损坏时回退进程内存态并照常盘点，不阻塞告警链。载入遇 OSError/字节层损坏时本进程 MUST NOT 回写（保留盘上原文件），由下个 daemon 进程重试载入。
3. 载入时机为每轮盘点开始前每进程一次（守卫），回写时机为每轮盘点收尾（含本轮放弃路径）。daemon 重启后必须从注册表恢复 first_seen 与静默窗台账，宽限（30 分钟）与静默窗跨重启连续。
4. 同指纹静默窗（24 小时滚动冷却）：同一指纹距上次告警不足 24 小时内 MUST NOT 重发 maintree_stray_wip_stale、MUST NOT 写入新 AdminStore 记录或唤起 admin run，仅 suppressed_count 累计；距上次告警满 24 小时 MAY 再发一条，evidence 携带累计抑制轮数；指纹演进（新指纹）按常规宽限正常告警。tracked 流告警门槛以 `alert_history` 为准，MUST NOT 再以 escalated_at 一次性标记永久禁止重告（escalated_at 字段仍写入并持久化，仅供审计与兼容）。
5. 抑制轮的 sweep 返回 status 维持 `orphan-timed`、返回键集不变；抑制日志按 60 分钟聚合窗落 info，MUST NOT 逐轮重写。
6. 静默窗台账独立于计时条目：在飞车道命中/会话归因分支 pop 计时条目、以及指纹当轮不在场的计时条目清除，均 MUST NOT 删除 24 小时静默窗内的台账条目；台账条目在该指纹当轮不在场且 last_alert_at 超 24 小时后淘汰。散件被提交/还原（指纹消失）后计时条目清除。
