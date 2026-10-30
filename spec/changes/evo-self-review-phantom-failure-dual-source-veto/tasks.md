## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: tests/test_self_review_terminal_crosscheck.py
  kind: modify
```

## 0. 串行前置（MERGE-NOTES 约束落点）

- [x] 0.1 本 SPEC 须待在飞 evo-fix-self-review-phantom-running（tasks 10/10 全勾、已实现待归档，明文冻结 result/error 分支语义）归档后方可开工；开工前对本文件与 design.md 所引行号按归档后代码复核一遍（复核：其实现分支已并入本分支（merge 64596a885），归档为 daemon 侧机械动作；所引行号按合并后代码复核——self_review.py 谓词段现位 :589/:614/:627、计数侧 :729-734、样本侧 :772-779/:808-813、_classify_run :475-544，maintenance_runs :1460/:1500-1656/:1621-1622/:1671 与 tests :248/:301/:311-321 逐字吻合）

## 1. 双源否决扩界

- [x] 1.1 core/self_review.py：_is_phantom_signal_failure（:595-605）扩展 error 终态形态——detail 以「Exit code」前缀起（evo-1792692791 实拍形态；MUST NOT 空泛匹配任意 error 文本）时经 _run_terminal_success（:570）查 daemon 终态，terminal=success 改计 success 并写 self_review_phantom_failure 告警，查无账面行保守保持 failed
- [x] 1.2 core/self_review.py：marker= 命中样本纳入同一双源否决，修订 :596-604 docstring 排除约定为「daemon 终态权威裁决」，计数侧守卫（:715-716）与样本侧守卫（:794-796）消费点同步放开；计数侧注释（:710-714）、样本侧 docstring（:753-760）与守卫注释（:788-793）的「marker= MUST NOT 纳入守卫」锁定表述同步改写；_record_phantom_failure_alert（:608）描述与 recommended_action 的「经信号路径」措辞随扩界泛化

## 2. 指标透传

- [x] 2.1 core/agent_runner/maintenance_runs.py：run_evolution 抢救/落地段（:1500-1656）翻转 run_ok=True 后、收尾 _log_lane_run_metrics 调用（:1671）前，分源回填真实指标——total_cost_usd ← 档案 result 事件顶层字段；turns ← daemon 日志 context metrics 行定向解析（MUST NOT 经 load_run_metric 合并索引取 turns：后写 lane 行 turns=0 会覆盖先写 context 行 turns=197，runs.py:107 后行刷新合并语义）；任一源查无/解析失败保持记 0 并 DEBUG 留痕，不阻塞落地主链

## 3. 测试

- [x] 3.1 tests/test_self_review_terminal_crosscheck.py：新增夹具「run 尾 error 终态 Exit code: 1 + daemon terminal=success」（evo-1792692791 形态）断言改计 success 且写 self_review_phantom_failure 告警
- [x] 3.2 tests/test_self_review_terminal_crosscheck.py：新增夹具「error 终态 + 查无账面行保持 failed」「daemon terminal=error 反例保持 failed」；既有 signal= 排除/告警用例与 daemon=error 反例（:311-321）不回归；既有 marker= pin 用例（:248 test_marker_failed_terminal_success_still_counted、:301 test_stats_failed_count_consistent_with_samples）按新语义同轮翻转断言（marker + terminal=success → 改计 success 并写 self_review_phantom_failure 告警）
