# verify-runner-engine — Runner 插件化引擎与契约形态

## ADDED Requirements

### Requirement: Runner 接口与按 kind 分派

引擎 SHALL 抽象 Runner 接口：`kind` 标识、`validate(scenario)`（返回验收错误列表）、`setup()`（本轮一次性准备）、`execute(scenario)`（返回 step_results / assertion_results / evidence）、`teardown()`、`probe_env()`（环境探针）。引擎 MUST 仅按 `scenario.kind` 查注册表分派，调度代码 MUST NOT 包含 per-kind 的 if/else 执行分支。初始注册：`web`→WebRunner（现有浏览器/断言/截图/视觉对比逻辑整体归位，行为不变）、`api`→ApiRunner（httpx 驱动，每场景独立 client 隔离 cookie）、`cli`→CliRunner（subprocess 驱动）。

#### Scenario: 调度器无 kind 分支
- **WHEN** 审查引擎调度实现（拓扑排序/并行/进度/报告路径）
- **THEN** 不存在按 kind 分叉的执行逻辑；新增第四种 kind 仅需新增 Runner 模块并注册

#### Scenario: WebRunner 行为等价
- **WHEN** 以既有 web 场景集（含 extension 项目与健康检查路径）分别运行改造前后的引擎
- **THEN** 场景结果（status/step_results/assertion_results/screenshots）语义一致，现有验证测试全绿

### Requirement: lazy setup 与资源纪律

引擎 MUST 仅对场景集中实际出现过的 kind 执行 setup/teardown。纯 CLI 或纯 API 场景集 MUST NOT 启动浏览器（不产生 Playwright/Chromium 依赖）。Runner setup 失败（如 ApiRunner 依赖缺失）按验证环境错误处理，不判 bug-found。

#### Scenario: 纯 CLI 轮次零浏览器
- **WHEN** 场景集全部为 `kind: cli`
- **THEN** 本轮验证进程不启动任何浏览器实例，验证正常完成出报告

#### Scenario: 混合集按需启动
- **WHEN** 场景集含 web 与 cli 两类场景
- **THEN** 仅 WebRunner 与 CliRunner 被 setup，浏览器启动一次供全部 web 场景共用

### Requirement: 引擎调度边界

引擎 SHALL 保留：验收门收集（逐场景委托 Runner.validate）、拓扑分批+信号量并行、Runner 返回结构组装与场景状态判定、进度写盘、报告构建与保存、环境门后置分类骨架（候选识别→整轮一次探针→批量降级 blocked-env）。探针本体 MUST 委托 Runner：web 保持现状（HTTP+推流）；api 对 base_url 执行契约 ready 探针（连接失败类=环境候选）；cli 第 1 版不做降级探针（超时=fail）。

#### Scenario: blocked-env 降级跨 kind 生效
- **WHEN** api 场景因实例失联整批失败且探针确认失联
- **THEN** 候选场景降级 `blocked-env`（计入 warning），不判 bug-found

### Requirement: 契约形态按场景集反推

契约不新增字段。serve/ready 是否必需 MUST 由本轮场景集的 kind 组成反推：
- **纯 cli 场景集**：serve、ready 全省（prepare 失败仍是唯一环境门）；MUST NOT 回退 commands.start；`_ensure_app_reachable` 在无实例形态下短路
- **含 web 或 api 场景**：serve 段（或 commands.start 兜底）必须有效；缺失时验收报明确错误打回 plan，不静默跑空
- **混合场景集**：serve 照常启动，cli 场景额外获得实例环境变量注入

#### Scenario: 纯 CLI 场景集跳过 serve
- **WHEN** 场景集全部为 cli 场景且项目契约无 serve 段（verify.yaml 仅 prepare 或整个缺失）
- **THEN** 验证正常执行 CLI 场景，不尝试启动服务、不报 serve 缺失错误

#### Scenario: 纯 CLI 场景集不回退 commands.start
- **WHEN** 场景集全部为 cli 场景且项目 config 定义了 commands.start
- **THEN** 不启动 commands.start 服务（无人消费的实例不拉起）

#### Scenario: web/api 场景缺 serve 打回
- **WHEN** 场景集含 api 场景，契约无 serve 且无 commands.start
- **THEN** 验收报「场景集含 web/api 场景但无 serve 配置」错误并打回 plan

### Requirement: BASE_URL 注入范围扩展

BASE_URL 铁律 MUST 覆盖三种形态：`navigate`（现状不变）、`http_request` / `sse_connect` 的 `url` 字段做 origin 全量改写（路径保留，planner 写什么都被覆盖）；CLI `run` 步骤执行环境 MUST 自动注入 `FENIX_VERIFY_BASE_URL` 与 `FENIX_VERIFY_PORT`，且框架值优先——场景 `env` 中同名变量被框架值覆盖（防 stale 地址事故同一逻辑）。无实例形态下上述改写与注入为无害空操作。

#### Scenario: API 场景 URL origin 改写
- **WHEN** api 场景 `http_request` url 为 `http://stale-host:9999/api/specs`，本次实例地址为 `http://127.0.0.1:54321`
- **THEN** 实际请求打到 `http://127.0.0.1:54321/api/specs`（路径 `/api/specs` 保留）

#### Scenario: CLI 环境变量框架值优先
- **WHEN** cli 场景 `env` 声明 `FENIX_VERIFY_BASE_URL: "http://localhost:8787"`，本轮实例地址为 `http://127.0.0.1:54321`
- **THEN** 命令实际读到的 `FENIX_VERIFY_BASE_URL` 为 `http://127.0.0.1:54321`

### Requirement: base_url 统一供给

引擎 SHALL 在验证开始时从契约确定本次实例 base_url 并统一传给各 Runner（探针与断言上下文共用），MUST 取代现有「从候选场景 navigate 步骤文本正则考古 base_url」的回退逻辑（该逻辑在场景失联时会漏判）。

#### Scenario: 失联场景不阻碍探针定位
- **WHEN** api 场景全部因实例失联失败，且场景 URL 中不含可考古的 origin 文本
- **THEN** 环境探针仍从契约供给的 base_url 正确探测并降级 blocked-env
