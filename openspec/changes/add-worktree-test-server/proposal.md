# Proposal: add-worktree-test-server

## Why

v2 页面 implementer 在 worktree 内开发，但 Playwright 测试的 baseURL 指向 `http://127.0.0.1:8787`——主仓 dashboard 服务。于是 implementer 为让测试通过，**直接修改主仓工作区文件**（app.js/bridge.js/app.json/页面 JSON 均已发生），导致：主仓树反复被污染、merge-back 被「local changes would be overwritten」熔断（v2-overview-page 实测）、每次都需人工比对清理。这是结构性缺陷，剩余 5 个 v2 spec（run-stream-modal、alerts-activities、admin-doc-modals、acceptance-suite、cutover）会逐个复现。

## What Changes

- 新增**每运行独立测试服务**：框架在派发 implementer/verifier 前于其 worktree 内启动专属测试服务（静态资源由 worktree 副本提供，后端 API/SSE 反向代理至主服务 8787 以保持真实集成验证），端口唯一分配；运行结束后框架回收服务（含异常路径）。
- `tests/v2/playwright.config.js` 的 baseURL 改为环境变量注入（框架派发时设置），缺省回退 `http://127.0.0.1:8787` 保持人工调试兼容。
- **不变量**：implementer/verifier 运行期间 MUST NOT 修改主仓工作区的被跟踪文件；所有测试断言针对 worktree 副本。
- 主服务 8787 与人工调试流程不受影响。

## Capabilities

### New Capabilities
- `worktree-test-server`: per-run 隔离测试服务的生命周期管理与 baseURL 注入，消除「worktree 开发 + 主仓测试」错位。

## Impact

- **代码**：`.fenix/core/agent_runner.py` 或 `worktree_manager.py`（服务生命周期）、`tests/v2/`（代理脚本 + config 参数化）
- **行为**：implementer 测试自证其 worktree 副本；主仓树零污染；merge-back 不再被脏树熔断
- **成本**：每个运行多一个本地端口服务（轻量代理），可忽略
- **风险**：代理脚本需正确透传 SSE/流式响应（禁用缓冲）；端口分配需避让
