# 验证报告：evo-add-frozen-scenario-schema-migration

> ⚠️ 本报告由框架于 2026-09-13T07:08:28Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 7/7 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 7/7 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 7 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.83M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| schema-migration-old-cli-to-new | 旧 schema 冻结文件 cli 场景自动迁移：run 步骤 value→command、output_match 断言 value→expected，迁移后校验通过验收（spec：冻结场景读侧旧 schema 兼容迁移） | pass | 0/3 | - |
| schema-migration-new-zero-change | 新 schema 文件行为零变化回归：已含 command / expected 字段时不做迁移，校验路径与现状一致（spec：新 schema 文件行为零变化） | pass | 0/3 | - |
| schema-corrupt-field-level-report | 真损坏文件报字段级差异清单：既无新字段也无旧字段时报错列出具体场景 id / 下标 / 缺失字段，不吞笼统 corrupt（spec：真损坏报字段级差异） | pass | 0/4 | - |
| schema-version-marker-write-and-read | 场景文件 schema 版本标记：写端持久化恒定写入 schema_version，读侧按版本路由迁移（当前版本直通、未知版本走迁移尝试+差异报错）（spec：场景文件 schema 版本标记） | pass | 0/7 | - |
| blocked-stuck-disposition-auto-reset | blocked_stuck 处置后自动复位：admin 处置成功（result=resolved）且阻塞类型为 blocked_stuck 时，已合并则直通 testing，未合并则转 ready；处置未完成不动状态（spec：blocked_stuck 处置后自动复位） | pass | 0/6 | - |
| migration-only-applies-when-target-missing | 迁移幂等性与条件性：仅当目标字段（command / expected）缺失时迁移，新字段存在则零干扰；迁移为幂等操作（spec：仅对目标字段缺失且旧字段存在生效） | pass | 0/2 | - |
| frozen-spec-blocked-not-auto-reset | 人工冻结 spec 不触发自动复位：frozen=True 的 blocked_stuck 不在 _reset 分支，需人工处置是唯一出路（spec：frozen 守卫） | pass | 0/3 | - |

## 本轮场景集变更

当前稳定场景集共 17 个（第 1 轮）。

- 首轮写入 17 个场景
- 写端校验剔除 17 条非法条目（未落盘）：blind-run-marker-failed（场景'blind-run-marker-failed'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout）；场景'blind-run-marker-failed'断言2: json_output 需要 step（指定解析哪个命名结果的 stdout））、real-success-run-succeeded（场景'real-success-run-succeeded'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout）；场景'real-success-run-succeeded'断言2: json_output 需要 step（指定解析哪个命名结果的 stdout））、budget-exhausted-marker-failed（场景'budget-exhausted-marker-failed'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout）；场景'budget-exhausted-marker-failed'断言2: json_output 需要 step（指定解析哪个命名结果的 stdout））、signal-fallback-no-marker（场景'signal-fallback-no-marker'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout）；场景'signal-fallback-no-marker'断言2: json_output 需要 step（指定解析哪个命名结果的 stdout））、empty-run-dropped（场景'empty-run-dropped'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout）；场景'empty-run-dropped'断言2: json_output 需要 step（指定解析哪个命名结果的 stdout））、marker-list-invariants（场景'marker-list-invariants'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout）；场景'marker-list-invariants'断言2: json_output 需要 step（指定解析哪个命名结果的 stdout））、marker-wins-without-signal（场景'marker-wins-without-signal'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout）；场景'marker-wins-without-signal'断言2: json_output 需要 step（指定解析哪个命名结果的 stdout））、midfile-signal-full-scan（场景'midfile-signal-full-scan'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout）；场景'midfile-signal-full-scan'断言2: json_output 需要 step（指定解析哪个命名结果的 stdout））、collect-runs-stats-aggregation（场景'collect-runs-stats-aggregation'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout）；场景'collect-runs-stats-aggregation'断言2: json_output 需要 step（指定解析哪个命名结果的 stdout））、failed-samples-traceability（场景'failed-samples-traceability'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout）；场景'failed-samples-traceability'断言2: json_output 需要 step（指定解析哪个命名结果的 stdout））、samples-sorted-and-limited（场景'samples-sorted-and-limited'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout）；场景'samples-sorted-and-limited'断言2: json_output 需要 step（指定解析哪个命名结果的 stdout））、review-prefix-excluded（场景'review-prefix-excluded'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout）；场景'review-prefix-excluded'断言2: json_output 需要 step（指定解析哪个命名结果的 stdout））、error-terminal-regression（场景'error-terminal-regression'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout）；场景'error-terminal-regression'断言2: json_output 需要 step（指定解析哪个命名结果的 stdout））、timeout-terminal-regression（场景'timeout-terminal-regression'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout））、instant-hang-regression（场景'instant-hang-regression'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout））、running-no-terminal（场景'running-no-terminal'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout））、zero-delivery-marker-failed（场景'zero-delivery-marker-failed'断言1: json_output 需要 step（指定解析哪个命名结果的 stdout）；场景'zero-delivery-marker-failed'断言2: json_output 需要 step（指定解析哪个命名结果的 stdout））

