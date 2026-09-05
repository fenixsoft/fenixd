# 验证报告：add-worktree-test-server

> ⚠️ 本报告由框架于 2026-08-29T10:56:46Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 3/7 场景通过，4 失败，0 错误（1 个真实产品 Bug）**

7 个场景：3 通过、4 失败、0 警告、0 错误、0 阻塞。失败集中在需要 JS 渲染的断言（page-title / stat-tile / SPEC 列表 / 跨项目概览文本），根因为隔离测试服务静态根未指向 worktree 副本的 core/dashboard/static/，app.js 返回 404 使 SPA 不启动；同时 playwright.config.js 未读取 V2_BASE_URL，baseURL 注入不生效。纯静态 HTML 元素断言（#main、#btn-overview 等）在 8765 上正常通过，排除端口冲突或主服务不可达问题。无 auth/签名错误、无 console 网络豁免、无弹窗时序问题、无 Layer-4 视觉问题可豁免。判定为 1 个 critical 产品 Bug（系统性，影响 4 个场景）。

| 指标 | 数量 |
| --- | --- |
| 通过 | 3 |
| 失败 | 4 |
| 错误 | 0 |
| 产品 Bug | 1 |


## 真实产品 Bug

### BUG-01（severity=critical）· element_visible + no_network_error + no_console_error + text_contains + element_count

- 关联场景：proxy-serves-worktree-static-root、proxy-reverses-api-to-main-server、proxy-passthrough-sse-no-buffer、baseurl-env-override-applied
- 描述：per-run 隔离测试服务未正确以 worktree 副本的 core/dashboard/static/ 作为静态根：app.js 返回 404，SPA 脚本无法加载，所有由 JS 动态渲染的内容（#main .page-title、.stat-tile、文本『跨项目概览』、table.spec-table、tr.spec-row）均缺失；同时 playwright.config.js 未读取框架注入的 V2_BASE_URL（当前误用 PLAYWRIGHT_TEST_BASE_URL），baseURL 注入未生效。四项以 JS 渲染为前置的验证场景全部失败，而仅断言静态 HTML 元素（#main、#btn-overview、#btn-config）的场景在 8765 上正常通过。
- 根因：隔离测试服务（dev-server.mjs）静态资源服务配置错误：index.html 可命中，但脚本资源 /app.js 未按 worktree 静态根提供（404），导致 SPA 不启动；且 playwright.config.js 的 baseURL 环境变量名与规范（V2_BASE_URL）不一致，框架注入的地址未被读取。根因统一指向『dev-server 静态根未指向 worktree 副本』这一能力缺口。
- 证据：
  - report_failed_scenarios: 4
  - passed_static_only_scenarios: ["proxy-port-unique-vs-main-server", "main-worktree-zero-pollution-invariant", "service-cleanup-after-run-terminal"]
  - captured_404: 404 http://127.0.0.1:8765/app.js（场景 proxy-serves-worktree-static-root，no_network_error 断言）
  - console_errors: ["[error] Failed to load resource: the server responded with a status of 404 (File not found)（场景 proxy-serves-worktree-static-root，no_console_error 断言）"]
  - config_mismatch: tests/v2/playwright.config.js:5 使用 process.env.PLAYWRIGHT_TEST_BASE_URL，spec/tasks 要求 V2_BASE_URL
  - dev_server_task_status: tasks.md 中 1.1（dev-server.mjs）与 1.2（playwright.config.js 改用 V2_BASE_URL）均未勾选，能力未落地
  - posthoc_probe: 测试时间之后探测：8765 当前返回标题为『Fenix New Tab』的无关 Vite 应用，且 /app.js、/style.css 均 404，佐证 8765 从未正确提供 dashboard 静态资源（环境漂移，仅作佐证）


## 场景结果

| 场景 | 状态 | 失败断言 |
| --- | --- | --- |
| proxy-serves-worktree-static-root | fail | 5/5 |
| proxy-reverses-api-to-main-server | fail | 3/5 |
| proxy-passthrough-sse-no-buffer | fail | 1/3 |
| proxy-port-unique-vs-main-server | pass | 0/3 |
| baseurl-env-override-applied | fail | 3/4 |
| main-worktree-zero-pollution-invariant | pass | 0/3 |
| service-cleanup-after-run-terminal | pass | 0/3 |
