# self-review-window-snapshot 增量规格

## ADDED Requirements

### Requirement: 聚合窗口上界固定快照
自省聚合（run 统计 / 日志 ERROR 聚合）开始时 MUST 对窗口上界取一次固定快照（`window_end = datetime.now()`），全部 `_in_window` 判定使用该快照值，聚合执行期间不得再调用实时时钟判定窗口归属。窗口语义仍为 `[window_start, window_end]` 闭区，仅将上界从『聚合中实时变化』改为『聚合启动时冻结』。

#### Scenario: 并行派发期间聚合不漏计
- **WHEN** 自省聚合启动后、完成前，agent_runner 新创建 run 文件（时间戳 ≤ 聚合启动时点）
- **THEN** 该 run 按快照上界判定，聚合结果与聚合启动时刻磁盘状态一致

#### Scenario: 聚合启动后新派发的 run 不计入本轮
- **WHEN** run 文件创建时间晚于聚合快照时点
- **THEN** 不计入本轮统计（正确语义：非本轮数据），下一轮自省自然纳入

#### Scenario: 聚合期间耗时不影响边界判定
- **WHEN** 聚合执行耗时较长（大 runs 目录）
- **THEN** 窗口边界不因耗时漂移，统计口径确定可复现