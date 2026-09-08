# spec-duration-persistence — ADDED Requirements

## ADDED Requirements

### Requirement: done 状态固化总耗时到 STATE.md

SPEC 状态从 verified 转换为 done 时，系统 SHALL 立即计算该 SPEC 的总耗时并作为 `total_duration` 字段写入 STATE.md 条目。

总耗时 SHALL 等于该 SPEC 全部 run 产物（implementer/verifier/planner/tester/admin 等，含 `runs/archive/` 归档产物）的 `duration_seconds` 之和（秒，整数）；无任何 run 产物时 SHALL 写入 0。

#### Scenario: 验证通过转 done 时写入耗时

- **WHEN** SPEC 通过验证，状态由 verified 转换为 done，且该 SPEC 存在 run 产物（如 impl 运行 100 秒 + planner-judge 运行 50 秒）
- **THEN** STATE.md 该 SPEC 条目出现 `total_duration: 150`

#### Scenario: 无 run 产物时写入 0

- **WHEN** SPEC 转换为 done 但 runs/ 与归档中无任何匹配该 SPEC 的 run 产物
- **THEN** STATE.md 该条目写入 `total_duration: 0`

#### Scenario: done 转 pushed 后字段不重算

- **WHEN** 已写入 `total_duration` 的 done SPEC 后续转换为 pushed
- **THEN** STATE.md 中该字段保持 done 时刻的值不变

### Requirement: total_duration 字段跨 STATE.md 重写持久

STATE.md 的序列化 SHALL 包含 `total_duration` 字段，使字段在 daemon 多次条目更新、状态转换与重启往返后不丢失。

#### Scenario: 序列化往返保留字段

- **WHEN** 含 `total_duration` 的条目经历任意 `update_spec` 触发的 STATE.md 重写
- **THEN** 重写后的 STATE.md 仍包含该条目的 `total_duration` 行且值不变

### Requirement: dashboard 对已完成 SPEC 优先返回持久耗时

Dashboard 的 SPEC 摘要（spec_summary）对状态为 done 或 pushed 的 SPEC，SHALL 在 STATE.md 条目含非空 `total_duration` 字段时直接返回该值（int，秒）；字段缺失时 SHALL 回退现有 run 产物求和逻辑。

#### Scenario: 已完成 SPEC 从 STATE.md 返回耗时

- **WHEN** /api/specs 请求一个 done/pushed 且 STATE.md 含 `total_duration: 150` 的 SPEC
- **THEN** 返回的 `total_duration` 为 150（即使 run 产物已被清理）

#### Scenario: 存量 SPEC 缺字段时回退

- **WHEN** /api/specs 请求一个 done/pushed 但 STATE.md 无 `total_duration` 字段的存量 SPEC
- **THEN** 返回的 `total_duration` 等于现有 run 求和结果（数据已丢失时为 0），接口不报错

#### Scenario: 非完成状态不受影响

- **WHEN** /api/specs 请求一个 implementing/testing 等非完成状态的 SPEC（无论其条目是否含 total_duration）
- **THEN** 返回的 `total_duration` 仍由 run 产物实时求和得出
