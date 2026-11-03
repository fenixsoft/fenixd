# harness-default-fallback 规范

## ADDED Requirements

### Requirement: 无分配时按 harness 自身配置启动（对称回落）

系统 SHALL 在 `SpawnRequest` 无 `agents.models` 分配渲染的 provider 链时，按各 harness 自身配置启动车道，MUST NOT 以预检错误拒绝 spawn：

- claude 适配器：环境继承 + CLI 默认档（现状行为，保持不变）
- dsh 适配器：省略 `--patch`（不写 patch 文件、argv 不携带该参数），由 dsh 按 profile 自身配置的默认模型启动；`build_env` 无 apikey 桥接（不设 `FENIX_DSH_PROVIDER_API_KEY`）

显式提供了部分 provider 链但仍缺要素的形态（配置笔误）仍 MUST 报 `DshSpawnConfigError`（笔误防护保留）。

#### Scenario: dsh 无分配 spawn 成功且不带 patch

- **WHEN** `agents.models` 无该 Agent 角色分配，harness=dsh，发起 spawn
- **THEN** `build_spawn_spec` 正常返回 `SpawnSpec`，argv 不含 `--patch`，环境不含 `FENIX_DSH_PROVIDER_API_KEY`，不抛 `DshSpawnConfigError`

#### Scenario: dsh 部分链仍报错

- **WHEN** `SpawnRequest.env_overrides` 仅含 `ANTHROPIC_BASE_URL`（缺 apikey/model）
- **THEN** 抛 `DshSpawnConfigError`（笔误防护语义不变）

#### Scenario: claude 无分配 spawn 成功

- **WHEN** `agents.models` 无分配，harness=claude，发起 spawn
- **THEN** spawn 成功，环境按既有 env_mode 语义继承，行为与本 SPEC 合入前一致

### Requirement: 回落 WARN 观察钩子（一次性）

系统 SHALL 在回落形态生效时（SpawnRequest 无显式 provider 链）发一次 `WARNING` 日志留痕，每 daemon 进程每 adapter 至多一次（进程级去重）；MUST NOT 拒绝 spawn。WARNING 文案 MUST 含「未分配 provider 链，回落 harness 默认配置」语义与角色名。

#### Scenario: 回落 WARN 每进程仅一次

- **WHEN** 同一 daemon 进程内连续发起 3 次无分配 spawn（同 harness）
- **THEN** 仅第 1 次产生 WARNING 留痕，第 2/3 次静默正常 spawn

### Requirement: 归因降级标记

回落 run 的 run metrics 上下文 SHALL 附归因降级标记（`provider_source: "harness-default"`），provider/model 维持既有 null/钉死形态；消费侧（计费/健康检查）可据此区分「显式链 run」与「回落 run」。

#### Scenario: 回落 run metrics 带标记

- **WHEN** 一次无分配 spawn 的 run 落 run metrics
- **THEN** metrics 上下文含 `provider_source: "harness-default"`；显式链 run 不含该键
