# 能力：knowledge-distill-resilience

## R1 显式模型名

蒸馏 run spawn（core/knowledge.py _spawn_and_wait）恒传显式 model（取配置的蒸馏车道裸模型名，经 SpawnRequest.model→claude_adapter --model 透传链路），使子进程不再依赖宿主 ANTHROPIC_DEFAULT_*_MODEL 别名解析。

## R2 拒识兜底重试

非零退出且 stderr 命中 [claude-code:unrecognized_model]（判别 pattern 复用 core/agent_runner/provider_circuit.py 既有识别）时，以裸模型名自动重试一次；重试成功按正常完成入账，仍失败走既有 give_up→清理半成品→登重试台账路径（行为不重复登记）。

## R3 台账龄期提醒

基于 .fenix/todo.md 重试行所在日期节计算登记龄期，超 24 小时未重试时每日至多一条 admin 提醒（幂等防刷屏），直至该行被勾选或移除。