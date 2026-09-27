# ADR-037：页面验证服务 = worktree 静态资源 + 反代主服务，生命周期归框架

date: 2026-09-05
status: accepted

## Context

v2 页面在 worktree 开发，但 Playwright baseURL 指向主仓 8787 dashboard 服务，agent 为让测试通过把页面文件改进主仓，merge-back 被「local changes would be overwritten」熔断；该同构问题会在每个页面 SPEC 复现。

## Decision

- 页面验证用轻量反代（Node http）：静态资源取自 worktree，API/SSE 反代至主服务。测试打真后端——否决「静态服务器 + 逐页 API mock」（成本高、失真）与「每 worktree 第二份完整 dashboard 实例」（与主 daemon 争运行时锁）。
- 服务生命周期归框架：agent_runner 派发前启动、注入 `V2_BASE_URL`、run 终态（含被杀）后 kill；daemon 启动时清扫遗留进程。不靠 agent 自启自停（异常路径漏清理不可靠）。
- 端口确定性分配：高位端口段（排除主服务 8787），冲突时重试分配，耗尽按 run 失败处理并告警；playwright baseURL 由 env 覆盖 + 缺省回退。

## Consequences

- 主仓不再被实现改动污染，页面 SPEC 可并行增量交付；页面 SPEC 的 tasks 只写「跑测试」，baseURL 由 config 决定。
- SSE 代理必须 `flushHeaders` + 透传 chunk，否则事件流测试失效（验收场景含 SSE 流）。
- 主服务重启期间代理 502 暴露为环境性失败，走既有噪音分流归类，不自动重试。
