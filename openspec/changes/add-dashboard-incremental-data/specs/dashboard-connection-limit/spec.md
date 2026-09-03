## ADDED Requirements

### Requirement: SSE 连接上限

SSEHub 活跃连接数上限 ≤32：超出时新连接拒绝（HTTP 503 返回 JSON 错误体），已建立连接不受影响；
被拒客户端由前端退化为轮询。

#### Scenario: 超限拒绝
- **WHEN** 已建立 32 条 `/api/stream` 连接，第 33 条发起
- **THEN** 第 33 条收到 503 且 JSON body `{"error": ...}`；前 32 条持续收到心跳/事件

#### Scenario: 释放后恢复
- **WHEN** 32 条中的 1 条断开（客户端关闭）
- **THEN** 新连接可正常建立（计数回落到 31）

### Requirement: HTTP 线程上限

ThreadingHTTPServer 并发处理线程数上限 ≤64：入口判断线程计数超限时响应 503 `{"error":"server busy"}`，
不排队不堆积。

#### Scenario: 线程耗尽返回 503
- **WHEN** 并发执行 64 条慢读请求（挂起），第 65 条请求到达
- **THEN** 第 65 条收到 503 server busy；已挂起请求不受影响

### Requirement: 上限常量可配置

上限值以模块常量暴露（`MAX_SSE_CONNECTIONS` / `MAX_SERVER_THREADS`），测试可 monkeypatch 降低后验证。

#### Scenario: 常量降值可测
- **WHEN** monkeypatch `MAX_SSE_CONNECTIONS=2` 后建立 2 条连接再建第 3 条
- **THEN** 第 3 条被拒 503，证明上限读取自常量而非硬编码