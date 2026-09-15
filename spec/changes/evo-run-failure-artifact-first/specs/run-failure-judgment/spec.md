# run-failure-judgment — 评审失败判定先查已落盘产物

## 场景：run 失败但产物已落盘（判别失败）

- 前置：spec-review run 以非零 exit code 收工，但 .fenix/spec-review/<spec>/.fenix-run-result.json 已合法落盘。
- 行为：按产物消费（approved → ready；repaired → repair 通道），退出码仅降级 warning 日志 + 告警留痕；_review_attempts 不递增；不得重派评审。
- 判定「合法」的充分条件：文件存在、JSON 可解析、status ∈ {approved, repaired}、mtime 不早于本次 run 锚点（reviewer_run）写入时刻、与派发前快照（snapshot.json）spec 一致性校验通过。
- 结果：spec 状态推进，消费幂等（consume 后 reviewer_run 清空，不触发重派）。

## 场景：run 失败且产物缺失/非法（内容失败）

- 行为：维持既有语义——_handle_review_failure 递增 _review_attempts 至上限（3，spec_review.py:26）后 freeze_for_human。

## 场景：infra 类失败识别与标记（402/403/预算耗尽）

- 失败原因文本匹配 infra 指纹（402/403/429/quota/budget/余额/insufficient balance/rate limit）时，将本次 run 失败分类标记为 infra 并随 error/告警 evidence 透出，提示上层走 infra 处置，不计入内容质量重试计数。
- 本场景只完成识别与标记；熔断/冷却由 run-failure-classification-circuitbreaker 承接。

## 非目标

- 不改 verifier 结果读取单源（evo-verifier-result-single-source）。
- 不做完整三级失败分类与熔断（run-failure-classification-circuitbreaker）。
- 不改变评审内容质量门（approved 仍须 findings 无阻断、repairs 一致性等既有硬门，consume_review_result 内校验不变）。