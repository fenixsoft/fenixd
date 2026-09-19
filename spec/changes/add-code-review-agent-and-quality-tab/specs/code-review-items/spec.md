## ADDED Requirements

### Requirement: 问题台账存储

系统 SHALL 以独立台账文件持久化代码质量问题条目。

- 台账路径 MUST 为 `.fenix/code-review/items.jsonl`（每行一条 JSON）。
- 每条 MUST 至少含字段：`item_id`、`project`、`review_id`、`review_kind`、`reviewed_at`、`spec`、`file`、`line`、`severity`、`category`、`title`、`description`、`suggestion`、`evidence`、`fingerprint`、`status`、`spec_name`、`first_seen_at`、`last_seen_at`。
- `review_kind` MUST 取值于 `scheduled`（周期自省）/ `manual_full`（手动全仓）/ `manual_window`（手动本周期）。
- `severity` MUST 取值于 `critical | major | minor | info`。
- `status` MUST 取值于 `open | in_spec | resolved | ignored`。
- `item_id` MUST 唯一且稳定（同一问题重复观测不变）。

#### Scenario: 一次审查结果写入台账

- **WHEN** 一次审查产出 8 条问题
- **THEN** `.fenix/code-review/items.jsonl` MUST 追加 8 条记录，每条 `status` 初始为 `open`，`first_seen_at == last_seen_at`

### Requirement: 指纹去重

系统 SHALL 以 `fingerprint = sha1(file + category + 归一化 title)[:12]` 作为问题去重权威，避免周期性重复扫描产生重复条目。

- 同一 fingerprint 再次被观测到时，MUST NOT 插入新条目，MUST 仅更新既有条目的 `last_seen_at`（并刷新 `severity`/`description` 等可变字段）。
- `title` 归一化规则 MUST 稳定可复现（如去首尾空白、折叠内部空白、大小写统一），保证同一问题跨轮 fingerprint 一致。

#### Scenario: 重复观测不新增条目

- **WHEN** 台账已含 fingerprint 为 `abc123` 的 open 条目，新一轮审查再次观测到同一问题
- **THEN** 台账条目总数 MUST NOT 增加，该条目 `last_seen_at` MUST 被更新为本次时间

#### Scenario: 跨轮指纹稳定

- **WHEN** 同一问题在两轮审查中标题仅首尾空白或大小写不同
- **THEN** 两轮 MUST 得到同一 fingerprint，MUST 判为同一条目

### Requirement: 全仓快照核销

`manual_full`（全仓审查）SHALL 作为权威快照，用于自动核销已消失的问题；窗口审查 MUST NOT 核销。

- 一次 `manual_full` 审查完成后，台账中仍为 `open` 但本轮未再被观测到的条目 MUST 置为 `resolved`（记录核销时间）。
- `scheduled` / `manual_window` 审查 MUST 只增不核销（窗口外的问题不在本轮观测范围，不得据此判 resolved）。
- 已 `in_spec`（已关联修复 SPEC）或 `ignored` 的条目 MUST NOT 被自动核销覆盖。

#### Scenario: 全仓审查核销已修复问题

- **WHEN** 台账含一条 open 条目（上轮全仓审查发现），本次全仓审查未再观测到它
- **THEN** 该条目 MUST 置为 `resolved`，MUST NOT 继续显示在默认 open 列表

#### Scenario: 窗口审查不核销

- **WHEN** 一次 `manual_window` 审查未观测到某条窗口外的 open 问题
- **THEN** 该条目 MUST 保持 `open`，MUST NOT 被置为 `resolved`

### Requirement: 条目状态流转

系统 SHALL 支持条目状态的人工流转。

- `ignored` MUST 由用户在 Dashboard 显式标记，标记后 MUST NOT 出现在默认问题列表。
- `in_spec` MUST 在条目被用于生成修复 SPEC 时自动置入，并记录 `spec_name`。
- `resolved` MUST 由全仓快照核销置入。
- 状态流转 MUST 幂等：重复标记为同一状态 MUST NOT 报错或产生副作用。

#### Scenario: 忽略问题

- **WHEN** 用户对某条 open 问题点击「忽略」
- **THEN** 该条目 `status` MUST 变为 `ignored`，默认问题列表 MUST 不再包含它

#### Scenario: 生成 SPEC 后标记归属

- **WHEN** 某条目被选中并成功生成修复 SPEC `fix-cr-xxx`
- **THEN** 该条目 `status` MUST 变为 `in_spec` 且 `spec_name == "fix-cr-xxx"`
