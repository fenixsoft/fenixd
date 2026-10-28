# code-fix-lane delta：回归异常熔断

## MODIFIED Requirements

### Requirement: 回归失败的自动重试与丢弃

单批首轮全量回归未通过时，系统 SHALL 进入**定向重试轮**（上限 `admin.code_review_fix.targeted_retry_max`，缺省 3）：每轮在同一 worktree 内派一次 `code-fix` run，prompt MUST 注入上一轮失败用例的结构化明细（nodeid + 失败摘要），并明确指令**只修复与失败用例相关的问题，MUST NOT 扩面重做全批**；修复对象由 agent 依据用例信息判定——可以是产品代码缺陷，也可以是测试本身缺陷（断言过时、替身失真、超时替身自旋类）。耗尽轮数仍失败则**现场即弃**（语义同原「两次回归均失败」，MUST NOT 保留 worktree 待人工），条目入失败档案并按跨链重试预算自动重试（预算语义见 `code-fix-batch-selfheal`）。

**回归异常熔断**：当批内回归异常类失败（回归结局 `parse_error`，或回归 `failed` 但失败明细提取为空/不可映射即 `fallback_full` 生效且明细 items 为空）**连续**达到熔断阈值（模块常量，缺省 2 次，不新增配置键）时，重试循环 SHALL 提前终止——MUST NOT 再派发下一轮定向 run 与全量回归，按现场即弃语义收口，批收口 `reason` 为 `regression_parse_error_breaker`。熔断计数在同批内连续累计，遇回归正常产出失败明细（真实测试失败）或回归 `passed` 即清零——真实测试失败 MUST NOT 进熔断计数，既有 `targeted_retry_max` 轮数上限行为在熔断未触发时逐位不变。

- 失败用例明细 MUST 结构化落盘（nodeid + 失败摘要，如 `.fenix/code-review/fix-reg-failures-<run_id>.json`，首轮与每个定向轮回归非 passed 时各落一份、文件名含该轮 run_id），供重试注入与事后审计；nodeid 映射以 junit `classname` 主导重构（pytest junitxml 不产 `file` 属性属预期，MUST NOT 因此判映射失败），映射失败（不足以唯一重构 nodeid）时 MUST 回退为全量重试（fail-closed 到现状语义）并留日志。
- 每轮重试 MUST 在**同一 worktree** 内进行；轮间 MUST 注入累计失败明细（上一轮失败集，含此前修过的用例若再次失败）。
- 某定向轮回归（失败子集重跑）`passed` 时 MUST 按正常路径合回并核销该批条目。
- 耗尽 `targeted_retry_max` 轮仍未 `passed` 时 MUST 丢弃该批：MUST NOT 合回、MUST NOT 置 `resolved`，条目 MUST 保持 `open`（进入失败档案）。
- 熔断提前终止与轮数耗尽共用同一收口语义：丢弃时 MUST 在清理现场**前**把 `branch` 与 `tip_sha`（连同 `reason`、`failed_at`、最后一轮失败用例明细引用）写入失败档案记录，随后 MUST 清理失败 worktree 并释放 spec 锁。收口告警 MUST 复用既有 `write_regression_failed_alert` 路径（告警名 `regression_failed_twice` 历史兼容名不变），`retry_rounds` 按实际执行轮数如实传入；熔断收口与轮数耗尽收口 MUST NOT 对同批重复发告警。熔断收口日志 MUST 为 WARNING 级并包含熔断触发判据（两轮各自的回归 status 与明细形态），供事后区分「测试失败耗尽」与「回归没跑出结果被熔断」。
- 失败档案中的条目，后续检查点 MUST 跳过（同链内 MUST NOT 重复派发同一批）；新链启动时按 `fail_count` 预算自动释放（`fail_count < FAIL_RETRY_MAX`），预算内条目 MUST NOT 要求人工解除才能重试。
- 达到预算上限（`fail_count ≥ FAIL_RETRY_MAX`）的条目集 MUST 永久跳过，并在 `fail_count` 递增至上限那次入档时发一次性 warning 告警（点名录）、同时在 `.fenix/todo.md` 追加待人工清理项。

#### Scenario: 定向轮修复后通过

- **WHEN** 首轮全量回归失败 3 例，第 1 轮定向重试只修复该 3 例相关问题，子集回归只重跑该 3 例且通过
- **THEN** 框架 MUST 合回该批并核销条目，MUST NOT 重跑全量回归，子集回归的实际执行用例数 MUST 等于失败集大小

#### Scenario: 测试自身缺陷被修复

- **WHEN** 失败用例经 agent 判定为测试本身缺陷（如断言过时、替身真自旋）且修复测试后子集回归通过
- **THEN** 框架 MUST 按通过路径合回，且该轮产物行 MUST 带 `fix_scope=test` 标注供审计

#### Scenario: 轮数耗尽现场即弃

- **WHEN** 连续 `targeted_retry_max`（缺省 3）轮定向重试后子集回归仍失败
- **THEN** 框架 MUST 按既有丢弃语义入失败档案（`branch`/`tip_sha`/明细引用入档）、清理 worktree、释放 spec 锁、链继续推进下一批

#### Scenario: 回归异常熔断提前终止

- **WHEN** 同批内连续 2 轮回归结局为 `parse_error`（或 `failed` 但明细为空且 `fallback_full=true`），定向重试尚未耗尽 `targeted_retry_max` 轮数
- **THEN** 框架 MUST 立即终止重试循环（不再派发第 3 轮定向 run 与全量回归），按现场即弃语义收口，批收口 `reason` 为 `regression_parse_error_breaker`，收口告警恰好发一次且 `retry_rounds` 等于实际执行轮数

#### Scenario: 真实测试失败不触发熔断

- **WHEN** 第 1 轮回归 `parse_error`（熔断计数 1），第 2 轮回归 `failed` 且成功提取到非空失败明细（真实测试失败）
- **THEN** 熔断计数 MUST 清零，重试循环 MUST 继续走既有定向重试路径直至 `targeted_retry_max` 轮数耗尽，收口 `reason` 沿用既有轮数耗尽语义

#### Scenario: 首轮通过零定向轮

- **WHEN** 某批首轮全量回归 `passed`
- **THEN** MUST NOT 派任何定向轮，主路径行为与现状逐字一致

#### Scenario: 预算内失败批下轮自动重试

- **WHEN** 上一轮因定向轮耗尽（或熔断）丢弃了第 1 批（条目在失败档案且 `fail_count < FAIL_RETRY_MAX`），其后新链启动
- **THEN** 检查点 MUST 自动释放该记录并重新组批该批条目（重组批从首轮全量回归起重新走本轮 SPEC 的门与定向轮语义），MUST NOT 要求人工调 `release_failed_batch` 解除
