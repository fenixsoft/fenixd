# ADR-002：模型路由——env 承载真实路由，`--model` 用官方名过 SDK 校验

date: 2026-09-02
status: accepted

## Context

claude-code SDK 的子代理派生路径对非官方模型名报 `unrecognized_model` 致命错误；daemon 环境中的模型名（如第三方 provider 的模型）通常不是官方名。直接把分配的真实模型名传给 `--model` 会让子代理路径启动失败；只设 `--model` 又无法表达 provider 的 baseurl/apikey。多 provider、按 agent 角色分配模型的配置能力需要一个对所有 agent 车道一致成立的路由机制。

## Decision

- 配置了模型分配的 agent 角色在 spawn 时注入进程环境：`ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` 承载 provider 的真实路由信息。
- `--model` 参数恒取官方名：provider 配置了 `sdk_model` 则用之，否则回退 `agents.subagent_model`；它只用于通过 SDK 模型名校验，不承载真实路由。
- 未配置分配的角色零注入，维持默认环境与 `--model agents.subagent_model`，行为与无 provider 配置完全一致。
- 真实模型选择最终由 provider 网关依据 env/请求决定；`sdk_model` 同时是网关可见的模型名字段，配置时须意识到它可能成为实际生效模型。

## Consequences

- 同一路由模式覆盖全部 agent 角色，provider 切换只改配置不改代码。
- 代价是模型语义分层：配置里的 `model`（真实路由）与 `sdk_model`（校验壳/请求体模型名）可能不同，排障时须区分「校验名」与「路由名」。
- 该模式依赖进程环境注入生效，而 claude CLI 会以自身配置文件的 env 块覆盖进程环境——因此本裁定必须与 CLAUDE_CONFIG_DIR 车道隔离（ADR-003）配合才绝对生效。
