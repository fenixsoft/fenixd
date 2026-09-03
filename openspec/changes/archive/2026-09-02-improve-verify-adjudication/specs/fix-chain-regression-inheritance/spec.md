# fix-chain-regression-inheritance 能力（improve-verify-adjudication）

> 背景：add(15 场景) → fix(17) → fix-fix(6) 的覆盖缩水使首轮暴露的回归场景在后续轮次中悄然消失。本能力保证缺陷修复链始终背负其来源场景。

## ADDED Requirements

### Requirement: 父 SPEC 回归场景注入

框架在创建或重置 fix SPEC 时，MUST 读取父 SPEC 最新 report.json 中 status 为 `fail` 或从未出现于该报告的场景清单，将其注入 fix SPEC 的验证材料：写入 fix SPEC 目录下的回归场景清单文件（含父 SPEC 名、场景 id、失败摘要），并在 proposal.md/tasks.md 中声明这些场景为必测项。

#### Scenario: 新建 fix SPEC 携带继承清单

- **WHEN** 父 SPEC P 验证产生产品缺陷，报告含失败场景 Y 与未执行场景 X，框架派生 fix-P
- **THEN** fix-P 的目录下存在回归清单文件且记录 {X, Y} 及其来源；tasks.md 明确要求本轮验证必须覆盖这两个场景

#### Scenario: 多级 fix 不丢失继承

- **WHEN** fix-P 自身验证失败又派生 fix-fix-P
- **THEN** fix-fix-P 继承的回归清单 MUST 包含 P 与 fix-P 两轮的失败/未执行场景并集，而非仅最近一轮

### Requirement: fix 轮放行强制闭环

fix SPEC 推进到 `done`/`pushed` 前，除通用进度与质量门禁外，框架 MUST 校验其继承的每个回归场景在本轮 report.json 中均已执行且通过；任一缺失或失败则阻止推进并在 error 字段写明缺口场景 id。Administrator 可显式豁免某场景（豁免操作 MUST 落盘留痕，标记「人工确认不需复测」及理由），被豁免的场景视为闭环。

#### Scenario: 未覆盖继承场景被拦截

- **WHEN** fix-P 宣称 6/6 场景全过，但其继承清单中的场景 Y 未出现在本轮 report.json 的任何场景结果里
- **THEN** 放行被阻止，SPEC 保持 verified，error 字段包含「回归闭环缺口：Y」

#### Scenario: 继承场景全部通过后放行

- **WHEN** fix-P 本轮报告中继承清单内全部场景均为 pass
- **THEN** 回归闭环闸门放行，其余门禁正常生效

#### Scenario: Administrator 显式豁免视为闭环

- **WHEN** Administrator 对场景 Z 写入带理由的豁免标记，随后该 SPEC 再次触发放行校验
- **THEN** Z 不再构成放行阻塞，但豁免记录须可在告警与日志中追溯
