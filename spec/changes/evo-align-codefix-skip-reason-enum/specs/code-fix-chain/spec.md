# 能力：code-fix-chain（修复链收敛与豁免硬出口）

## 需求

### R1 skip_reason 前缀归一匹配

- 产物行 status=skipped 且 skip_reason 去除首尾空白后以 IGNORE_ELIGIBLE_SKIP_REASONS 任一枚举值开头时，视同命中豁免硬出口；skip_reason 完整原文（含后缀解释）作为该条目转 ignored 的理由写入台账。
- 裸枚举（整串相等）行为与现状完全一致，向后兼容。

### R2 脱靶 skipped 行可观测

- status=skipped 但 skip_reason 既非裸枚举也不以枚举值开头的产物行，处理时记一条 warning 日志（含 item_id 与 skip_reason 原文）；语义不变：仍不进豁免硬出口。

### R3 模板契约单点口径

- agents/code-fix.md：skip_reason 只允许写裸枚举；解释文本写入产物行新增的可选字段 reason；(no_marker) 规则改为「skip_reason 保持裸值，(no_marker) 信息写 reason 字段」；:24 的「在 skip_reason 或回复中说明」表述同步修正；产物 schema（:76-81）增补可选 reason 字段。
- runner 侧解析兼容 reason 字段：命中 R1 时把 reason（若有）与 skip_reason 原文一并写入 ignored 理由。

### R4 链级零进度护栏

- 同一修复链连续 2 轮收尾 rollup 的 resolved+ignored=0 时：发 admin 信号（说明链、涉及条目与连续零进度轮数）并暂停该链自动重派。
- 计数与解除：任一轮出现 resolved>0 或 ignored>0 即计数归零；人工介入处置或新一轮评审产出台账变更后解除暂停；与夜静窗守卫（NIGHT_QUIET_WINDOW_DEFAULT，core/code_fix.py:3249）正交，不改变其行为。

## Scenario

- Scenario 带后缀豁免命中：fixer 写 skip_reason 为 'false_positive (位置已有 fenix-ignore:xxx 标记…)' → runner 前缀命中，条目转 ignored，理由含完整原文，链当轮收敛，不再空转重派。
- Scenario 脱靶可观测：fixer 写无法识别的 skip_reason → warning 日志留痕，条目保持 open，链零进度计数加一。
- Scenario 零进度熔断：同链连续 2 轮 resolved=0 且 ignored=0 → admin 信号落告警面，自动重派暂停。
- Scenario 裸枚举回归：fixer 写裸枚举 false_positive → 行为与现状一致。