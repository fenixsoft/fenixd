## Why

fenixd agent 的 LLM 路由被 `~/.claude/settings.json` 的 `env` 块劫持：claude CLI 的 settings.json env 优先级高于进程环境变量，导致 `.fenix/config.yaml` 中通过 `agents.models` + `llm.providers` 给 agent 配置的 Provider（baseurl/apikey/model）注入后**并不生效**，agent 始终被强制路由到用户会话的 LLM 通道（cc-switch 网关 127.0.0.1:15721）。后果是 agent 与用户会话共享同一账号/配额，既无法隔离配额与故障影响面，也放大了网关故障（500）与用量配额（429）对 agent 的冲击。

## What Changes

- 当 agent 角色配置了 Provider（`agents.models.<role>.provider` 引用 `llm.providers`）时，agent 子进程改为**完全隔离**运行：设置 `CLAUDE_CONFIG_DIR` 指向独立配置目录，彻底绕过 `~/.claude/settings.json` 的 env 覆盖，使 Provider 的 baseurl/apikey/model **绝对生效**。
- 隔离配置目录保留 agent 依赖的插件与技能：symlink `~/.claude/skills` 与 `~/.claude/plugins`，并在隔离 `settings.json` 中带入 `enabledPlugins`（superpowers）与 `hooks`（block-image-read），保证 playwright-cli、superpowers 等子代理能力不丢失。
- 未配置 Provider 时保持现状：claude 子进程直接以当前 `~/.claude/settings.json` 启动（base/token 走 settings.json，仅保留 `--model subagent_model` 覆盖）。
- 纠正现有错误假设：Provider 生效不再依赖进程环境变量覆盖（该方式被 settings.json env 覆盖），改为 CLAUDE_CONFIG_DIR 隔离实现。

## Capabilities

### New Capabilities
- `agent-llm-isolation`: agent 子进程 LLM 通道的选择与强制生效——配置了 Provider 时完全隔离并优先使用该 Provider；未配置时透传当前 settings.json。

### Modified Capabilities

无（当前 `spec/specs/` 无活跃 spec，本变更引入新能力）。

## Impact

- `core/agent_runner.py`：`_run_claude` / `_execute_agent` 增加 `CLAUDE_CONFIG_DIR` 隔离逻辑，以及隔离配置目录（settings.json + symlinks）的按需生成。
- `.fenix/` 下新增 `agent-config/<provider>/` 目录（`.fenix/` 已被 gitignore，不入版本控制）。
- `core/config.py`：无需改动（`get_agent_model_assignment` 已可返回 provider 配置）；顺带确认 `administrator` 角色是否纳入已知角色（非本变更重点）。
- 无新增依赖，纯 Python 标准库（`pathlib`/`shutil`/`os`）。
