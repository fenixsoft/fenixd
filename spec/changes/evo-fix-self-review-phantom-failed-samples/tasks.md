## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: core/dashboard/data/runs.py
  kind: modify
- path: tests/test_self_review_terminal_crosscheck.py
  kind: new
- path: tests/test_self_review_run_semantics.py
  kind: modify
- path: tests/test_self_review_result_based_classification.py
  kind: modify
```

## 1. 信号护栏补齐

- [ ] 1.1 core/self_review.py：_classify_run 的信号证据扫描（self_review.py:301-303 的 _signal_evidence(lines[:-1])）改为结构性排除终态邻近窗口（尾三行 [assistant, run_metrics, result]）中的 assistant 事件行，使仅存在于 result 正文及其回声行中的失败词不再回流为 failed 证据（注意：assistant 行不逐字等于 result 全文，MUST NOT 按逐字副本内容匹配实现）
- [ ] 1.2 core/self_review.py：保持 marker 声明窗口（self_review.py:107、212-225）与真实失败检出路径语义不变
- [ ] 1.3 更新锁旧信号语义的既有测试（1.1 有意推翻 698a9a0d「兜底通道不收窄」决策，下列断言随之翻转）：tests/test_self_review_run_semantics.py:58 test_signal_fallback_when_no_marker、:121 test_signal_fallback_counts_failed、:134 test_samples_include_run_id_and_evidence（impl-sig-997 夹具）、:172 test_sample_scan_finds_midfile_signal、tests/test_self_review_result_based_classification.py:348 test_signal_guardrail_keeps_event_lines_skips_result_prose 前半——信号词移至终态邻近窗口之外的独立事件行以保留「独立失败证据仍可检出」覆盖，或按新语义改断言；同步两文件 docstring 中「不收窄」表述

## 2. 双源交叉守卫

- [ ] 2.1 core/dashboard/data/runs.py：为 run_metrics 索引（_load_run_metric_index，runs.py:46）补公共访问器供聚合侧复用，含 .fenixd.log.1 轮转回退与 _strip_run_attempt_suffix（runs.py:28）后缀对齐；core/self_review.py 侧延迟导入该访问器（对齐本模块延迟导入风格，避免加载序副作用）
- [ ] 2.2 core/self_review.py：collect_failed_run_samples（self_review.py:391）仅对信号路径命中（detail 前缀 signal=）的 failed 样本查 terminal；terminal=success 则不计入失败样本，改写 signal_type=self_review_phantom_failure、severity=warning 的告警且不自动 mark_handled（store 经 collect 函数可选参数透传 self.store——既有接线 core/admin_monitor.py:959 已传 store=self.store，admin_monitor.py 无需改动；store 未注入时仍排除幻影但跳过告警、降级 logger.warning）。marker= 命中（D1 假成功抓取：正常 result 收尾即记 terminal=success，runner.py:3313）MUST NOT 纳入守卫，照常计入失败
- [ ] 2.3 core/self_review.py：collect_runs_stats（self_review.py:338）仅对 detail 前缀 signal= 的 failed 计数交叉校验（marker= 命中与 error 终态失败照常计入）；metric 索引查不到该 run 终态时维持现状计入，不因缺数据改判

## 3. 测试

- [ ] 3.1 tests/test_self_review_terminal_crosscheck.py：以本条目两个幻影 run 的真实形态造夹具（尾三行 [assistant, run_metrics, result]、result 正文含「预算耗尽」/「SPEC 内容缺失」、声明区干净）断言分类为 succeeded 且不入失败样本
- [ ] 3.2 tests/test_self_review_terminal_crosscheck.py：覆盖交叉守卫——signal= 分类 failed 但 terminal=success 时不计失败且产出告警、marker= 命中即使 terminal=success 仍计失败（假成功抓取语义保持）、索引无记录时仍计失败、collect_runs_stats 失败计数与样本列表一致