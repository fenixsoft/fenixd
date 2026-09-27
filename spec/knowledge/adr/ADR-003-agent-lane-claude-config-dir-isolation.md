# ADR-003：Agent 车道 LLM 隔离必须经 CLAUDE_CONFIG_DIR

date: 2026-09-02
status: accepted

## Context

claude CLI 的 `~/.claude/settings.json` 中 `env` 块优先级高于进程环境变量：用户会话的网关配置（baseurl/token）会覆盖 daemon 注入的任何 provider 环境变量，使「按角色分配 provider」沦为死代码，且 agent 与用户会话共享同一 LLM 通道——故障与限流互相放大。实测结论：`--settings <file>` 追加配置无法覆盖 `~/.claude/settings.json` 的 env；`CLAUDE_CONFIG_DIR` 能整体更换 claude 的配置根目录，从而彻底绕开用户 settings。

## Decision

- provider 生效的 agent 角色，spawn 时必须设置 `CLAUDE_CONFIG_DIR=<project>/.fenix/agent-config/<provider>/`，实现与用户会话的完全隔离（不同账号、配额、故障域）。
- 隔离目录按需幂等生成（多并发 agent 共用同一 provider 目录）：`settings.json` 只放映射类变量（`ANTHROPIC_DEFAULT_*` 等）、`enabledPlugins` 与 hooks；`skills` / `plugins` 以 symlink 指回 `~/.claude` 对应目录，保持子代理技能与插件完整可用。
- provider 连接凭据（baseurl/apikey/model）只经进程环境注入，不写入隔离目录的 settings.json，apikey 不落盘。
- 未配置 provider 的角色零隔离：不设 `CLAUDE_CONFIG_DIR`、不注入 env，直接以用户当前 settings 启动。

## Consequences

- 「配了 provider 就真正用它」绝对成立，agent 车道与用户会话故障域解耦；隔离目录与进程 env 两处的职责切分（凭据走 env、映射/插件走 settings）须同时维持，任何一处回退都会让覆盖问题复发。
- 隔离后 agent 不再继承 `~/.claude` 的杂项配置，需要的能力必须显式复制进隔离 settings；symlink 的技能目录与用户会话共享，源变更会传导到 agent。
