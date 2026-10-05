## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: tests/test_codefix_digest_metrics.py
  kind: new
```

## 1. run 工具构成指标

- [x] 1.1 core/agent_runner/runner.py：context metrics 汇总处（:4936 日志行所在函数）增加 tool_use 按工具名计数与无 tool_use 的 assistant 文本行计数，与 turns 并列打进日志与 metrics 落盘；落盘失败不阻断 run 终态（保留 :4971 既有语义）
- [x] 1.2 core/agent_runner/runner.py：统计口径与 core/agent_runner/latency.py（:150-193）的 rounds/stall 一致按转录事件累计，跨 attempt 轮不串数

## 2. 消化链级 rollup

- [x] 2.1 core/code_fix.py：链末批判定（is_chain_last_batch :1109）命中或链中途终局时，汇总本链 run 数/总轮数/总 tool_use 与台账核销计数（resolved/ignored），输出一行结构化 rollup 日志并随链状态落盘；条目计数与台账核销一致，覆盖链中全部 run 不漏样本
- [x] 2.2 core/code_fix.py：链内 run 清单记账——随链状态逐 run 累积 run_id 形成链级持久列表（既有进度文件 run_id 字段批收尾即清除 :111、台账核销 mark_resolved :1624 不带 run_id，均不能充当链内 run 事实源）；rollup（2.1）以该清单逐 run 读取 `.fenix/runs/<run_id>.jsonl` 的 run_metrics 行汇总（读取模式先例 :423）

## 3. 测试

- [x] 3.1 tests/test_codefix_digest_metrics.py：工具构成指标用例——含 tool_use 与纯文本行的转录样本，断言直方图与文本行计数正确、metrics 落盘失败不阻断终态
- [x] 3.2 tests/test_codefix_digest_metrics.py：链 rollup 用例——多 run 链末批完成与中途终局两形态，断言 run 数/轮数/条数汇总与台账核销一致