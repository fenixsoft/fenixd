# code-fix-chain 变更

## ADDED Requirements

### Requirement: skip_reason 前缀归一匹配

产物行 status=skipped 且 skip_reason 为字符串、去除首尾空白后以 IGNORE_ELIGIBLE_SKIP_REASONS 任一枚举值（core/code_fix.py:125）开头时，视同命中豁免硬出口；skip_reason 完整原文（含后缀解释）与产物行可选 reason 字段作为该条目转 ignored 的理由写入台账（mark_ignored 的 reasons 形参，core/code_review.py:2343）。skip_reason 缺失或非字符串按未命中处理，MUST NOT 抛异常。裸枚举（整串相等）行为与现状完全一致，向后兼容。

#### Scenario: 带后缀豁免命中

- **When** fixer 写 skip_reason 为 `false_positive (位置已有 fenix-ignore:xxx 标记…)`
- **Then** runner 前缀命中，条目转 ignored，理由含完整原文（及 reason 字段若有），链当轮收敛，不再空转重派

#### Scenario: 裸枚举回归

- **When** fixer 写裸枚举 `false_positive`
- **Then** 行为与现状一致（置 ignored 终态，理由为裸值）

#### Scenario: 非法形态安全

- **When** 产物行 skip_reason 缺失或为非字符串值
- **Then** 按未命中白名单处理（条目保持 open），解析不抛异常

### Requirement: 脱靶 skipped 行可观测

status=skipped 且 skip_reason 为非空字符串、既不命中白名单（裸值或前缀）也不属既有 skipped 词汇表（unfixable、needs_human）时，处理时记一条 warning 日志（含 item_id 与 skip_reason 原文）。既有词汇表成员（unfixable/needs_human）与缺省（无 skip_reason）保持现状静默；脱靶行语义不变：仍不进豁免硬出口，条目保持 open。

#### Scenario: 脱靶可观测

- **When** fixer 写无法识别的 skip_reason（非既有词汇表成员）
- **Then** warning 日志留痕，条目保持 open，链零进度计数加一

#### Scenario: 既有词汇表不告警

- **When** fixer 写 `unfixable` 或 `needs_human`
- **Then** 行为与现状一致（保持 open、无新 warning 日志）

### Requirement: 模板契约单点口径

agents/code-fix.md：skip_reason 只允许写裸枚举；解释文本写入产物行新增的可选字段 reason；(no_marker) 规则（:106）改为「skip_reason 保持裸值，(no_marker) 信息写 reason 字段」；:24 的「在 skip_reason 或回复中说明」表述同步修正；产物 schema（:83-90）增补可选 reason 字段。runner 侧解析兼容 reason 字段：命中前缀归一时把 reason（若有）与 skip_reason 原文一并写入 ignored 理由。

#### Scenario: 过渡形态互认

- **When** 模板收紧后存量/回退产物仍写带后缀的 skip_reason（如 `(no_marker)` 尾注）
- **Then** 读侧前缀归一仍命中，不因模板收紧产生新一轮脱靶空转

### Requirement: 链级零进度护栏

同一修复链连续 2 轮收尾 rollup（各链终局写点经 _chain_terminal_fields → _emit_chain_rollup 出账，出账后链级计数归零，rollup 值即逐轮增量）的 resolved+ignored=0 时：发 admin 信号（说明链与连续零进度轮数，形态参照夜静窗守卫的 AdminStore 信号通道）并暂停该链自动重派。计数与暂停标记随链级进度字段持久化（沿用既有 phase=blocked 落盘与文案分流体系）；任一轮出现 resolved>0 或 ignored>0 即计数归零；解除路径：人工处置（既有 manual 授权/重派入口）或新一轮评审产出台账变更（选批扫描复核解除）。与夜静窗守卫（NIGHT_QUIET_WINDOW_DEFAULT，core/code_fix.py:3463）正交，不改变其行为。

#### Scenario: 零进度熔断

- **When** 同链连续 2 轮收尾 rollup 的 resolved=0 且 ignored=0
- **Then** admin 信号落告警面，该链自动重派暂停，进度面呈现暂停原因

#### Scenario: 进度恢复归零

- **When** 连续 1 轮零进度后，任一轮出现 resolved>0 或 ignored>0
- **Then** 零进度计数归零，不触发暂停

#### Scenario: 暂停解除

- **When** 暂停后人工完成处置，或新一轮评审产出台账变更
- **Then** 选批扫描复核后解除暂停，链恢复自动重派
