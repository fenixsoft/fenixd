## Deliverables

```yaml
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/spec_review.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: tests/test_spec_review_infra_attribution.py
  kind: new
```

## 1. 归因桥接（P0）

- [ ] 1.1 core/agent_runner/result_gate.py：AgentRunResult 增加可选结构化字段 api_error_status 与 conn_error（缺省 None，既有构造点不传即兼容）
- [ ] 1.2 core/agent_runner/runner.py：run_spec_review 失败路径的 catch-all（现约 :1447-1457）从异常对象回填 exc.api_error_status / exc.conn_error 进 AgentRunResult（挂载先例见 :6039-6063），不再只落 error=str(e)
- [ ] 1.3 core/pm_engine/spec_review.py：_classify_run_failure（现约 :1144-1202）优先消费结构化 api_error_status（429 → infra）与 conn_error（→ infra），无结构化字段时回退现有文本指纹分类；命中 infra 后沿用既有 infra 分支行为（不递增 _review_attempts、infra_breaker 记失败、熔断冷却短路 dispatch_review :230-245）

## 2. 评审车道在飞上限（P0）

- [ ] 2.1 core/pm_engine/dispatch/queue.py：新增评审车道在飞上限 _REVIEW_INFLIGHT_CAP（可配，缺省 2-3），插入 _review_entry_ready（现约 :389）可派发判定——命中上限时评审条目保留队列不 pop（范式仿 _PARALLEL_PLAN_INFLIGHT_CAP :151/:157-159 与 :558 在飞跳过先例），不丢弃任务

## 3. content 重试短退避（P1）

- [ ] 3.1 core/pm_engine/spec_review.py：content（评审质量）失败分支在 _enqueue 重派（现约 :1307）前加一档秒级短延迟退避（按 core/pm_engine/dispatch/backoff.py _schedule_recovery_timer 范式带判重集合防重复定时器）；infra 分支节奏不动（仍由熔断冷却负责）

## 4. 冻结前缀区分（P1）

- [ ] 4.1 core/state_machine.py：评审冻结按根因区分前缀——供给瞬态类（分类为 infra 时冻结）使用独立前缀，与评审质量不达标前缀可区分；三条红线：保留「原状态 reviewing」子串供 parse_orig_status（:151/:1613-1616）解冻还原、新前缀文案不得命中 core/admin_monitor.py _INTENTIONAL_PAUSE_MARKERS 短语、仍经 freeze_for_human（:1586）成对落冻结与告警

## 5. 测试

- [ ] 5.1 tests/test_spec_review_infra_attribution.py：构造 api_error_status=429 的失败结果，断言结构化字段随 AgentRunResult 传递、_classify_run_failure 判 infra、_review_attempts 不递增、infra_breaker 记失败；再构造无结构化字段但文本命中 "rate limit" 的用例，断言文本回退分类仍生效
- [ ] 5.2 tests/test_spec_review_infra_attribution.py：构造超过在飞上限的评审候选队列，断言超限条目保留队列且不并发超限、后续轮次正常补位派发
- [ ] 5.3 tests/test_spec_review_infra_attribution.py：断言 content 失败两次重派间隔不小于短退避且无重复定时器；断言供给瞬态冻结文案含「原状态 reviewing」可被 parse_orig_status 解析、不命中 _INTENTIONAL_PAUSE_MARKERS