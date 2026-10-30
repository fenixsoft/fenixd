# 设计：distill-model-name-fallback

## 落点

1. core/knowledge.py:1436-1494（_spawn_and_wait）：SpawnRequest 增加 model 实参（配置键沿用蒸馏车道既有模型配置，裸名）；:1480-1493 非零退出分支加 stderr 判别（pattern 对照 core/agent_runner/provider_circuit.py:78-106 的 unrecognized_model 识别），命中即以裸名单次重试。
2. core/knowledge.py:662-683（_register_todo_retry）/1496-1508（_give_up）：新增台账龄期扫描助手（解析 todo.md 重试行日期节），超 24 小时未重试发每日一条提醒，复用既有告警/信号通道并做同日幂等。
3. core/agent_runner/provider_circuit.py：只读引用其判别 pattern 常量，不改语义。
4. 测试：tests/test_knowledge_distill_resume.py（拒识命中→单次重试成功；重试仍失败只登一次台账；显式 model 透传断言；龄期提醒触发与同日幂等）。

## 风险与权衡

- 重试上界一轮 run（RUN_TIMEOUT_SECONDS 有界），不会放大失败风暴。
- 显式传名后若配置值为空需回退现行为（不传）并告警，避免静默空参。
- 宿主 settings 毒化是环境事实，仓内以显式传名隔离；运维侧修复（去掉 [1M] 后缀）作为部署说明记录，不入 repo 代码。