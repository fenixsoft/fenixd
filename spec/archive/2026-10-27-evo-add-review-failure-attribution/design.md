## Context

评审失败行构造：core/pm_engine/spec_review.py:433（只拼 run_err）、:490（reason）。对照 code-fix 形态：core/agent_runner/maintenance_runs.py:2595-2599（追加 [api_timeout=… exit_code=… stderr_tail: …]），_stderr_tail_summary 在 maintenance_runs.py:2305。归因桥接：core/agent_runner/runner.py:1622-1638（已透传 api_error_status/conn_error，未透 stderr），AgentRunResult 字段区 core/agent_runner/result_gate.py:132-156。指纹：core/admin_monitor.py:598-611 归一化（:578 保守集原则：不动路径与文字骨架）、:614-621 sha1 指纹、:153-155 召唤阈值、:3333-3334 同轮合并。熔断：core/pm_engine/infra_breaker.py:386 record_success（无调用方）、:353 计数无条件递增；调用点仅 core/pm_engine/spec_review.py:1363。

## Goals / Non-Goals

- Goals：失败行就地可归因；同型失败同指纹可跨日追踪；熔断计数语义修复。
- Non-Goals：不改共享底座错误文本（runner.py:6590）以免扰动全部车道指纹；不调阈值与冷却。

## Decisions

- D1 指纹剥离按组件模板窄化：只对 spec_review 组件「评审 run 执行失败: <spec>: …」模板剥 SPEC 名段，不做全局激进归一化——沿用 admin_monitor.py:578 保守集原则，防止不同骨架被误聚。
- D2 stderr_tail 复用既有 _stderr_tail_summary 读异常 stderr_lines，AgentRunResult 新增字段形态对齐 api_error_status；已归档 run 证明 429 等根因主要落在 api_error_status，stderr 对限流场景多为良性定噪行，留痕价值在于 exit_code/异常文本兜底。
- D3 record_success 接线放评审收工点（spec_review 链路「评审 run 已收工」处）而非 dispatch 层：语义是「链路证明可用」；熔断短路期间未实际派发的尝试不计成功。

## Risks / Trade-offs

- 剥 SPEC 名后不同 SPEC 的失败混聚：正是诉求（同型跨日追踪），且召唤仍受同指纹阈值与间隔约束，噪音可控。
- 熔断清零改变既有熔断灵敏度：恢复的是 infra_breaker 设计语义（「连续」），并在测试中固定窗口内连续判定。