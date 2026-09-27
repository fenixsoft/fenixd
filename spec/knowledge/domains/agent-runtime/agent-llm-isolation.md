<!-- knowledge: capability=agent-llm-isolation rev=1 sources=spec/archive/2026-09-02-add-agent-llm-isolation -->

# 按 Provider 隔离 LLM 凭据与配置目录

agent 角色被指派直连 Provider 时的运行时隔离机制：让 Provider 的连接配置绝对生效，同时不丢 agent 依赖的插件与技能。

## 现行规则

- 隔离触发：`agents.models.<role>.provider` 引用 `llm.providers` 中的 Provider 时，agent 子进程以完全隔离方式运行——设置 `CLAUDE_CONFIG_DIR` 指向独立的 agent 配置目录，彻底绕过 `~/.claude/settings.json` 的 env 覆盖，使该 Provider 的 baseurl/apikey/model 绝对生效。隔离目录按需生成且幂等，多 agent 并发首次使用同一 Provider 时安全地创建一次。
- 技能与插件保留：隔离配置目录保留 agent 子代理依赖的插件与技能——`enabledPlugins` 从 `~/.claude/settings.json` 复制（含 superpowers），`skills` 与 `plugins` 以 symlink 指向 `~/.claude` 对应目录，PreToolUse hooks（block-image-read）保留；agent 运行期间 playwright-cli 与 superpowers 技能必须可用。`~/.claude/skills` 或 `~/.claude/plugins` 缺失时跳过对应 symlink，agent 仍正常启动。
- 未配置 Provider 透传：agent 角色未配置 Provider 时，子进程直接以当前 `~/.claude/settings.json` 启动——不设 `CLAUDE_CONFIG_DIR`、不注入 Provider 环境变量，仅保留 `--model agents.subagent_model` 覆盖。
- 凭据不落盘：Provider 的 apikey 等敏感凭据经进程环境变量注入子进程，不写入隔离目录的 settings.json；隔离 settings.json 仅含模型映射类环境变量（`ANTHROPIC_DEFAULT_*`、`CLAUDE_CODE_SUBAGENT_MODEL`、`CLAUDE_CODE_MAX_CONTEXT_TOKENS`），不含 Provider 的 baseurl 与 apikey 明文。

## 溯源

- 2026-09-02 add-agent-llm-isolation — 固化 Provider 隔离与幂等目录、插件/技能 symlink 保留、未配置透传现状、凭据仅存进程环境四条契约
