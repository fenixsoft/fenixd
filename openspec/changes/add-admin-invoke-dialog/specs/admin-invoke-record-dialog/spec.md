# admin-invoke-record-dialog — 呼叫 Admin 处置记录弹窗

## ADDED Requirements

### Requirement: 呼叫成功后弹出处置记录弹窗

用户在 SPEC 行右键菜单点击「呼叫 Admin 介入」后，系统 SHALL 在呼叫请求返回成功（HTTP 2xx）或返回 409（已有处置进行中）时打开处置记录弹窗；弹窗 SHALL 显示当前 SPEC 相关的处置记录列表。呼叫请求因其他错误失败（网络异常、5xx 等）时 SHALL NOT 打开弹窗，仅显示错误提示。

#### Scenario: 呼叫成功自动弹窗
- **WHEN** 用户对 SPEC `fix-foo` 点击右键菜单「呼叫 Admin 介入」，POST `/api/spec-admin-invoke` 返回成功
- **THEN** 页面打开处置记录弹窗，展示 `fix-foo` 相关处置记录，且无需用户再次点击

#### Scenario: 已在处置中仍弹窗
- **WHEN** 用户点击「呼叫 Admin 介入」但服务端返回 409（该 SPEC 已有呼叫进行中）
- **THEN** 页面同样打开处置记录弹窗，用户可查看当前处置进度

#### Scenario: 呼叫失败不弹窗
- **WHEN** POST `/api/spec-admin-invoke` 因网络或服务端错误失败
- **THEN** 仅显示错误 toast，不打开弹窗

### Requirement: 弹窗按 SPEC 过滤展示处置记录

处置记录弹窗 SHALL 仅展示与该 SPEC 相关的记录（escalation 与 disposition 记录按 `spec` 字段过滤），记录渲染 SHALL 复用运维记录视图的卡片样式（叙述总结、处置动作、结果、状态标签、未处置置顶）。后端 `GET /api/admin-activities` SHALL 支持可选 `spec` 查询参数实现服务端过滤。

#### Scenario: 仅显示该 SPEC 的记录
- **WHEN** 项目中存在 SPEC `fix-foo` 与 `fix-bar` 的处置记录，用户在 `fix-foo` 上呼叫 Admin 弹出弹窗
- **THEN** 弹窗仅列出 `spec=fix-foo` 的记录，`fix-bar` 的记录不出现

#### Scenario: 该 SPEC 无历史记录
- **WHEN** 用户对一个从未触发过 Admin 处置的 SPEC 呼叫成功并弹出弹窗
- **THEN** 弹窗显示该 SPEC 暂无处置记录的空态提示（呼叫本身产生的初始记录可出现）

#### Scenario: 复用运维记录卡片样式
- **WHEN** 弹窗中渲染某条含叙述总结的 disposition 记录
- **THEN** 展示内容与运维记录视图一致：summary 叙述、处置动作、结果、状态标签

### Requirement: 弹窗内容通过 SSE 实时更新

弹窗打开期间，系统 SHALL 通过现有全局 SSE 通道（`/api/stream`）接收 Admin 处置记录变更事件并自动更新弹窗内容：Dashboard 后端文件监听器 SHALL 监听 `.fenix/admin_alerts.json` 变更，变更时向已连接客户端广播处置记录更新事件；前端 SHALL 在弹窗打开状态下响应该事件并重新拉取（或直接应用推送的）该 SPEC 处置数据。弹窗关闭后 SHALL 忽略后续更新事件。Admin 后台处置流程 SHALL 不受弹窗开合影响。

#### Scenario: Admin 产生新处置记录时弹窗自动刷新
- **WHEN** 弹窗处于打开状态，Administrator Agent 后台写入新的 disposition 记录到 `.fenix/admin_alerts.json`
- **THEN** Dashboard 后端广播处置记录更新事件，弹窗内容在无手动刷新的情况下更新并显示新记录

#### Scenario: 关闭弹窗后后台处置继续
- **WHEN** 用户关闭弹窗，此后 Administrator 在后台继续处置并产生新记录
- **THEN** 后台处置流程不受影响，继续产生处置记录；页面不因弹窗关闭而报错

#### Scenario: 弹窗打开期间状态流转实时可见
- **WHEN** 弹窗中某条记录原为「处置中」，Admin 完成处置后记录状态更新
- **THEN** 弹窗中该记录状态标签更新为最新状态，无需用户关闭重开弹窗
