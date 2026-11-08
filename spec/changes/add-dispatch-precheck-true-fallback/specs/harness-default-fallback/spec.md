# harness-default-fallback 规范（修改）

> 修改既有能力 `harness-default-fallback`（spec/changes/add-harness-default-key-fallback/specs/harness-default-fallback/spec.md）。
> 背景：该能力声明了「dsh 无分配省略 `--patch`、按 profile 自身配置默认档启动」的对称回落语义，
> 但 dsh-bundle `modelConfig.ts` 在插件创建期无条件断言 `config.model` 显式存在（「绝不回退 dsh
> 默认档」旧纪律残留），无 patch 即 StartupError——声明的 dsh 形态回落实际不可达。本变更在
> bundle 侧兑现该语义（用户 2026-11-08 裁定：真对称回落）。

## MODIFIED Requirements

### Requirement: 无分配时按 harness 自身配置启动（对称回落）

系统 SHALL 在 `SpawnRequest` 无 `agents.models` 分配渲染的 provider 链时，按各 harness 自身配置启动车道，MUST NOT 以预检错误拒绝 spawn：

- claude 适配器：环境继承 + CLI 默认档（现状行为，保持不变）
- dsh 适配器：省略 `--patch`（不写 patch 文件、argv 不携带该参数），由 dsh 按 profile 自身配置的默认模型启动；`build_env` 无 apikey 桥接（不设 `FENIX_DSH_PROVIDER_API_KEY`）
- **dsh-bundle 侧（本变更补齐）**：fenix profile 的 modelConfig 插件在 `config.model` 整体缺席（无 patch 回落形态）时 MUST NOT 抛「模型未显式配置」StartupError，SHALL 交由 dsh 自身默认模型解析链（dsh-base 通道）供数，并以日志 WARN 留痕回落形态；`headless-runner` 等依赖 `agentDefaultModel`/`fenixModelConfig` 服务的插件 SHALL 正常激活

显式提供了部分 provider 链但仍缺要素的形态（配置笔误）仍 MUST 报 `DshSpawnConfigError`（笔误防护保留，bundle 侧对应「`config.model` 在场但要素缺失」保持 fail-fast）。

#### Scenario: dsh 无分配 spawn 成功且不带 patch

- **WHEN** `agents.models` 无该 Agent 角色分配，harness=dsh，发起 spawn
- **THEN** `build_spawn_spec` 正常返回 `SpawnSpec`，argv 不含 `--patch`，环境不含 `FENIX_DSH_PROVIDER_API_KEY`，不抛 `DshSpawnConfigError`

#### Scenario: dsh 无 patch 时 fenix profile 以 dsh 默认档完成启动

- **WHEN** dsh 以 fenix profile 启动且无 `--patch`（`config.model` 缺席）
- **THEN** modelConfig 插件不抛 StartupError，日志含回落 WARN；`agentDefaultModel`/`fenixModelConfig` 服务可用，`headless-runner`（required）激活，dsh 进程存活并以 dsh 默认模型执行任务

#### Scenario: dsh 部分链仍报错

- **WHEN** `SpawnRequest.env_overrides` 仅含 `ANTHROPIC_BASE_URL`（缺 apikey/model）
- **THEN** 抛 `DshSpawnConfigError`（笔误防护语义不变）

#### Scenario: bundle 侧部分配置仍 fail-fast

- **WHEN** patch/config 提供了 `config.model` 但 `baseURL`/`apiKeyEnv` 任一缺失或为空
- **THEN** modelConfig 插件以「模型未显式配置」fail-fast（笔误防护保留）

#### Scenario: claude 无分配 spawn 成功

- **WHEN** `agents.models` 无分配，harness=claude，发起 spawn
- **THEN** spawn 成功，环境按既有 env_mode 语义继承，行为与本 SPEC 合入前一致

### Requirement: 回落 WARN 观察钩子（一次性）

系统 SHALL 在回落形态生效时（SpawnRequest 无显式 provider 链）发一次 `WARNING` 日志留痕，每 daemon 进程每 adapter 至多一次（进程级去重）；MUST NOT 拒绝 spawn。WARNING 文案 MUST 含「未分配 provider 链，回落 harness 默认配置」语义与角色名。

补充 bundle 侧观测面：bundle 侧回落形态（`config.model` 整体缺席）生效时 SHALL 在 dsh 侧日志留痕一条回落 WARN（含「config.model 缺席，回落 dsh 默认档」语义），使启动诊断一眼可辨回落形态与显式链形态。

#### Scenario: 回落 WARN 每进程仅一次

- **WHEN** 同一 daemon 进程内连续发起 3 次无分配 spawn（同 harness）
- **THEN** 仅第 1 次产生 WARNING 留痕，第 2/3 次静默正常 spawn

#### Scenario: bundle 侧回落留痕

- **WHEN** fenix profile 无 patch 启动、回落 dsh 默认档
- **THEN** dsh 启动日志/诊断含回落 WARN；显式链启动（patch 在场）不产生该 WARN

## ADDED Requirements

### Requirement: 显式链形态不受回落语义改写（回归红线）

系统 SHALL 保持显式全链 spawn 产物逐字节恒定：argv 含 `--patch` 且 patch 文件落盘渲染 model/baseURL 三要素、env 桥接 `FENIX_DSH_PROVIDER_API_KEY`、`ANTHROPIC_BASE_URL`/`ANTHROPIC_API_KEY` 两 consumed 键不透传子进程。

#### Scenario: 显式链 spawn 产物字节级不变

- **WHEN** provider 链三要素齐全，harness=dsh，发起 spawn
- **THEN** argv 含 `--patch` 且 patch 渲染内容与引入本变更前一致；bundle 侧 modelConfig 显式链校验路径行为不变
