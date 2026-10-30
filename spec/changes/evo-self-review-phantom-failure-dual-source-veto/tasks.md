## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: tests/test_self_review_terminal_crosscheck.py
  kind: modify
```

## 1. 双源否决扩界

- [ ] 1.1 core/self_review.py：_is_phantom_signal_failure（:580-590）扩展 error 终态形态——detail 为 Exit code/CLI 错误形态时经 _run_terminal_success（:556）查 daemon 终态，terminal=success 改计 success 并写 self_review_phantom_failure 告警，查无账面行保守保持 failed
- [ ] 1.2 core/self_review.py：marker= 命中样本纳入同一双源否决，修订 :586-588 docstring 排除约定为「daemon 终态权威裁决」，计数侧（:695-700）与样本侧（:777-784）消费点同步放开

## 2. 指标透传

- [ ] 2.1 core/agent_runner/maintenance_runs.py：产物直读/salvage 登记（:1500-1517）的 run_metrics 行透传档案侧真实 turns 与 total_cost_usd，读取失败时保持记 0 并 DEBUG 留痕

## 3. 测试

- [ ] 3.1 tests/test_self_review_terminal_crosscheck.py：新增夹具「run 尾 error 终态 Exit code: 1 + daemon terminal=success」（evo-1792692791 形态）断言改计 success 且写 self_review_phantom_failure 告警
- [ ] 3.2 tests/test_self_review_terminal_crosscheck.py：新增夹具「error 终态 + 查无账面行保持 failed」「daemon terminal=error 反例保持 failed」，既有 signal= 排除/告警与 marker= 用例不回归