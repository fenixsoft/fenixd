# Agent LLM Isolation Spec

## ADDED Requirements

### Requirement: Provider 配置时 agent 完全隔离并优先使用该 Provider
当 `.fenix/config.yaml` 中 `agents.models.<role>.provider` 引用了 `llm.providers` 中的 Provider 时，agent 子进程 SHALL 以完全隔离方式运行：设置 `CLAUDE_CONFIG_DIR` 指向独立的 agent 配置目录，彻底绕过 `~/.claude/settings.json` 的 env 覆盖，使 Provider 的 `baseurl`/`apikey`/`model` 绝对生效。隔离目录 SHALL 按需生成且幂等。

#### Scenario: 已配置 Provider 时请求打到 Provider
- **WHEN** 用户为 implementer 角色配置了指向 Provider 的 `agents.models.implementer.provider`
- **THEN** 启动的 `claude` 子进程带 `CLAUDE_CONFIG_DIR` 环境变量，且 Provider 的 baseurl/apikey/model 生效，请求不经过 `~/.claude/settings.json` 指定的 base URL

#### Scenario: 隔离目录按需生成且幂等
- **WHEN** 多个 agent 并发首次使用同一 Provider
- **THEN** 隔离配置目录被安全地创建一次，重复创建不产生副作用

### Requirement: 隔离不丢失 agent 依赖的插件与技能
隔离配置目录 SHALL 保留 agent 子代理依赖的插件与技能：`enabledPlugins` 从 `~/.claude/settings.json` 复制（含 superpowers），`skills` 与 `plugins` 以 symlink 指向 `~/.claude` 对应目录，PreToolUse hooks（block-image-read）保留。agent 运行期间 MUST 仍可用 playwright-cli 与 superpowers 技能。

#### Scenario: 隔离后技能与插件完整
- **WHEN** agent 子进程在 Provider 隔离模式下启动
- **THEN** 其技能列表包含 `playwright-cli` 且加载 superpowers 插件，与未隔离时一致

#### Scenario: 源目录缺失时优雅降级
- **WHEN** `~/.claude/skills` 或 `~/.claude/plugins` 不存在
- **THEN** 隔离目录跳过对应 symlink，agent 仍正常启动，不报错

### Requirement: 未配置 Provider 时透传当前 settings.json
当 agent 角色未配置 Provider 时，agent 子进程 SHALL 直接以当前 `~/.claude/settings.json` 启动：不设置 `CLAUDE_CONFIG_DIR`、不注入 Provider 环境变量，仅保留 `--model agents.subagent_model` 覆盖。此路径行为 MUST 与现状一致。

#### Scenario: 未配置 Provider 时保持现状
- **WHEN** `agents.models.<role>` 未配置或为空
- **THEN** `claude` 子进程不携带 `CLAUDE_CONFIG_DIR`，base URL 与 token 来自 `~/.claude/settings.json`，且带 `--model <subagent_model>`

### Requirement: Provider 凭据不落盘
Provider 的 `apikey` 等敏感凭据 SHALL 经进程环境变量注入子进程，不得写入隔离目录的 settings.json 文件。隔离 settings.json 仅可包含模型映射类环境变量（如 `ANTHROPIC_DEFAULT_*`、`CLAUDE_CODE_SUBAGENT_MODEL`、`CLAUDE_CODE_MAX_CONTEXT_TOKENS`），不得包含 Provider 的 baseurl 与 apikey。

#### Scenario: 凭据仅存于进程环境
- **WHEN** 已配置 Provider 的 agent 启动
- **THEN** 隔离目录中的 settings.json 不包含 Provider 的 apikey 与 baseurl 明文，连接凭据仅存在于子进程环境变量
