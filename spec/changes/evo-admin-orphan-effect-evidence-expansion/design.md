## 设计

### 改动集中点

core/admin_monitor.py 单点改造，收口侧（core/admin_store.py）零改动：

1. _read_recent_unfreeze_transitions（:4713-4765）：:4723 的单文件改为候选集 [fenixd.log] + [fenixd.log.{i} for i in 1.._LOG_ROTATION_BACKUPS]（:166），按窗口起点过滤——mtime 早于窗口起点的文件跳过，读到窗内最老一行即止；保留逐文件尾部限量（_TAIL_ERROR_READ_BYTES :623 语义不变），最坏成本与跨日复发检索（:3449-3454）同量级。
2. _orphan_group_effect_evidence（:4656-4709）：global/None 分支从「仅日志对账」扩为依序尝试证据家族：解冻留痕（既有）→ 合并/收尾提交（新增，git log 按窗口与消息匹配）→ STATE 旁证（新增）。命中即返回证据对象；全空则走既有升级路径（:4563 守卫内 append ESCALATION）。
3. 常量区（:623/:633/:637/:641）新增提交类证据的匹配配置（提交消息家族前缀）；_ORPHAN_EFFECT_DELIBERATE_CHANNELS（:637）语义仅约束解冻留痕通道，不动。

### spec 名提取

global 组的 DISPOSITION 记录 spec 字段为 "global" 占位。提取顺序：组内记录 actions_taken 文本中的 spec 名 token → 关联 SIGNAL 记录 → 均失败则跳过 STATE 家族（不猜）。提取逻辑独立成函数，便于单测。

### 风险

- 读多个轮转文件的成本：窗口过滤 + mtime 剪枝 + 尾部限量三重约束下可控。
- 提交消息匹配假阳性：要求消息同时含目标 spec 名与家族前缀、时间落在对账窗内；测试覆盖假阳性用例。