# Design: add-worktree-test-server

## Context

实证链路（2026-08-29）：v2-overview-page merge-back 被「local changes would be overwritten」熔断；排查发现主仓工作区被 implementer 改入 app.js/bridge.js/app.json/overview.json/project.json——它们在 worktree 开发，但 Playwright baseURL 是 8787 = 主仓 dashboard 服务，为让测试通过只好改主仓文件。同构问题将在此后每个 v2 页面 spec 复现（此前 sse-bridge/data-adapters/spec-detail/config 未爆雷是因为每次都被人工/巡检清理或恰好合流成功）。

## Goals / Decisions

### D1: 反代方案而非静态服务器或第二实例
测试需要真实后端（overview 的启停删、SSE 重拉、config 的保存回显均打真 API，mock 会大幅重写测试且削弱验收意义）。选 **worktree 静态资源 + API/SSE 反代至主服务** 的轻量代理（Node http，约 30-50 行，放 `tests/v2/dev-server.mjs`）：
- 否决「纯静态服务器 + Playwright route 拦截 mock」：每个页面都要写 API mock，成本高且失去真后端验证。
- 否决「每 worktree 跑第二份完整 dashboard 实例」：与主 daemon 争抢运行时锁（admin_alerts.json.lock 等），风险与重量都不成正比。

### D2: 服务生命周期归框架管（agent_runner），不靠 agent 自觉
agent 自启自停不可靠（异常路径漏清理、debug 循环里忘杀）。框架在派发前启动、注入 `V2_BASE_URL`、run 终态（含被杀）后 kill；daemon 启动时清扫遗留进程（按进程标记或端口段）。实现挂靠 worktree_manager 的创建/清理钩子最自然。

### D3: 端口分配确定性
`V2_TEST_PORT_BASE + (run 序号 mod N)` 或系统分配后写入运行环境；并发运行（并行度 2，预留余量取 20 个高位端口段）不冲突，主服务 8787 排除在外。

### D4: 兼容与迁移极小
playwright.config.js 改 3 行（env 覆盖 + 回退）；已完成的 v2 spec 不回改；进行中/待派的 spec 无需改 tasks（它们只写「跑测试」，baseURL 由 config 决定）。v2-shell-hash-router tasks 里的 8787 字样属历史 spec 不动。

## Risks / Trade-offs

- SSE 代理缓冲会破坏事件流测试——实现时必须 `flushHeaders` + 透传 chunk，验收场景含 SSE 流。
- 端口被外部占用——服务启动失败时框架按端口冲突重试分配，重试耗尽按 run 失败处理并告警。
- 主服务重启期间代理 502——测试将失败并暴露为环境问题（噪音分流已有能力归类），可接受。

## Migration Plan

落地即对后续派发生效；对正在运行的运行无影响（它们仍走 8787，由巡检兜底清理）。

## Open Questions

无。
