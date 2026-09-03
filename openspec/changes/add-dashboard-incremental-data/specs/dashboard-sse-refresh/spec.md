## ADDED Requirements

### Requirement: 前端 SSE 增量驱动

v3 SPA 的 spec 数据流改为 SSE 增量驱动：首屏经 `/api/specs` 建立本地 spec 摘要表；
此后 `state` 增量事件进入本地 patch 队列（同 spec 1s 内多事件只应用最新），
表格由本地表渲染；统计徽标由本地表推导。轮询心跳降为 30~60s，`visibilitychange` 时立即校准。

#### Scenario: 增量事件 patch 单行
- **WHEN** 收到 `state` 事件 `specs:[{spec:"s1", summary:{...新值...}}]`
- **THEN** 页面不触发全量列表重渲染；s1 行显示新摘要且其它行状态不变（对 React 渲染计数断言）

#### Scenario: 删除事件移除行
- **WHEN** 收到 `{spec:"s1", summary:null}` 事件
- **THEN** s1 行从表格移除且排序保持

#### Scenario: 心跳降频与补刷
- **WHEN** 页面可见且 SSE 连接正常
- **THEN** `/api/overview` 请求间隔 ≥30s（原 2s）；切后台再切回（visibilitychange）触发一次立即校准请求

#### Scenario: SSE 断线降级
- **WHEN** SSE 连接断开（onerror / 超时重连失败）
- **THEN** 前端不进入空窗：心跳轮询仍按 30s 兜底刷新，重连成功后恢复增量模式

### Requirement: 列表检索防抖

spec 表格的搜索/筛选输入在用户键入期间不触发后端请求：输入防抖 ≥300ms 后在本地摘要表内过滤；
仅本地表为空（首屏未载入）时才回退请求 `/api/specs`。

#### Scenario: 输入防抖
- **WHEN** 用户在 1 秒内连续键入 5 个字符（间隔 <300ms）
- **THEN** 期间无任何 `/api/specs?project=` 新请求，最后一次键入 300ms 后完成本地过滤渲染