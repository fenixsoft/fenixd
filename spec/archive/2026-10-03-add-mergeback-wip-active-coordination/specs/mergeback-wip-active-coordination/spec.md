# mergeback-wip-active-coordination 能力

## ADDED Requirements

### Requirement: 占用者识别

合回被 WIP overlap 挡住时，框架 SHALL 识别主树未提交改动的占用者并落盘留痕（随进度/日志）：把 overlap 文件集与**在飞实现车道**（implementer/code-fix run 的 worktree 分支相对主树 HEAD 的改动文件集）求交——存在命中即在飞持有者（记录 run/spec/分支），零命中即无主陈旧 WIP。识别 MUST 基于机械数据源（worktree 注册表、在飞 run 列表、git diff），MUST NOT 使用 LLM 推导路径名。

#### Scenario: 在飞持有者被识别

- **WHEN** 主树未提交修改 `A.tsx`，且在飞 implementer run 的分支改动集含 `A.tsx`
- **THEN** 识别结果为该 run（spec 名与分支可追溯），并写入进度/日志

#### Scenario: 无主陈旧 WIP 被识别

- **WHEN** 主树未提交修改 `B.tsx`，当前无任何在飞车道分支改动集命中 `B.tsx`
- **THEN** 识别结果为无主，写入进度/日志

### Requirement: 事件驱动合回重试

持有者为在飞车道时，框架 SHALL 以该 run 的终态事件作为合回重试的主要唤醒手段（终态事件到达即重试合回）；固定间隔轮询 MUST 降级为兜底手段（事件丢失防线）。既有 precheck 拦截、merge-tree 预演、主树零污染语义不变——事件唤醒的只是「何时重试」，不是「是否重试」。

#### Scenario: 持有车道收尾即重试合回

- **WHEN** 合回因 overlap 挡住、持有者 implementer run 随后到达终态
- **THEN** 合回在终态事件到达后的短窗口内（秒级）自动重试，MUST NOT 等到下一个固定轮询周期

#### Scenario: 无 overlap 零变化

- **WHEN** 合回时主树无 overlap
- **THEN** 合回路径行为与现状逐字一致，无识别与订阅开销

### Requirement: 无主陈旧 WIP 升级

识别为无主陈旧 WIP 时，框架 SHALL 在可配置宽限（`admin.mergeback_wip_orphan_grace_minutes`，缺省 30）内继续事件驱动等待（期间可能变为有主），宽限耗尽 MUST 升级既有 `mergeback_wip_overlap` 人工告警（major 分级，附 overlap 文件与识别证据），MUST NOT 无限期静默等待，也 MUST NOT 自动 stash/丢弃主树改动。

#### Scenario: 宽限耗尽升级人工

- **WHEN** overlap 判定无主且宽限 30 分钟内无人认领、主树 WIP 未清除
- **THEN** 发出 `mergeback_wip_overlap` major 告警（含文件清单与证据），批保持「保留待自动合回」语义，MUST NOT 丢弃批分支、MUST NOT 触碰主树改动
