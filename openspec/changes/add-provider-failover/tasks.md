# Tasks: add-provider-failover

## 1. 配置链解析（design D1/链解析）

- [ ] 1.1 config loader 支持 agents.models.*.provider 的 str|list 解析为链（单值→单元素链），启动/热更新校验未知名字打 ERROR 不阻塞；补单测（列表/单值兼容/未知名三例）
- [ ] 1.2 _get_agent_model_assignment 重构为返回候选链列表（含每项 provider+model 三件套），消费点（prompt 构建、env 注入、熔断查询）同步适配；既有单值配置的集成测试不变绿不收工

## 2. 错误分类与冷却（design D2/D3）

- [ ] 2.1 新增 classify_switch_error()：unrecognized_model 文本 / HTTP 5xx / 连接异常三类返回 switch 标记；今日真实报错文本入库 fixture；补分类矩阵单测（含 4xx 不误分类）
- [ ] 2.2 provider_circuits 增加 switch_cooldown_until 独立字段与默认 300s 冷却（config: pm.failover.switch_cooldown_seconds）；链选择跳过冷却中候选，全链冷却返回 chain_exhausted 失败且不启动进程、不消耗 spec 重试；补单测（单家冷却跳转 / 全链耗尽 / 冷却到期主链复位）

## 3. attempt 级接入与续跑（design D1/D4）

- [ ] 3.1 _execute_agent attempt 循环接入链选择：启动前选首个未冷却候选；切换类失败后推进指针（实例级 cursor 按 agent_type 记忆）；下一 attempt 携带 --resume 原会话继续；补模拟单测（首候选 dying→次候选接管且 session_id 保持）
- [ ] 3.2 CLAUDE_CONFIG_DIR 隔离目录随候选同步切换（复用 _ensure_agent_config_dir）；跨 provider resume 行为记录 switch 事件日志；补单测

## 4. 观测（design D5）

- [ ] 4.1 AgentRunResult 增 provider_used/model_used 字段；run jsonl attempt 启动时写入 provider_marker 行；"provider switched a→b" INFO 打点；补单测
- [ ] 4.2 per-provider 当日 attempt 计数与 daily_attempts_warn（默认 50）WARNING 单次告警；补单测

## 5. 回归与核验

- [ ] 5.1 全量 pytest 通过（重点 tests/test_agent_runner.py、config 相关及新增用例），无既有用例回归
- [ ] 5.2 对照两个 capability spec 的全部 Scenario 逐条核对实现覆盖并记录结论
