# 设计：审查子代理 429 节流与退避

## 现状结构

- 在飞上限注入链：agents/code-review.md:39 模板条款（{repo_concurrency} 占位）→ core/agent_runner/prompt_builder.py:2366/2395-2411 注入（fail-open 回退 4）→ core/config.py:4791-4793 get_repo_code_review_concurrency（缺省 4，_positive_int_reader）→ core/agent_runner/maintenance_runs.py:3027 传值。
- 既有 429 防线全在 run 终态/provider 级：core/provider_circuit.py:73-91（429/[1302]/rate_limit 三签名分类）、:92-109（重置时间解析）、:110-112（RATELIMIT_REDISPATCH_MAX=1）、core/admin_monitor.py:2810-2812（终态 ratelimit_redispatch 意图消费）、maintenance_runs.py:3478（error 收场抢救）。
- 关键约束：审查子代理由 run 主体（claude CLI Task 工具）派发，框架代码不在派发路径上——行为面唯一可控通道是 prompt 契约，观测面唯一可控通道是终态 result 标记。

## 设计决策

1. 行为面走契约：429 记忆、指数退避、止损规则写入 agents/code-review.md 由 run 主体执行；框架不做进程内节流器——派发不经框架代码，进程内节流无处安放。
2. 观测面走终态标记：review_429_storm=true 由 run 主体写入终态 result；框架沿用「终态意图消费」既有先例（admin_monitor.py:2810-2812 的 ratelimit_redispatch 模式）在 admin_monitor 增加标记消费并产生 admin 告警，同 run 去重。
3. 缺省并发降 2：改 core/config.py:4791-4793 缺省常量与 prompt_builder.py:2395-2411 的 fail-open 回退值（4→2），配置键与读取器语义不动。
4. 跨项目维度只提示不排程：告警 evidence 固定提示「同账户多项目审查窗口重叠，建议错峰排程」；排程协调留待该告警实际复发后再立项。

## 风险

- 降并发拉长审查墙钟（死亡补审串行时更明显）——接受：墙钟成本远低于 3 死接管补审与 19-20 美元 run 成本。
- 契约条款依赖 run 主体遵从、无硬闸——接受：与 code-review.md 现有条款同级；风暴告警提供观测兜底。