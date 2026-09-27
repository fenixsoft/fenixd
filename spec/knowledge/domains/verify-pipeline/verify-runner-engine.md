# 验证执行引擎
<!-- knowledge: capability=verify-runner-engine rev=2 sources=spec/archive/2026-09-12-add-verify-multi-kind-runner,spec/archive/2026-09-14-fix-verify-cli-cwd-isolation -->

场景执行的 Runner 插件化引擎：按 scenario.kind 查注册表分派，按场景集反推契约形态，执行根与簿记根分离。

## 现行规则

- Runner 接口与分派：Runner 接口含 `kind` 标识、`validate(scenario)`（返回验收错误列表）、`setup()`（本轮一次性准备）、`execute(scenario)`（返回 step_results / assertion_results / evidence）、`teardown()`、`probe_env()`（环境探针）；引擎仅按 `scenario.kind` 查注册表分派，调度代码不含 per-kind 的 if/else 执行分支（新增第四种 kind 仅需新增 Runner 模块并注册）。注册表：web→WebRunner（浏览器/断言/截图/视觉对比）、api→ApiRunner（httpx 驱动，每场景独立 client 隔离 cookie）、cli→CliRunner（subprocess 驱动）。
- lazy setup 与资源纪律：仅对场景集中实际出现过的 kind 执行 setup/teardown；纯 CLI 或纯 API 场景集不启动浏览器（不产生 Playwright/Chromium 依赖）；Runner setup 失败（如 ApiRunner 依赖缺失）按验证环境错误处理，不判 bug-found。
- 引擎调度边界：验收门收集（逐场景委托 Runner.validate）、拓扑分批+信号量并行、Runner 返回结构组装与场景状态判定、进度写盘、报告构建与保存、环境门后置分类骨架（候选识别→整轮一次探针→批量降级 blocked-env）。探针本体委托 Runner：web 保持 HTTP+推流；api 对 base_url 执行契约 ready 探针（连接失败类=环境候选）；cli 不做降级探针（超时=fail）。
- 契约形态按场景集反推（零新增字段）：纯 cli 场景集 serve/ready 全省、不回退 commands.start（无人消费的实例不拉起），`_ensure_app_reachable` 在无实例形态下短路；含 web 或 api 场景时 serve 段（或 commands.start 兜底）必须有效，缺失时验收报明确错误打回 plan，不静默跑空；混合场景集 serve 照常启动，cli 场景额外获得实例环境变量注入。prepare 失败是纯 cli 场景集的唯一环境门。
- BASE_URL 注入范围：覆盖 `navigate`、`http_request` / `sse_connect` 的 `url` 字段（origin 全量改写、路径保留，planner 写什么都被覆盖）；CLI `run` 步骤执行环境自动注入 `FENIX_VERIFY_BASE_URL` 与 `FENIX_VERIFY_PORT`，框架值优先——场景 `env` 中同名变量被框架值覆盖；无实例形态下上述改写与注入为无害空操作。
- base_url 统一供给：验证开始时从契约确定本次实例 base_url 并统一传给各 Runner（探针与断言上下文共用），不从候选场景 navigate 步骤文本正则考古 base_url（场景失联时该回退会漏判）。
- cli 执行根隔离：验证轮存在 serving worktree（command-worktree）时，引擎将该 worktree 根作为场景执行根下发给各 Runner，`CliRunner` 对未显式声明 `cwd` 的步骤以执行根为缺省 cwd（seed 型步骤写入落在本轮验证树内）；无 serving worktree 的验证轮 cli 缺省 cwd 维持主树项目根。引擎簿记（`.fenix/verify-progress/` 下的场景加载、报告、进度、截图）固定主树 `.fenix`，不随执行根改变。

## 溯源

- 史前复原（存量基线） — 验证引擎按场景步骤驱动浏览器执行动作与断言，产出结构化逐步骤判定结果供裁决消费
- 2026-09-12 add-verify-multi-kind-runner — Runner 插件化重构：web 单形态假设退役，新增 api/cli 双 Runner、调度无 kind 分支、lazy setup、契约形态按场景集反推、BASE_URL 注入扩展与 base_url 契约统一供给
- 2026-09-14 fix-verify-cli-cwd-isolation — cli 步骤缺省 cwd 收敛为本轮 serving worktree 根（执行根曾错为主树根，seed 型场景把测试夹具写进主树 `.fenix/STATE.md` 与 `spec/changes/`，被 daemon 当真需求收编自动派发、反复烧钱），引擎簿记路径不变
