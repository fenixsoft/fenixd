## Context

Registry.add_project（core/dashboard/registry.py:445）fixture 缺省 False、无任何拦截；告警缺省聚合分支按 fixture 过滤（core/dashboard/routes/alert_routes.py:117-118），点名查询 ?project= 分支不看 fixture（:104-113）；摄取抑制 _fixture_invocation_suppressed（core/admin_monitor.py:2625-2629）只覆盖 AdminMonitor 捞取路径，场景直写 admin_alerts.json 完全绕开。

## Goals / Non-Goals

- Goals：文档与出题提示词双固化规则 + 低成本静态扫描情报，使「夹具未打标」在验证轮评审前可见。
- Non-Goals：不重构告警聚合/摄取链路；不改 ADR-163 语义与 Registry 接口。

## Decisions

- D1 守卫走静态扫描而非 Registry 缺省翻转：ADR-163 Decision 第 12 行明文禁按路径/名字推导夹具身份，按路径翻转缺省即路径推导；且两个事故场景都是显式传 False，「显式 override 才放行」拦不住本次根因形态。表驱动模式（对齐既有 stale_literal_port 同型）改动小、可测。
- D2 情报不拦截：保持验证链「静态检查注入 judge 情报」既有惯例，避免误伤合法的真实项目注册。
- D3 文档与出题提示词双固化：根因是 planner 从未被灌输规则（agents/planner-plan.md 全文无 fixture 字样），单补文档触达不了出题端。

## Risks / Trade-offs

- 静态模式对变量传参等非字面写法会漏报：接受——情报定位是提示而非硬闸，漏报成本低于误报。
- 文档断言类测试脆弱：沿用领域文档既有断言惯例，只断言 MUST 条目存在。