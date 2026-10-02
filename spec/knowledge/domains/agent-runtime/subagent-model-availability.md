<!-- knowledge: capability=subagent-model-availability rev=1 sources=spec/archive/2026-09-25-fix-agent-lane-efficiency -->

# 子代理模型可用性

Provider 隔离配置中的子代理模型映射与启动失败可见化：子代理派生模型必须落在所属 provider 的可用模型域内。

## 现行规则

- 模型映射注入：直连 Provider 车道（`_get_agent_model_assignment` 返回分配）下，框架在 provider 隔离配置目录（`.fenix/agent-config/<provider>/settings.json`）写入按该 provider 重算的模型映射 `env`，至少含：
  - `CLAUDE_CODE_SUBAGENT_MODEL`：取值优先级为配置键 `agents.subagent_model_override`（非空时）→ 该 provider 的 `model`；
  - 子代理派生的各 tier 兜底（`ANTHROPIC_DEFAULT_OPUS_MODEL` / `ANTHROPIC_DEFAULT_SONNET_MODEL` / `ANTHROPIC_DEFAULT_HAIKU_MODEL`）：映射到该 provider 自身可用模型，不得沿用宿主进程环境中的 cc-switch 官方模型名。
- 映射值来源：全部来自 provider 配置，不从宿主环境复制（防陈旧宿主模型名毒化）。未分配 provider 的默认网关车道行为不变（不写入该映射）。
- 隔离目录幂等重建：`settings.json` 已存在且内容不含新映射时，写入仍须生效——版本标记 + 内容不匹配时原子重写（`tempfile` + `os.replace` 手法）或落显式提示，不静默保持旧内容；重写不破坏 `.fenix/agent-config/<provider>/` 下的 `skills` / `plugins` symlink。
- 启动失败可见化：子代理（`Explore` / `general-purpose` / `Plan` 等）派发后以 `model_not_found`、认证失败或其它启动期错误终止时，run 转录与 daemon 日志落显式 WARNING（含子代理类型、错误类别与原文摘要），不静默吞掉；该可见化不改变 run 的终态判定。子代理正常完成不产生此类告警。

## 溯源

- 2026-09-25 fix-agent-lane-efficiency（spec/archive/2026-09-25-fix-agent-lane-efficiency） — 固化 provider 模型映射注入（subagent_model_override 优先级、tier 兜底重算）、既有隔离目录幂等重建与子代理启动失败可见化
