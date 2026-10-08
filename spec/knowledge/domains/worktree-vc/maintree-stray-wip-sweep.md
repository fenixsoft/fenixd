# 主树散件 WIP 周期盘点与滞留升级

<!-- knowledge: capability=maintree-stray-wip-sweep rev=1
     sources=spec/archive/2026-10-08-evo-add-maintree-stray-wip-sweep -->

daemon 周期只读盘点主树流水线外的 tracked 未提交改动（散件），机械归因持有者，无主且宽限耗尽时以一次性 major 告警浮出——散件滞留由分钟级机械巡检检出，而非 LLM 复盘车道的偶然检出。

## 规则

### 周期只读盘点

- daemon 主循环 60s 节拍对主树 tracked 未提交改动做只读盘点（`git status --porcelain`，排除 untracked，口径对齐既有 tracked-only 脏判定）；主树干净时零产出、零告警、零状态残留。纯 untracked 散件不在本能力覆盖内（构建产物类 untracked 噪音因此天然免疫）。
- 盘点在 worktree_manager 主树锁上以非阻塞方式参与互斥：锁被占用（merge-back 的 stash→merge→pop 写临界区进行中）即放弃本轮，不留痕为异常，下轮重试；绝不与写临界区并发，也绝不阻塞调用方主循环。
- 盘点接线禁设「无在飞 run」空闲预检（见 [ADR-258](../../adr/ADR-258-stray-sweep-readonly-observer-attribution-single-source.md)）——加了预检就永远看不到在飞车道、全部按无主误升级；必须把在飞实现车道 run_ids 传入归因（PMEngine 包装方法供参，盘点器按 WorktreeManager 句柄身份缓存复用，注册表进程内延续）。

### 指纹滞留计时（mtime 免疫）

- 滞留计时基于内容指纹的连续在场（见 [ADR-257](../../adr/ADR-257-maintree-staleness-content-fingerprint-no-mtime.md)）：指纹 = 改动路径排序集 + `git diff HEAD` 内容哈希（对 HEAD 求、含暂存+未暂存——纯 `git diff` 对纯暂存态散件为空、哈希退化为空串故不用；路径集与哈希 NUL 分隔防拼接歧义）。禁用 mtime 等可被外部 git 操作重写的时间戳作计时依据。
- 指纹不变沿用原 first_seen 继续计时（autostash pop 批量重写 mtime 不归零）；内容再被编辑即换新指纹，旧条目清除、新条目自当轮重新起算；改动消失（已被提交/stash/还原）即清除计时状态复位，不告警不残留。

### 占用者机械归因

- 复用合回 WIP 协调的既有机械归因器（`identify_wip_occupant` / `WipOccupantInfo`，见 [ADR-258](../../adr/ADR-258-stray-sweep-readonly-observer-attribution-single-source.md)），禁重造求交逻辑：改动文件集与在飞实现车道 worktree 分支相对主树 HEAD 的改动集求交，命中即持有者在飞——不计时不告警；零命中即无主，自指纹首次出现时刻起算宽限。
- 归因盲区随证据留痕：识别只覆盖 worktree 分支型在飞车道；人工/管理员会话等主树直改形态必零命中，一律按无主走宽限升级，升级仅为告警、误判影响有界，禁为覆盖盲区引入主树写探测。
- 持有者命中期间持续 defer 不告警（与合回 WIP 协调的事件驱动等待同语义），在飞车道长期不终态不构成升级条件。

### 宽限与一次性升级告警

- 宽限配置 `admin.maintree_stray_wip_grace_minutes`，缺省 30，语义对齐 `admin.mergeback_wip_orphan_grace_minutes`；`0` 合法＝耗尽即升级（同指纹一次性去重兜住刷屏）；解析失败/负值/NaN/inf/超一天上限一律回退缺省——配置事故既不放大成无限期静默等待，也不变成关闭降噪的极端。
- 宽限耗尽恰发一次 `maintree_stray_wip_stale` major 告警（经 AdminStore，同指纹先查后记去重，MUST NOT 重复升级）：evidence 附文件清单、first_seen、归因证据、盲区注记与零触碰注记，recommended_action 指向人工 `git add/commit` 或 `git stash push` 留痕。
- 告警经 admin_monitor 三表登记（SIGNAL_SEVERITY + SIGNAL_RECOMMENDATION + STORED_SIGNAL_TYPES）接入自动唤起 Administrator；落盘记录 evidence 以「项目名=」开头供摄取项目名解析收录（本告警无 spec 归属）。漏 STORED_SIGNAL_TYPES 则记录落 store 后无人摄取、升级出口落空。

### 零触碰与能力边界

- 盘点与升级链路全只读：MUST NOT 对主树执行 stash、stash pop、checkout、clean、reset 或任何改变工作区/索引内容的操作；一次盘点/告警前后 `git status --porcelain` 输出逐字节一致。框架仅报告，处置权完全留给人工程序。
- first_seen 与告警去重注册表为 daemon 进程内存态，daemon 重启即重置宽限：重启后散件仍在场会重新起算并最终再告警，损失仅时效，不引入持久化状态文件。
- 本能力为独立旁路观察者，覆盖合回闸门看不见的散件形态（autostash 先行腾空主树使 WIP overlap 占用识别全程不触发，见 [mergeback-wip-active-coordination](mergeback-wip-active-coordination.md)）；不改动 autostash 路径、reclaim「脏不抢」语义与 WIP overlap 闸门任何现行行为，也不消费合回协调的台账与事件。

## 关键行为

- 单轮盘点流程：非阻塞取主树锁（忙则弃轮返回）→ `git status --porcelain` 取 tracked 改动（空集即 status=clean 零产出）→ 构造指纹并与注册表比对（新增档记 first_seen / 同指纹沿用 / 消失清除）→ 传入飞实现车道 run_ids 归因分流（holder 不计时 / 无主按宽限计时）→ 无主且在场超宽限且同指纹未升级过 → 写 AdminStore 告警并记升级标记。

## 溯源

- 2026-10-08 evo-add-maintree-stray-wip-sweep（spec/archive/2026-10-08-evo-add-maintree-stray-wip-sweep） — 新建本页：主树 tracked 散件 WIP 周期只读盘点（60s 节拍、主树锁非阻塞互斥、tracked-only 口径）、内容指纹滞留计时（mtime 免疫）、复用 `identify_wip_occupant` 机械归因、宽限耗尽一次性 `maintree_stray_wip_stale` major 告警（admin_monitor 三表登记接入唤起）、全链零触碰仅报告。
