# Proposal: scenario-timeout-unit-contract

## Why

场景 timeout 字段的单位约定在规划器与校验器之间断裂，3 日内两次整批拒绝：2026-11-08 m0-a2a-streaming-pipeline 并行出题产物 8 条被拒（180000.0/1800000.0），2026-11-10 m3-audio-clipboard-textinput 重排产物 15 条被拒（60000.0~1800000.0）——值全为毫秒形态，而校验器（core/verify_engine/scenarios.py:48）按秒读、上限 1800 秒，报错只回显数值与上限、无单位提示。

根因是持久的提示词缺口：agents/planner-plan.md:124 仅列 timeout 为可选字段、无单位约定（被拒 run 思考痕迹自述「timeout option semantics unknown…engine will clamp」）。2026-10-22 曾因「planner 以毫秒语义误写」加过量级校验门（65cf52653），但规划提示词始终未补单位——量级门挡住了非法值落盘，却没消除错位本身，每次触发仍烧一轮重排（11-10 一轮 1254s+612s≈31 分钟）。两轮重排均靠规划器自行诊断出根因才命中，报错信息未提供任何单位嫌疑线索。

## What Changes

- **提示词单位约定（agents/planner-plan.md）**：timeout 与 sse_connect duration 字段补「单位为秒」的显式约定与合法示例值，与校验器语义对齐（两字段共用同一 1800 秒上限常量）。
- **报错嫌疑提示（core/verify_engine/scenarios.py）**：timeout/duration 超上限且值可被 1000 整除时，报错附加「疑似毫秒，建议除以 1000」提示，让重排一轮命中。
- **单测**：覆盖提示词约定一致性校验与报错嫌疑提示触发条件。

## Capabilities

### planner-scenario-schema

见 specs/planner-scenario-schema/spec.md。

## Impact

- agents/planner-plan.md 提示词变更即时生效于新 planner-plan run。
- core/verify_engine/scenarios.py 校验报错文案增强，校验语义与上限不变。