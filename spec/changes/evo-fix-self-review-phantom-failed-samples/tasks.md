## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: core/dashboard/data/runs.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_self_review_terminal_crosscheck.py
  kind: new
```

## 1. 信号护栏补齐

- [ ] 1.1 core/self_review.py：_classify_run 的信号证据扫描（self_review.py:301-303 的 _signal_evidence(lines[:-1])）改为排除与 result 终态文本同源的前驱行（尾三行 [assistant, run_metrics, result] 结构中的 assistant 副本行），使仅存在于 result 正文及其副本中的失败词不再回流为 failed 证据
- [ ] 1.2 core/self_review.py：保持 marker 声明窗口（self_review.py:107、212-225）与真实失败检出路径语义不变

## 2. 双源交叉守卫

- [ ] 2.1 core/dashboard/data/runs.py：为 run_metrics 索引（_load_run_metric_index，runs.py:46）补公共访问器供聚合侧复用，含 .fenixd.log.1 轮转回退与 _strip_run_attempt_suffix（runs.py:28）后缀对齐
- [ ] 2.2 core/self_review.py：collect_failed_run_samples（self_review.py:391）对分类 failed（detail 前缀 marker=/signal=）的样本查 terminal；terminal=success 则不计入失败样本，改写 signal_type=self_review_phantom_failure、severity=warning 的告警且不自动 mark_handled（AdminStore 经 SelfReviewScheduler 注入，构造接线在 core/admin_monitor.py:951-953）
- [ ] 2.3 core/self_review.py：collect_runs_stats（self_review.py:338）失败计数同样交叉校验；metric 索引查不到该 run 终态时维持现状计入，不因缺数据改判

## 3. 测试

- [ ] 3.1 tests/test_self_review_terminal_crosscheck.py：以本条目两个幻影 run 的真实形态造夹具（尾三行 [assistant, run_metrics, result]、result 正文含「预算耗尽」/「SPEC 内容缺失」、声明区干净）断言分类为 succeeded 且不入失败样本
- [ ] 3.2 tests/test_self_review_terminal_crosscheck.py：覆盖交叉守卫——分类 failed 但 terminal=success 时不计失败且产出告警、索引无记录时仍计失败、collect_runs_stats 失败计数与样本列表一致