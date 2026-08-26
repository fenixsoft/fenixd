## Context

当前 `core/agent_runner.py` 的 `_execute_agent` 为每个 agent 角色解析模型分配（`ConfigLoader.get_agent_model_assignment`）：配置了 Provider 时把 `ANTHROPIC_BASE_URL/API_KEY/MODEL` 注入子进程环境变量；未配置时仅传 `--model subagent_model`。随后 `_run_claude` 用 `subprocess.Popen` 启动 `claude -p ...`。

实证发现（2026-08-26）：**claude CLI 的 `~/.claude/settings.json` 中 `env` 块优先级高于进程环境变量**。该文件当前包含 `ANTHROPIC_BASE_URL=http://127.0.0.1:15721`（cc-switch 网关）与 `ANTHROPIC_AUTH_TOKEN=PROXY_MANAGED`，因此 agent 子进程无论 daemon 环境注入什么，最终都打到网关，与用户会话共享同一 LLM 通道——Provider 注入成为死代码，且 agent 故障被网关 500/429 放大。

验证结论（均已实测）：
1. `CLAUDE_CONFIG_DIR=<dir>` 会改变 claude 的配置根目录，**彻底绕过 `~/.claude/settings.json`**（内存路径、env、插件均切到新目录）。
2. 隔离目录内 `settings.json` 带 `enabledPlugins` 且 `skills`/`plugins` 为指向 `~/.claude` 的 symlink 时，**superpowers 插件与全部 43 个技能（含 playwright-cli）完整保留**。
3. 隔离 + 进程环境注入 Provider（Ark baseurl/token/model）+ `--model claude-sonnet-5` 时，请求**真实打到 Provider 并返回 200**。

## Goals / Non-Goals

**Goals:**
- 配置了 Provider 的 agent 角色，其 baseurl/apikey/model 绝对生效，与用户会话完全隔离（不同账号/配额/故障域）。
- 隔离不牺牲 agent 子代理能力：playwright-cli、superpowers 等技能与插件继续可用。
- 未配置 Provider 时，agent 行为与现状一致（透传 `~/.claude/settings.json`，保留 `--model subagent_model`）。

**Non-Goals:**
- 不改变 `llm.providers` / `agents.models` 的配置格式与校验（沿用现有 `ConfigLoader`）。
- 不处理网关（cc-switch）本身的配额/故障；本变更只保证"配了 Provider 就真正用它"。
- 不迁移用户 `~/.claude/settings.json` 的权限块（agent 以 `--permission-mode bypassPermissions` 运行，权限无关）。

## Decisions

### D1：用 `CLAUDE_CONFIG_DIR` 实现完全隔离（而非仅注入 env）

- **选择**：Provider 生效时，为子进程设置 `CLAUDE_CONFIG_DIR=<project>/.fenix/agent-config/<provider>/`。
- **理由**：唯一能让 Provider 的 baseurl/key/model 不被 `~/.claude/settings.json` env 覆盖的方式（实测：仅注入 env 时 settings.json 优先生效，Provider 无效）。
- **备选**：`--settings <file>` 追加配置——实测无法覆盖 `~/.claude/settings.json` env，否决。

### D2：隔离目录内保留插件与技能

- **选择**：按需生成 `agent-config/<provider>/` 目录，包含：
  - `settings.json`：`enabledPlugins` 从 `~/.claude/settings.json` 复制（缺省 `superpowers@claude-plugins-official`）；`hooks` 从现有 `.fenix/agent-settings.json` 复制（PreToolUse block-image-read）。
  - `skills` → symlink `~/.claude/skills`、`plugins` → symlink `~/.claude/plugins`（源不存在则跳过）。
- **理由**：实测 symlink + `enabledPlugins` 后 43 个技能与 superpowers 插件完整保留；symlink 避免复制大目录、随源更新。
- **备选**：整目录复制——陈旧且浪费磁盘，否决。

### D3：Provider 连接凭据经进程环境注入，隔离 settings.json 只放"映射/插件/hooks"

- **选择**：Provider 的 `ANTHROPIC_BASE_URL/API_KEY/MODEL` 继续走现有 `env_overrides` 注入子进程；隔离 `settings.json` 的 `env` 仅复制 `~/.claude/settings.json` 中的 `ANTHROPIC_DEFAULT_*` / `CLAUDE_CODE_SUBAGENT_MODEL` / `CLAUDE_CODE_MAX_CONTEXT_TOKENS` 等映射类变量（**不含** base url/token），保证子代理 SDK 模型映射不丢，同时 apikey 不落盘。
- **理由**：不改动现有 `_execute_agent` 的 env 注入路径（改动最小）；apikey 只在进程内存，不写磁盘。

### D4：未配置 Provider 时零隔离、保持现状

- **选择**：`assignment is None` 时不设 `CLAUDE_CONFIG_DIR`、不注入 env，维持 `--model subagent_model`。
- **理由**：用户明确要求"直接以当前 settings.json 启动"；`--model` 保留用于规避 SDK 子代理 `unrecognized_model` 校验（daemon 环境 `ANTHROPIC_MODEL=deepseek-v4-flash` 非官方模型名）。

### D5：隔离目录按需生成 + 幂等

- **选择**：每次 `_run_claude` 在 Provider 生效时确保目录存在（幂等创建：目录已存在则跳过 symlink/写文件）。
- **理由**：多 agent 并发（`max_concurrent`）共用同一 provider 目录，需线程安全（创建时加锁或容忍重复创建覆盖，内容确定无副作用）。

## Risks / Trade-offs

- [Provider 隔离后失去 `~/.claude` 全部配置（模型映射之外的杂项）] → 隔离 settings.json 显式复制所需键（D3）；agent 运行在 bypassPermissions 下，权限块本就不需要。
- [symlink 指向 `~/.claude/skills`，若该目录被外部改写会影响 agent] → 与用户会话共享只读技能目录，属预期（用户要求保留插件）；文档注明。
- [多并发 agent 首次同时创建隔离目录的竞态] → 创建逻辑幂等 + 目录级锁或原子 mkdir（D5）。
- [`CLAUDE_CODE_MAX_CONTEXT_TOKENS` 等映射类变量漏复制导致子代理行为差异] → D3 显式复制 `env` 映射类键，并在验收中覆盖子代理派发场景。

## Migration Plan

1. 实现 `_run_claude`/`_execute_agent` 的隔离逻辑（D1-D5）。
2. 单元测试：Provider 生效时 `_run_claude` 构造的 cmd/env 含 `CLAUDE_CONFIG_DIR` 与隔离目录；未配置时不包含。
3. 集成验证：在 `.fenix/config.yaml` 配置一个指向 Ark 的 Provider（implementer 角色），确认 agent 运行产物中的请求打到 Ark、返回 200，且技能/插件完整（init 事件含 playwright-cli）。
4. 回滚：删除 Provider 配置即回到现状（隔离逻辑仅在配置 Provider 时启用）。

## Open Questions

- 是否把 `administrator` 角色纳入 `KNOWN_AGENT_TYPES` 并同样获得 Provider 隔离？（现 `config.py` 不含该角色；`run_administrator` 走独立 `_get_admin_model` 路径，暂不纳入，留待后续。）
