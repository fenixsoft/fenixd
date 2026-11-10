## ADDED Requirements

### Requirement: 人工解冻清零 judge 重跑计数与硬上限旗标

`unfreeze_spec` 的清零集 MUST 包含 `_judge_rerun_count = 0` 与 `_judge_cap_frozen = False`，与既有验证计数（`_verify_redo_count`/`_env_block_rounds` 等）并入同一原子写。解冻后 judge 派发门的重跑判定 MUST 从 0 重新起算（`0+1=1 ≤ 上限`），不因解冻前残留计数再次触发 `_judge_hard_cap_freeze`。`_judge_cap_frozen` MUST 随解冻清除——该旗标残留会使计数恒停（自动递增失效），judge 生命周期预算永久失效。

#### Scenario: judge_rerun_cap 冻结解冻后可正常重验
- **WHEN** SPEC 处于 `_judge_rerun_count=6`、`_judge_cap_frozen=True` 的冻结态，人工调用 unfreeze_spec
- **THEN** 解冻后 `_judge_rerun_count=0`、`_judge_cap_frozen=False`，后续 verify→judge 链正常派发（计数从 1 重新累计），不出现 `count > 上限` 的原样再冻

#### Scenario: 与既有清零集同一原子写
- **WHEN** unfreeze_spec 执行清零
- **THEN** 新增两字段与既有清零字段在同一原子写内落盘，无中间态窗口

#### Scenario: 字段缺失条目前向兼容
- **WHEN** 旧条目 STATE 中无 `_judge_rerun_count`/`_judge_cap_frozen` 键（存量 spec），执行 unfreeze_spec
- **THEN** 清零写等价于补零，无异常、无其他字段被扰动
