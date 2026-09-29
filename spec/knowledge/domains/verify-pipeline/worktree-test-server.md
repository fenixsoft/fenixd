# worktree 被测服务供给
<!-- knowledge: capability=worktree-test-server rev=1 sources=spec/archive/2026-09-05-add-worktree-test-server -->

per-run 隔离测试服务：implementer/verifier 的测试请求落在其 worktree 副本上，主仓工作区在运行期间零写入。

## 现行规则

- per-run 专属服务：框架在派发 implementer/verifier 进入 worktree 前，为该运行启动专属测试服务并注入地址——静态根目录为该运行的 worktree（`core/dashboard/static/`），页面与脚本请求命中 worktree 副本。
- 后端反代主服务：未命中静态资源的后端请求（`/api/*`、SSE 流）反向代理至主服务（`http://127.0.0.1:8787`），保持真实后端集成验证；代理透传流式响应（禁用缓冲、保留 EventStream 头）。
- 端口唯一与地址注入：端口唯一分配（主服务与并发运行之间不冲突），地址经环境变量（如 `V2_BASE_URL`）注入运行环境。
- 服务回收：运行终态（成功/失败/异常终止/进程被杀）后框架回收该服务进程并释放端口；框架自身重启时清理遗留服务；主仓 8787 服务不受影响。
- baseURL 参数化：`tests/v2/playwright.config.js` 的 baseURL 支持环境变量覆盖（框架派发时设置），未设置时回退 `http://127.0.0.1:8787`；既有本地人工调试流程（直接 `npx playwright test`）行为不变。
- 零污染不变量：implementer/verifier 运行期间不修改主仓工作区的被跟踪文件；测试断言针对 worktree 副本（修改 worktree 内页面/脚本立即可测），主仓工作区被跟踪文件在该运行全程保持未修改。

## 溯源

- 史前复原（存量基线） — worktree 内 dev-server 生命周期由框架托管，孤儿清扫按存活归属判定，防 spec 锁误判
- [2026-09-05 add-worktree-test-server](spec/archive/2026-09-05-add-worktree-test-server/) — 新增 per-run 隔离测试服务与 baseURL 环境变量注入（测试 baseURL 曾固定指向主仓 8787，implementer 为让测试通过直改主仓工作区文件，主树反复被污染且 merge-back 被「local changes would be overwritten」熔断）
