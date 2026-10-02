# maintree-stray-wip-sweep 能力

## ADDED Requirements

### Requirement: 周期盘点主树散件 WIP

daemon 周期巡检 SHALL 对主树 tracked 未提交改动做只读盘点（`git status --porcelain`，排除 untracked，口径对齐既有 tracked-only 脏判定）；盘点 MUST 在 worktree_manager 主树锁上以非阻塞方式参与互斥，锁被占用（merge-back/autostash 临界区进行中）时本轮直接放弃；盘点 MUST NOT 产生任何写工作区/索引/暂存栈的 git 副作用。

#### Scenario: 滞留散件被盘点入库

WHEN 主树存在 tracked 未提交修改且主树锁空闲
THEN 本轮盘点产出该改动集的指纹（路径排序集 + diff 内容哈希）并记录首次出现时刻

#### Scenario: 主树干净时零产出

WHEN 主树无 tracked 未提交改动
THEN 本轮盘点无产出、无告警、无状态残留

#### Scenario: 锁忙时本轮跳过

WHEN 盘点发起时 merge-back 的 stash→merge→pop 临界区正持有主树锁
THEN 本轮盘点放弃且不留痕为异常，下轮重试

### Requirement: 占用者归因与陈旧计时

对盘点出的改动集，框架 SHALL 复用既有机械归因器（WipOccupantInfo：在飞实现车道 run 分支相对主树 HEAD 的改动文件集求交）判定持有者；命中 → 持有者在飞，不计时不告警；零命中 → 无主，按指纹首次出现时刻起算宽限（`admin.maintree_stray_wip_grace_minutes`，缺省 30，语义对齐 `admin.mergeback_wip_orphan_grace_minutes`）。陈旧计时 MUST 基于内容指纹的连续在场，MUST NOT 以文件 mtime 为计时依据。

#### Scenario: 在飞车道命中则不告警

WHEN 改动文件集与某在飞实现车道分支改动集存在交集
THEN 归因为该车道持有，宽限计时器不启动、不发告警

#### Scenario: 零命中开始宽限计时

WHEN 改动文件集对所有在飞车道分支改动集零命中
THEN 识别为无主散件 WIP，自指纹首次出现时刻起计宽限

#### Scenario: 指纹稳定时保持原计时（mtime 免疫）

WHEN 同一改动集的 mtime 被外部操作（如 autostash pop）批量重写，但路径集与 diff 内容哈希不变
THEN 该指纹沿用原 first_seen 继续计时，计时器不归零

### Requirement: 宽限耗尽一次性升级告警

无主散件 WIP 宽限耗尽时，框架 SHALL 恰发一次 `maintree_stray_wip_stale` major 告警（经 AdminStore，型制对齐 `_write_defer_orphan_alert`）：evidence 附文件清单、first_seen、归因证据与 WipOccupantInfo.BLIND_SPOT_NOTE 盲区注记，recommended_action 指向人工提交或 stash 留痕；同指纹先查后记去重，MUST NOT 重复升级；改动集消失（已被提交/stash/还原）时 SHALL 清除计时状态且不告警。

#### Scenario: 宽限耗尽恰发一次

WHEN 无主散件 WIP 在场时间超过宽限（如已滞留 31 分钟，超过 30 分钟宽限）
THEN 发出一次 major 告警，后续盘点周期不重复发送

#### Scenario: 改动消失即复位

WHEN 上一周期仍在场的指纹在本周期盘点中不再出现
THEN 计时状态清除，不发告警、不残留

### Requirement: 零触碰语义

盘点与升级链路 MUST NOT 对主树执行 stash、stash pop、checkout、clean、reset 或任何改变工作区/索引内容的操作；框架仅报告，处置权完全留给人工程序。

#### Scenario: 告警前后主树逐字节一致

WHEN 一次盘点/告警完成
THEN `git status --porcelain` 输出与盘点前逐字节一致，工作区文件内容未被触碰