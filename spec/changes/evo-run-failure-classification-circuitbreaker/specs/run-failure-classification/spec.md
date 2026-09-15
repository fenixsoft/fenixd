# run-failure-classification — run 执行失败三级分类与熔断

## 场景：infra 失败（403/402/预算耗尽/CLI 进程级）

- 识别：失败原因匹配 infra 指纹（403/402/429/quota/budget/余额/insufficient balance/rate limit）或 CLI 进程级崩溃（Exit code 非内容语义），或 probe 标记（model_chain_preflight_failed）。
- 行为：同一链路（spec-review / verify / impl）连续 infra 失败 ≥3 次 → 熔断该链路：停止派发、落 kind=escalation、signal_type=run_infra_failure、severity=critical 告警（evidence 含链路、指纹、次数、时间窗）；进入冷却窗口（默认 30 分钟）；窗口结束自动恢复重试。
- 冷却期间 _review_attempts 不递增（不计入内容重试）。

## 场景：内容失败（含空白轮次）

- 行为：维持既有语义（_review_attempts 机械重试至上限 3 → freeze_for_human，spec_review.py:26）。

## 场景：判别失败（产物已落盘）

- 行为：按产物消费（run-failure-artifact-first 承接），不重试。

## 非目标

- 不改评审内容质量硬门（approved/repairs 一致性等）。
- 不改 verifier 结果读取单源（evo-verifier-result-single-source）。
- 不做派发前探活（model-chain-preflight 承接）。