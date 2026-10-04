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

- [x] 1.1 core/agent_runner/result_gate.py：AgentRunResult 增加可选结构化字段 api_error_status 与 conn_error（缺省 None，既有构造点不传即兼容）
- [x] 1.2 core/agent_runner/runner.py：run_spec_review 失败路径的 catch-all（现约 :1447-1457）从异常对象回填 exc.api_error_status / exc.conn_error 进 AgentRunResult（挂载先例见 :6039-6063），不再只落 error=str(e)
- [x] 1.3 core/pm_engine/spec_review.py：_classify_run_failure（现约 :1144-1202）优先消费结构化 api_error_status（429 → infra）与 conn_error（→ infra），无结构化字段时回退现有文本指纹分类；命中 infra 后沿用既有 infra 分支行为（不递增 _review_attempts、infra_breaker 记失败、熔断冷却短路 dispatch_review :230-245）。传递约定：结构化字段现止步于 AgentRunResult——_handle_review_failure（:1204，签名仅收 reason 文本）与调用点（:453 仅传 f"评审 run 执行失败: {run_err}"）须扩展为把 AgentRunResult（或其 api_error_status/conn_error 字段）透传至 _classify_run_failure（加可选参数，缺省 None 时走文本回退，既有调用形态与测试兼容）

## 2. 评审车道在飞上限（P0）

- [x] 2.1 core/pm_engine/dispatch/queue.py：新增评审车道在飞上限 _REVIEW_INFLIGHT_CAP（可配，缺省 2-3），插入 _review_entry_ready（现约 :389）可派发判定——命中上限时评审条目保留队列不 pop（范式仿 _PARALLEL_PLAN_INFLIGHT_CAP :151/:157-159 与 :558 在飞跳过先例），不丢弃任务

## 3. content 重试短退避（P1）

- [x] 3.1 core/pm_engine/spec_review.py：content（评审质量）失败分支在 _enqueue 重派（现约 :1307）前加一档秒级短延迟退避（按 core/pm_engine/dispatch/backoff.py _schedule_recovery_timer 范式带判重集合防重复定时器）；infra 分支节奏不动（仍由熔断冷却负责）

## 4. 冻结前缀区分（P1）

- [x] 4.1 core/state_machine.py + core/pm_engine/spec_review.py：评审自动冻结按根因换用新增的评审专用前缀常量（与「用户指令冻结」可区分）；改动点 = state_machine.py 新增常量（FREEZE_ERROR_PREFIX :64 旁）+ spec_review.py 三处冻结调用点按根因取用（:305 尝试上限派发闸门、:726 spec-review-rejected、:1317 尝试上限失败收口）。红线：① 保留「原状态 reviewing」子串供 parse_orig_status（state_machine.py:148）解冻还原并保留 spec-review-incomplete 标记子串；② 新前缀不得命中 core/admin_monitor.py _INTENTIONAL_PAUSE_MARKERS 短语（:949）也不得以 "frozen:" 开头（:972-974 豁免判定两条文本形态）；③ 仍经 freeze_for_human（:1586）成对落冻结与告警。MUST NOT 修改 FREEZE_ERROR_PREFIX 常量值——freeze_spec 人工冻结路径（:1553）依赖其「用户指令冻结」前缀的有意豁免语义。机制定位：infra 分类不冻结（供给瞬态自动恢复由熔断冷却承载，见 1.3）；冻结置 frozen=True 后有意等待豁免命中属转人工预期语义，本任务目标是文案归因准确而非逃过豁免

## 5. 测试

- [x] 5.1 tests/test_spec_review_infra_attribution.py：构造 api_error_status=429 的失败结果，断言结构化字段随 AgentRunResult 传递、_classify_run_failure 判 infra、_review_attempts 不递增、infra_breaker 记失败；再构造 conn_error=True 的失败结果，断言同样判 infra；再构造无结构化字段但文本命中 "rate limit" 的用例，断言文本回退分类仍生效
- [x] 5.2 tests/test_spec_review_infra_attribution.py：构造超过在飞上限的评审候选队列，断言超限条目保留队列且不并发超限、后续轮次正常补位派发
- [x] 5.3 tests/test_spec_review_infra_attribution.py：断言 content 失败两次重派间隔不小于短退避且无重复定时器；断言评审冻结新前缀文案含「原状态 reviewing」可被 parse_orig_status 解析、不命中 _INTENTIONAL_PAUSE_MARKERS 且不以 "frozen:" 开头、FREEZE_ERROR_PREFIX 常量值未被改动（freeze_spec 人工冻结文案契约不变）；断言 infra 分类失败不进入冻结路径（不递增 _review_attempts、不落 frozen）