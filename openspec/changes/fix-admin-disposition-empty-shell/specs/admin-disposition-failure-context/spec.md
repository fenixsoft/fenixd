# admin-disposition-failure-context Specification

## ADDED Requirements

### Requirement: 失败处置记录必须自解释

Administrator 处置 run 异常结束（`_run_claude` 抛出异常、CLI 非零退出、结果实例文件缺失）时，daemon 落盘的 final disposition 记录 SHALL 携带失败原因与信号上下文，使该记录无需日志考古即可回答"处置为什么失败"。空壳记录（`summary` 与 `action_taken` 均为空）MUST 不再出现。

#### Scenario: CLI 失败的 final 记录携带 error 与兜底字段

- **WHEN** `run_administrator` 的 `_run_claude` 抛出异常（如 `claude CLI failed: Exit code: 143`）且 Administrator 未写出处置实例文件
- **THEN** 落盘的 final disposition 记录满足以下全部断言：
  - `result` == `"failed"`
  - `error` 字段存在且等于异常文本（含退出码或错误标识）
  - `recommended_action` 等于触发信号（signal）的 `recommended_action`，为非空字符串
  - `description` 非空（`disp.problem or signal.description` 兜底）
  - `summary` 与 `action_taken` 允许为空，但 `error` 必须非空

#### Scenario: 成功处置记录不受影响

- **WHEN** Administrator 正常写出处置实例文件且 `result` 非 `failed`
- **THEN** final 记录各字段与现有行为一致：`summary`/`action_taken`/`recommended_action` 取自实例文件内容；`error` 字段为空字符串或不出现

### Requirement: 处置失败必须有 WARNING 日志

`run_administrator` 的 `_run_claude` 异常路径 SHALL 记录一条 WARNING 级日志，包含 run_id 与异常文本，确保失败可在 `fenixd.log` 中直接检索。

#### Scenario: 失败路径产生可检索日志

- **WHEN** `_run_claude` 在 `run_administrator` 中抛出任意异常
- **THEN** `fenixd.log` 出现一条 `level == "WARNING"` 且 `component == "agent_runner"` 的日志，其 message 同时包含该 run 的 `run_id`（形如 `admin-<spec>-<ts>`）与异常文本

### Requirement: 运维界面展示失败处置记录的原因

v3 activities 页（`/#/activities`）的 disposition 卡片 SHALL 在记录携带非空 `error` 字段时展示该失败原因；`summary` 为空的失败记录 MUST 显示 error 而非仅显示"（无叙述总结）"占位文案。

#### Scenario: 空壳记录卡片显示失败原因

- **WHEN** 打开 v3 运维记录页且存在一条 `result == "failed"`、`summary` 为空、`error` 非空的 disposition 记录
- **THEN** 该卡片正文区域渲染出 `error` 的文本内容（含退出码或错误标识），页面不再出现"仅时间 + 项目 + spec 名的可视信息"状态的失败处置卡片

#### Scenario: 旧记录向后兼容

- **WHEN** 打开 v3 运维记录页且记录不含 `error` 键（存量空壳记录）或 `error` 为空（成功记录）
- **THEN** 页面正常渲染不报错，卡片展示行为与现状一致
