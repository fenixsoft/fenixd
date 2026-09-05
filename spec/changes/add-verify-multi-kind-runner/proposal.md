# Proposal: add-verify-multi-kind-runner

## Why

当前验证链的场景模型、断言库、引擎与契约全部以 web 应用为唯一形态假设：场景验收硬性要求 `navigate` 浏览器步骤（`core/verify_engine/scenarios.py`），18 种断言全部基于 Playwright DOM，引擎无条件启动浏览器，契约 serve 只支持「起一个 HTTP 服务」。纯 CLI 与纯 API 类 spec 因此**没有任何可行的验证通路**——CLI spec 在验收门就被整体拒绝；API 验证只能用 web 场景 GET 端点 `text_contains` 断 JSON 文本凑合（`mock_api` 断流假阴性放大器已实证烧钱）。近期 fenixd 自身即有 CLI/API 型 spec 待验（成本统计命令、dashboard 端点改造），同时这是框架完整性缺口（非 web 项目无法接入 fenixd）。

## What Changes

- **场景模型加 `kind` 字段**（web/cli/api，缺省 web，存量零迁移）：kind 是场景级字段，混合 spec = 场景集混排 + `depends_on` 跨 kind 编排；单场景内不混排步骤类型
- **三套结构化断言词表**：CLI（exit_code / file_exists / output_match / file_content / json_output / dir_contains）与 API（status_code / json_path / response_header / body_contains / json_schema / latency_under，含 sse_connect 流式步骤），延续「第 1-3 层失败=一定是 Bug」确定性承诺，**不带脚本逃生舱**
- **CLI 步骤特异语义**：非零退出码不自动判失败（错误路径测试预期），由 exit_code 断言仲裁；超时=步骤失败；信号死亡=error；输出捕获 64KB 截断
- **引擎 Runner 插件化**：抽 Runner 接口（validate/execute/setup/teardown/probe_env），WebRunner/ApiRunner/CliRunner 独立模块，engine 瘦身为纯调度（642→约 250 行）；按场景集实际 kind lazy setup——纯 CLI/API 轮次不启动浏览器
- **契约形态按场景集反推**（零新增字段）：纯 cli 场景集 serve/ready 全省且不回退 commands.start；含 web/api 场景则 serve 必须有效（现状不变）；BASE_URL 铁律扩展——API 场景 URL origin 全量改写、CLI `run` 步骤自动注入 `FENIX_VERIFY_BASE_URL`/`FENIX_VERIFY_PORT`
- **下游字段驱动渲染零迁移**：report.json scenarios 透传 kind；dashboard 场景页签 kind 徽章、断言详情按字段有无自适应、截图区空占位；verdict 链（assertion_triage 四分类）预期零改动，列入回归；scenarios.json 条目加可选 kind
- **planner 侧与验收门**：planner-plan.md 增加 kind 选择判定树与三套词表引导（权威源标注为 scenarios.py VALID 常量，防枚举双源漂移）；明确「HTTP 端点验证用 api 场景」治理老坑；验收门 per-kind 词表校验、跨 kind 步骤误用与无 serve 配置错误打回 plan；verifier/judge/fast-track 提示词截图措辞中立化
- **渐进落地**：PR1 抽 WebRunner 等价重构（全量回归）→ PR2 ApiRunner → PR3 CliRunner

## Capabilities

### New Capabilities

- `multi-kind-scenario-model`: 场景 kind 字段、三套词表（步骤/断言/字段口径）、CLI 特异执行语义、API 响应命名捕获、证据截断纪律、per-kind 场景验收校验
- `verify-runner-engine`: Runner 接口与分派、引擎调度边界、lazy setup、契约形态按场景集反推、BASE_URL 注入范围扩展、环境门 kind 适配
- `multi-kind-planning-guidance`: planner 词表引导与 kind 选择规则、验收门打回路径、prompt 措辞中立化、docs/help 验证文档更新
- `multi-kind-report-compat`: report.json kind 透传、dashboard 字段驱动渲染、verdict 链与场景冻结零迁移兼容

### Modified Capabilities

（无——spec/specs/ 当前无活跃能力声明，验证链既有需求散落在归档 spec 中，本 spec 全部为 ADDED）

## Impact

- **核心代码**：`core/verify_engine/`（scenarios.py / engine.py / 新增 runner 与断言模块）、`core/verify_contract.py`、`core/pm_engine/verification.py`（serve 需求反推）、`core/verify_scenarios.py`（ScenarioEntry.kind）
- **回归确认（预期零改动）**：`core/verdict_check.py`、`core/fast_track_result.py`、验证进度/gate/洗白门禁
- **前端**：dashboard spec detail 场景页签（kind 徽章、断言详情渲染、截图占位）
- **提示词**：`agents/planner-plan.md`、`agents/verifier.md`、`agents/planner-judge.md`、`agents/fast-track.md`（注意 prompt 双落点约定：改前 merge main + merge-tree 自证）
- **依赖**：新增 `httpx`（ApiRunner）；`jsonschema`（json_schema 断言，可选降级）
- **文档**：`docs/help/05-verification.md`（主）、`02-concepts.md`、`08-config.md`、`01-quick-start.md`（核对）
- **风险**：等价重构回归面大（PR1 触及全部现有 web 验证路径）；SSE 步骤实现复杂度高（允许降为 fast-follow）
