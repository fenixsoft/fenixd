## ADDED Requirements

### Requirement: 裁决选项风险档位声明

注册表 MUST 为每个裁决选项声明风险档位字段 `risk_tier`，取值限定 `reversible-experiment`（reset 类：清计数重验等失败可自然再冻结再告警的自限动作）、`state-advance`（带病推进类）、`terminal`（终局不可逆类），与 signal_type→choices 映射同源单点维护于 core/dashboard/data/adjudication_choices.py。策略引擎仅可自动执行 `reversible-experiment` 档选项；历史条目缺档时 MUST 按最保守 `terminal` 兜底（不自动执行）。档位声明 MUST NOT 改变既有 choice 解析、payload 校验与执行行为。

#### Scenario: 每条选项携带合法档位
- **WHEN** 注册表任意桶中任一 choice 条目被读取
- **THEN** 其 risk_tier 字段存在且取值为三档之一，judge_rerun_cap 桶的 manual_fixed_reverify 声明为 reversible-experiment，force_advance 声明为 state-advance，abandon 声明为 terminal

#### Scenario: 缺档保守兜底
- **WHEN** 新增 choice 条目未声明 risk_tier（历史或笔误）
- **THEN** 读取侧按 terminal 兜底，策略引擎不自动执行该选项，既有解析与执行行为不受影响

#### Scenario: 档位不改变既有行为
- **WHEN** 人工经 alert-resolve 或链 closed 出口执行任一 choice
- **THEN** 解析、payload 校验、执行与留痕行为与引入 risk_tier 前完全一致
