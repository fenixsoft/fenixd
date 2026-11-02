# 提案：distill-model-name-fallback

## 问题

知识蒸馏车道被模型名拒识击杀且无自动兜底：2026-10-27-evo-add-review-failure-attribution 的蒸馏 run 于 2026-10-27T08:09:06Z 死于 [claude-code:unrecognized_model] glm-5.3-flash[1M]（fenixd.log:3296），该归档知识入库缺位 ≥9 小时至窗末未重试。家族规模（复核更正为全量口径）：保留日志 unrecognized_model 共 42 行，含 6 个归档蒸馏被杀、5 个 Administrator run 失败（fenixd.log:6 等）。

注入点已定位（复核增量，替代原条目两假说）：宿主 /root/.claude/settings.json env 将 ANTHROPIC_DEFAULT_SONNET_MODEL/OPUS_MODEL 设为带 [1M] 后缀的模型名，daemon 进程 env 实测继承；蒸馏 spawn 不传模型名且 ENV_MODE_CLEAN 全量继承宿主 env（core/agent_runner/harness/claude_adapter.py:267-283；:371-372 仅 req.model 非空才拼 --model），CLI 别名解析到毒化值。主车道同模型裸名一直可用。

车道现状：_spawn_and_wait（core/knowledge.py:1436-1494）对非零退出仅告警返回，无拒识识别与重试；「重试台账」是人看队列（_register_todo_retry，:662-683），give_up 后 pending 条目即移除（:1496-1508），无龄期消费者——本例欠账连 evo-knowledge-distill-resume-guard（在途，仅 daemon 启动触发恢复）落地也覆盖不到。

## 目标

1. 蒸馏 spawn 恒显式传配置的裸模型名（隔离宿主 env 毒化别名）。
2. 非零退出且 stderr 命中 unrecognized_model 时，以裸模型名单次重试；仍失败走既有 give_up/台账路径。
3. 重试台账龄期信号：todo.md 重试行登记超 24 小时未重试时每日至多一条提醒（幂等）。

## 非目标

- 不改宿主 /root/.claude/settings.json（运维面，SPEC 只记录结论；宿主修复后显式传名仍保留作纵深）。
- 不动 agent_runner 车道的 provider_circuit/failover 语义（仅复用其判别 pattern）。
- 不改 evo-knowledge-distill-resume-guard（在途）的启动恢复逻辑。