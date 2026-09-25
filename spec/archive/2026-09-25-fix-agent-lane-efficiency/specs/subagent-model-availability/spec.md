# subagent-model-availability — 子代理模型可用性（新增）

## ADDED Requirements

### Requirement: provider 隔离配置注入子代理模型映射

直连 Provider 车道（`_get_agent_model_assignment` 返回分配）下，框架 SHALL 在 provider 隔离配置目录（`.fenix/agent-config/<provider>/settings.json`）写入一段**按该 provider 重算**的模型映射 `env`，至少包含：

- `CLAUDE_CODE_SUBAGENT_MODEL`：子代理模型名，取值优先级为配置键 `agents.subagent_model_override`（非空时）→ 该 provider 的 `model`；
- 子代理派生的各 tier 兜底（`ANTHROPIC_DEFAULT_OPUS_MODEL` / `ANTHROPIC_DEFAULT_SONNET_MODEL` / `ANTHROPIC_DEFAULT_HAIKU_MODEL`）：MUST NOT 沿用宿主进程环境中的 cc-switch 官方模型名，MUST 映射到该 provider 自身可用模型。

映射值 MUST 来自 provider 配置而非宿主环境复制（防「陈旧 hy3」毒化）。未分配 provider 的默认网关车道 behavior MUST 不变。

#### Scenario: 直连 provider 时子代理模型被映射到 provider 模型

- **WHEN** 某 agent 被分配 provider `P`（`model` 为 `deepseek-v4-flash`），且配置键 `agents.subagent_model_override` 为空
- **THEN** `.fenix/agent-config/P/settings.json` 的 `env.CLAUDE_CODE_SUBAGENT_MODEL` 为 `deepseek-v4-flash`，且 `env` 内不含宿主环境的 `claude-opus-4-8[1M]` 一类名字

#### Scenario: 配置键覆盖生效

- **WHEN** `agents.subagent_model_override` 为 `glm-5.3-flash`
- **THEN** 上述 `CLAUDE_CODE_SUBAGENT_MODEL` 取值为 `glm-5.3-flash`（覆盖 provider `model` 缺省）

#### Scenario: 未分配 provider 车道行为不变

- **WHEN** agent 未配置任何 provider（走默认网关）
- **THEN** 不写入上述 provider 隔离映射，行为与变更前逐字节一致

### Requirement: 既有隔离目录的幂等重建

provider 隔离目录的写入 MUST 在 `settings.json` **已存在**（且内容不含新映射）时仍然生效——`_ensure_agent_config_dir` 现行「marker 存在即 return」的幂等语义会在已部署机器上使新映射永不落盘（仓库内 5 个 provider 目录实测均已存在无 `env` 的 settings.json）。框架 SHALL 版本标记 + 内容不匹配时原子重写（沿用既有 `tempfile` + `os.replace` 手法），或落显式提示要求清理；MUST NOT 静默保持旧内容。

#### Scenario: 已存在的旧 settings.json 被更新

- **WHEN** `.fenix/agent-config/P/settings.json` 已存在且不含 `env` 映射，随后某 agent 被分配 provider `P`
- **THEN** 该文件被原子重写为含 provider 模型映射的版本（或落显式提示），且 `.fenix/agent-config/P/` 下的 `skills` / `plugins` symlink 不被破坏

### Requirement: 子代理启动失败可见化

子代理（`Explore` / `general-purpose` / `Plan` 等）派发后以 `model_not_found`、认证失败或其它启动期错误终止时，框架 SHALL 在 run 转录与 daemon 日志落显式 WARNING（含子代理类型、错误类别与原文摘要），MUST NOT 静默吞掉。该可见化 MUST NOT 改变 run 的终态判定。

#### Scenario: 子代理 404 落显式告警

- **WHEN** 某 `Explore` 子代理以 `model_not_found (HTTP 404)` 失败
- **THEN** 该 run 的转录/日志出现含子代理类型与错误类别的 WARNING，且该 run 的终态判定与未发生该失败时一致

#### Scenario: 成功派发不产生告警

- **WHEN** 子代理正常完成
- **THEN** 不产生上述 WARNING
