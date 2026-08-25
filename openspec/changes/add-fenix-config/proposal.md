# Proposal: 为 Fenixd 增加 LLM 模型分配与审批模式配置

## Why

目前 Fenixd 的所有 Agent（implementer / planner-plan / planner-judge / verifier）统一使用 daemon 启动时环境变量（`ANTHROPIC_MODEL`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_API_KEY`）所指向的同一个模型，无法按 Agent 角色区分模型；且审批是唯一的人工门禁，所有 `done` 状态的 SPEC 都必须人工通过 `/fenix-approve` 推送。用户希望：

1. 可配置多个 LLM Provider（baseurl / apikey / model 等），并按 Agent 角色分配不同模型（例如 Plan 用 DeepSeek-v4-pro，执行用 DeepSeek-v4-flash）；不分配的 Agent 维持现状（使用 Claude Code 默认模型）。
2. 可配置审批模式：默认手工 approve，也可设置为「推进到 done 后自动 approve」。

以上配置需写入 Fenixd 配置文件（扩展现有 `.fenix/config.yaml`，手工可改），并在 Dashboard 提供可视化界面修改。

## What Changes

- **新增 LLM Provider 注册表配置** `llm.providers`：可定义多个命名 Provider，每个含 `name`、`baseurl`、`apikey`、`model`（默认模型名）等字段。
- **新增 Agent 模型分配配置** `agents.models`：将各 Agent 角色（implementer、planner-plan、planner-judge、verifier）映射到某个 Provider + 模型；未分配的 Agent 使用默认模型（现状行为）。
- **Agent 运行时按分配路由模型**：`agent_runner._run_claude` 为已分配模型的 Agent 注入对应 Provider 的 `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` 环境变量并传 `--model`（保留 claude-code SDK 模型名校验的 workaround，见 design）；未分配则完全维持现状。
- **新增审批模式配置** `gates.approve_mode`：`manual`（默认，现状）或 `auto`。
- **自动审批**：当 `approve_mode=auto` 且 SPEC 推进到 `done` 时，daemon 自动执行 `git push origin fenix/<branch>` 并将状态推进到 `pushed`，移除人工门禁。
- **Dashboard 可视化配置界面**：新增配置页，可编辑 LLM Provider（增删改）、Agent 模型分配、审批模式；写入 `.fenix/config.yaml`，修改后需重启 daemon 生效。
- **配置模板同步**：`config.template.yaml` 同步新增字段说明，保证 `fenix-init` 生成的新项目自带新配置骨架。

## Capabilities

### New Capabilities

- `llm-model-assignment`: LLM Provider 注册表（baseurl / apikey / model）与按 Agent 角色分配模型；未分配时使用默认模型；配置经 `.fenix/config.yaml` 持久化，并在 Dashboard 提供可视化编辑。
- `approve-mode`: 审批模式配置（manual / auto）；`auto` 模式下 SPEC 推进到 done 后 daemon 自动 git push 并标记 pushed；配置经 `.fenix/config.yaml` 持久化，并在 Dashboard 提供可视化编辑。

### Modified Capabilities

<!-- 现有 openspec/specs/ 与归档目录均无已定义能力，本次全部为新增。 -->

## Impact

- **核心代码**：
  - `core/config.py`：新增配置字段校验（`llm.providers`、`agents.models`、`gates.approve_mode`）。
  - `core/agent_runner.py`：`_run_claude` 按 Agent 角色解析模型分配并注入运行环境；`_build_prompt` 需透传 agent_type 到运行层（当前 `_execute_agent` 已持有 agent_type）。
  - `core/pm_engine.py`：`approve_mode=auto` 时在 SPEC 到达 `done` 后自动执行 git push + `approve_push`（需将真实 git push 逻辑从 /fenix-approve skill 下沉到 daemon，或复用可执行路径）。
  - `core/dashboard/server.py`：新增读取/写入配置的 REST 端点（目前仅 GET，需新增写方法）。
  - `core/dashboard/data.py`：配置读写辅助函数。
  - `core/dashboard/static/`：新增「配置」页面（前端视图 + 编辑表单）。
- **配置文件**：`.fenix/config.yaml` 与 `config.template.yaml` 新增 `llm`、`agents.models`、`gates.approve_mode` 字段。
- **Skill**：`fenix-approve` 说明自动模式下可跳过人工门禁；`fenix-status` / `fenix-dashboard` 展示当前审批模式。
- **安全考量**：Provider 的 `apikey` 为敏感信息；配置写入 `.fenix/config.yaml`（已 gitignore），Dashboard 为本地 127.0.0.1 服务，符合现有安全边界。自动审批会真实推送 git 分支到远端，属显著外向行为，默认不开启。
- **测试**：`tests/test_core.py` 增加配置解析、模型分配路由、审批模式判定等单元测试。
