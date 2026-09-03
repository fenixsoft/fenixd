## Why

配置页目前将 LLM Provider、Agent 模型分配、并行度、审批模式四个区块垂直平铺在单页长表单中，页面过长、结构不聚焦；且 Administrator 角色的模型不在 Agent 分配区，使用独立的 `admin.agent_model` 单字段（无 Provider 概念），与其余 Agent 的「Provider + 模型」分配方式不一致，只能在配置文件中手填。

## What Changes

1. **配置页页签化**：配置页由单页平铺改为 4 个页签——「LLM Provider」「Agent 模型分配」「并行度设置」「审批模式」，各页签内容与原区块一致，保存按钮与生效提示保留在页签区下方（仍为全局保存，一次写回整个受管配置）。
2. **Agent 模型分配新增 Administrator**：与 implementer/planner/verifier 相同交互（勾选分配 → 选择 Provider → 填模型名），写入 `agents.models.administrator = {provider, model}`。
3. **后端角色注册与运行时解析**：`KNOWN_AGENT_TYPES` 增加 `administrator`；`run_administrator` 优先使用 `agents.models.administrator` 的 assignment（含 Provider env 注入：baseurl/apikey/自定义 env），未配置时回退 `admin.agent_model` → 默认网关模型常量（现有行为不变，兼容已有配置）。
4. **配置校验与受管键**：`agents.models.administrator` 通过现有 `_validate_agent_models` 校验（因 KNOWN_AGENT_TYPES 已包含它），无需新校验路径。

## Capabilities

### New Capabilities

- `config-tabs`: 配置页页签化布局（4 页签切换、页签状态保持、全局保存）。
- `administrator-model-assignment`: Administrator 角色的模型分配——写入 `agents.models.administrator`，运行时按 assignment 注入 Provider 环境并回退旧键。

### Modified Capabilities

<!-- 无：页签化不改变现有各配置项语义；administrator 分配为全新能力，现有 admin.agent_model 键保持兼容不改动。 -->

## Impact

- `core/dashboard/static/app.js`：`renderConfig` 改为页签渲染；`KNOWN_AGENT_TYPES` 前端的渲染列表增加 administrator；`hydrateConfigPage`/保存逻辑按页签容器调整选择器。
- `core/dashboard/static/style.css`：新增页签样式（复用现有 fenix bundle 的 tab 样式或新增 `.config-tabs`）。
- `core/config.py`：`KNOWN_AGENT_TYPES` 常量增加 `administrator`（校验自动覆盖）。
- `core/agent_runner.py`：`run_administrator` 改用 `_get_agent_model_assignment("administrator")` 解析 Provider+模型，assignment 存在时向 `_run_claude` 传 `env_overrides`（provider 直连），并保留 `admin.agent_model`/默认网关回退链。
- `core/dashboard/data.py`：受管键（llm / agents / gates）已覆盖新键，无需变更；确认 `read_config`/`write_config` 透传 `agents.models.administrator`。
- 与进行中的 `improve-agent-config-and-verify-resume`（agent run params）同改 `agents.models` 区域，需在合并时注意无冲突。