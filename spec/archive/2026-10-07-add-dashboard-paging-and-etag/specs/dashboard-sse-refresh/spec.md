## MODIFIED Requirements

### Requirement: refresh 心跳的驱动语义

无 `project` 字段的 `refresh` 心跳（`REFRESH_HEARTBEAT = 2.0s` 周期广播，兜底 daemon 状态/新项目发现等非文件变更场景）不再直接触发项目详情页的全量重拉：项目详情页收到心跳后仅执行条件请求校准（携带 If-None-Match），304 未命中（数据确实变化）才重拉渲染。带 `project` 字段的事件（state/detail/admin_activities 等）驱动语义不变。跨项目聚合页（概览 `/overview`、运维 `/activities`）收到心跳后的重拉行为不变（由条件请求通道兜住传输成本）。

#### Scenario: 心跳命中 304 不重拉

- **WHEN** 项目详情页可见且无任何项目数据变化，10 个 refresh 心跳周期（~20s）内
- **THEN** 该页心跳触发的条件请求（`getSpecDetail` → `/api/specs/<spec>?project=…`，已纳入 ETag 覆盖）全部命中 304，无全量响应体传输，页面无重渲染

#### Scenario: 数据变化时心跳照常反映

- **WHEN** daemon 写入 STATE.md 使该项目 spec 状态变化，下一个 refresh 心跳到达
- **THEN** 条件请求返回 200 全量，页面在心跳周期内（≤2s + 请求耗时）反映新状态（不劣化于现状）

#### Scenario: 聚合页行为不变

- **WHEN** 概览页/运维页可见，refresh 心跳到达
- **THEN** 页面照常触发重拉请求（由 ETag/304 兜住未变场景的传输），页码/滚动/页签状态保持（与现行为一致）
