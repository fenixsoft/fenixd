# 范围收窄（2026-10-30 人工全量核查）

- 三重不设防复核成立：knowledge.py:1491-1501 SpawnRequest 不传 model＋claude_adapter.py:377-378 无 model 不拼 --model＋agent_env_keys.py:15-19 清洁 env 仅剔 3 键（ANTHROPIC_DEFAULT_* 全继承；宿主 settings.json 至今 glm-5.3-flash[1M]）；knowledge.py:1521-1527 非零退出仅 warning 无 unrecognized_model 分类（provider_circuit 分类仅 agent 车道有）；knowledge.py:666 台账自述「给人看的队列」无龄期消费者。
- **范围收窄（重要）**：10-29 fenixd.log:7935 实证裸名也会被网关拒识（unrecognized_model 裸名变体）——兜底重试/终态分类须覆盖裸名形态；显式传 model 只堵 [1M] 别名形态。
- 边界：在飞 evo-knowledge-distill-resume-guard 无模型名兜底面（已 grep 确认），不冲突；10-09 narrative 修复（钉 glm-5.3-flash+300s）是同族先例可引用。
