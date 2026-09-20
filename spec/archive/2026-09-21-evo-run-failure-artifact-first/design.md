# design — run-failure-artifact-first

## 现状

- core/pm_engine/spec_review.py:128-138 run_spec_review 步骤 3：run_ok = getattr(result, "success", False)；not run_ok → _handle_review_failure（:421-466，_review_attempts 递增至 MAX_REVIEW_ATTEMPTS=3 后 freeze_for_human）。
- 步骤 4 consume_review_result（:138-139）仅在 run_ok 后执行；失败路径从不读取已落盘产物。
- 事故序列（2026-09-14）：14:56:22 结果文件落盘 approved → 14:56:39 ERROR「评审 run 执行失败…Exit code: 1」（fenixd.log 8889 行）→ 尝试上限 3 → 冻结；$8.54 作废。

## D1 产物优先判定（spec-review 车道）

run_spec_review 步骤 3 not run_ok 分支前置调用 _artifact_landed_valid(spec_name)：
- 读 .fenix/spec-review/<spec>/.fenix-run-result.json；
- JSON 可解析且 status ∈ {approved, repaired}；
- mtime ≥ 锚点（reviewer_run）写入时刻，且与派发前快照（snapshot.json）spec 一致性通过（复用 _check_write_boundary 的 spec 戳校验思路）；
- 满足 → 记 warning（含 exit code 失败原因，供复盘）+ consume_review_result，return True；
- 不满足 → 走既有 _handle_review_failure。

## D2 infra 错误识别与标记

- 新增 _classify_run_failure(reason) → "infra" | "content"：文本匹配 402/403/429/quota/budget/余额/insufficient balance/rate limit → infra（大小写不敏感；reason 为 None/空时视为 content）。
- infra 标记写入 _handle_review_failure 的 error 上下文与告警 evidence，**error 保留 spec-review-incomplete: 前缀不变**（spec_review.py:485 re_review 的 startswith 契约依赖该前缀，改前缀将破坏「blocked 因评审进入」判定）；分类以 error 内后缀 `[infra: <匹配指纹>]` 透出，供日志与 freeze 告警 evidence（reason 含指纹文本）复盘；仍先按既有重试上限兜底（infra 不递增 _review_attempts 的语义由 run-failure-classification-circuitbreaker 承接，本 SPEC 阶段保持既有递增行为）。

## D3 幂等与防重入

- 消费侧天然幂等（consume_review_result 后 STATE 推进、reviewer_run 清空）；产物优先分支不得在 consume 后再次触发重派。
- 结果文件 status=failed（评审器自判内容失败）→ 不算合法产物，走内容重试。
- 快照/spec 戳校验失败 → 视为产物不可信，走既有重试（保守方向：宁可重试不可错消费）。