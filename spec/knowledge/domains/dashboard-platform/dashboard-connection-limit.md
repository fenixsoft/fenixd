# 连接数上限

<!-- knowledge: capability=dashboard-connection-limit rev=1
     sources=spec/archive/2026-09-09-add-dashboard-incremental-data -->

dashboard 服务对 SSE 连接与 HTTP 并发线程的双上限保护，防标签页风暴耗尽资源。

## 规则

- SSE 活跃连接上限 32（`MAX_SSE_CONNECTIONS`）：超出时新连接被拒（HTTP 503 返回 JSON 错误体），已建立连接不受影响；被拒客户端退化为轮询；连接释放后计数回落，新连接可正常建立。
- HTTP 并发处理线程上限 64（`MAX_SERVER_THREADS`）：入口判断线程计数超限时响应 503 `{"error":"server busy"}`，不排队不堆积；已挂起请求不受影响。
- 两个上限以模块常量暴露在 `core.dashboard.server` 命名空间（SSEHub 经模块引用读取，非硬编码），测试可 monkeypatch 降值后验证拒绝行为。

## 溯源

- 2026-09-09 2026-09-09-add-dashboard-incremental-data（spec/archive/2026-09-09-add-dashboard-incremental-data） — 建立 SSE 连接上限与 HTTP 线程上限，超限拒绝（503）而非排队堆积，常量可 monkeypatch 降值测试
