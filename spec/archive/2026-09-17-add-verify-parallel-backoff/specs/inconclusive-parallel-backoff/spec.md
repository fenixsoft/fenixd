# spec-inconclusive-parallel-backoff

## ADDED Requirements

### Requirement: inconclusive 重验并行度按 attempt 递减
当 `_handle_env_blocked_inconclusive` 判定本轮为全批 blocked-env（inconclusive）且 attempt < 上限时，框架 SHALL 按连续 blocked-env attempt 数计算降档并行度并写入 spec attrs 的 `_verify_parallel_override` 字段，下一轮验证 `VerifyEngine` MUST 以该值覆盖 `max_parallel` 配置值。递减规则：attempt 1（首次重验判定）不降档（`_verify_parallel_override` 不写入）；attempt ≥ 2 起有效并行度 = max(1, 配置值 >> (attempt - 1))（即逐 attempt 减半向下取整，下限 1）。

#### Scenario: 首次 inconclusive 重验不降档
- **WHEN** 某 SPEC 第 1 轮验证全批 blocked-env，`_inconclusive_attempts=1`，配置 max_parallel=5
- **THEN** spec attrs 不含 `_verify_parallel_override`，重验轮有效并行度=5

#### Scenario: 连续 blocked-env 逐轮递减
- **WHEN** 连续 blocked-env 使 `_inconclusive_attempts=2` 后重验，配置 max_parallel=5
- **THEN** `_verify_parallel_override=2`，重验轮引擎日志显式并行度=2；若该轮仍全批 blocked-env 使 `_inconclusive_attempts=3`，`_verify_parallel_override=1`

#### Scenario: 低配置值直接触底
- **WHEN** 配置 max_parallel=2 且 `_inconclusive_attempts=2`
- **THEN** `_verify_parallel_override=1`

### Requirement: 健康轮自动复位降档
任一轮验证结果非 inconclusive（出现有效失败 failed+errors>0，或 verdict 为 verified/bug-found 等正常判定）时，框架 SHALL 清除 `_verify_parallel_override`；`_inconclusive_attempts` 的既有清零点（人工解冻 unfreeze、fast-track verified 清零）MUST 同步清 `_verify_parallel_override`。

#### Scenario: 环境恢复后并行度复位
- **WHEN** 降档轮（并行度 2）验证不再全批 blocked-env（如出现真实 bug-found 或 verified）
- **THEN** `_verify_parallel_override` 被清除，后续验证恢复配置并行度

#### Scenario: 人工解冻后降档不残留
- **WHEN** SPEC 因 inconclusive_loop 达升级阈值被冻结，人工 unfreeze 处置
- **THEN** `_inconclusive_attempts` 与 `_verify_parallel_override` 同轮清零，重验从配置并行度开始

### Requirement: 降档可观测
降档生效轮的验证 SHALL 在引擎启动日志与 report.json 中透出有效并行度及降档来源（非 inconclusive 重验轮 MUST 不出现降档标记），使「因连续 blocked-env 降档至并行度 N」在时间轴可追溯。

#### Scenario: 降档轮日志与报告可见
- **WHEN** 重验轮以 `_verify_parallel_override=2` 执行
- **THEN** 引擎启动日志含「并行度=2（inconclusive 降档）」语义信息，report 顶层记录 effective_parallel=2

#### Scenario: 正常轮无降档标记
- **WHEN** 无 `_verify_parallel_override` 的常规验证轮执行
- **THEN** 日志并行度=配置值，无降档来源标记，report 不含 effective_parallel 降档语义
