## Why

评审车道（spec-review）run 失败时错误行不带结构化归因（stderr_tail/exit_code/api_error_status），根因须逐个翻归档 run 文件；错误消息内嵌 SPEC 名使 daemon_errors 指纹互不相同，同型失败无法跨日聚合追踪（10-03 靠三指纹合并召唤、10-05 同型零召唤）。另核查发现真机制缺口：infra_breaker.record_success 在 spec-review 链路无任何调用点，「连续 infra 失败」计数只增不清、跨周累计，1 次真实失败即可凭陈旧计数误触熔断（10-05 实测停摆约 48 分钟、评审顺延约 1 小时）。

## What Changes

1. 归因留痕：run_spec_review 失败桥接补 stderr_tail 透出（复用 _stderr_tail_summary），AgentRunResult 增同名字段，评审失败 ERROR 行对齐 code-fix 车道形态追加 [api_error_status=… exit_code=… stderr_tail: …] 括注。
2. 指纹归一化：_normalize_error_message 对 spec_review 组件的「评审 run 执行失败: <spec>: …」模板剥离 SPEC 名段（按组件窄化，不动全局文字骨架）。
3. 熔断计数清零接线：评审 run 成功收工路径调用 record_success，恢复「连续失败」语义。

## Out of Scope

- 不改 runner.py 共享底座错误文本「claude CLI failed: …」（影响全部车道指纹骨架）。
- 不调熔断阈值/冷却参数；不动 code-fix 车道既有留痕形态。