# 能力：stray-tracked-registry-persistence（tracked 流散件注册表持久化）

## 术语
- tracked 流散件：主树 git 已跟踪文件的未提交改动，由 maintree_stray_wip_stale 周期盘点告警。
- first_seen 注册表：以归一化改动指纹为键、记录首次发现时刻的跨重启状态文件。
- 同指纹静默窗：同一指纹 diff 字节级零演进期间的告警抑制。

## 行为规范
1. tracked 流散件首次盘点发现时登记 .fenix/stray_tracked_registry.json：键为归一化改动指纹，值含 first_seen/first_seen_iso/文件集/escalated_at/escalated_signal_at（字段白名单与 untracked 注册表一致）。
2. 写入必须原子（tmp+replace）；文件缺失/损坏时回退进程内存态并照常盘点，不阻塞告警链。
3. daemon 重启后必须从注册表恢复 first_seen，宽限（30 分钟）与升级时钟跨重启连续。
4. 同指纹静默窗：距上次告警 24 小时内且 diff 字节级完全一致的指纹不重发 maintree_stray_wip_stale，仅累计度数记账；diff 演进即正常重告并刷新 first_seen 与静默窗起点。
5. 散件被提交/还原（指纹消失）后注册表条目清除。