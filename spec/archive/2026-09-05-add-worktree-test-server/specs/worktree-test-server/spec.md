# worktree-test-server 能力增量（add-worktree-test-server）

> 消除「worktree 开发 + 主仓测试服务」错位：每个 implementer/verifier 运行的测试请求 MUST 落在其 worktree 副本上，主仓工作区在其运行期间保持零写入。

## ADDED Requirements

### Requirement: per-run 隔离测试服务

框架在派发 implementer/verifier 进入 worktree 前，MUST 为该运行启动专属测试服务并注入其地址：

1. 服务静态根目录为该运行的 worktree（`core/dashboard/static/`），保证页面与脚本请求命中 worktree 副本。
2. 未命中静态资源的后端请求（`/api/*`、SSE 流）MUST 反向代理至主服务（`http://127.0.0.1:8787`），保持真实后端集成验证；代理 MUST 透传流式响应（禁用缓冲、保留 EventStream 头）。
3. 端口 MUST 唯一分配（在主服务与并发运行之间不冲突），地址经环境变量（如 `V2_BASE_URL`）注入运行环境。
4. 运行终态（成功/失败/异常终止/进程被杀）后框架 MUST 回收该服务进程；框架自身重启时 MUST 清理遗留服务。

#### Scenario: implementer 测试命中 worktree 副本

- **WHEN** implementer 在 worktree 内运行 Playwright 测试（baseURL 来自注入的 V2_BASE_URL）
- **THEN** 页面与脚本请求返回 worktree 版本（修改 worktree 的 app.js 立即可测），且后端 API/SSE 行为与主服务一致

#### Scenario: 运行结束后服务回收

- **WHEN** 某运行到达终态或其进程被杀
- **THEN** 对应测试服务进程被终止，端口释放；主仓 8787 服务不受影响

#### Scenario: 主仓工作区零污染

- **WHEN** implementer 为让测试通过而修改页面/脚本
- **THEN** 其修改仅落在 worktree 内；主仓工作区的被跟踪文件在该运行全程保持未修改

### Requirement: baseURL 参数化

`tests/v2/playwright.config.js` 的 baseURL MUST 支持环境变量覆盖（框架注入），未设置时回退 `http://127.0.0.1:8787`。既有本地人工调试流程（直接跑 `npx playwright test`）行为不变。

#### Scenario: 环境变量生效

- **WHEN** 以 `V2_BASE_URL=http://127.0.0.1:<port> npx playwright test` 运行
- **THEN** 所有测试请求指向该地址

#### Scenario: 缺省回退兼容

- **WHEN** 未设置环境变量直接运行测试
- **THEN** baseURL 回退为 `http://127.0.0.1:8787`，与现行人工调试行为一致
