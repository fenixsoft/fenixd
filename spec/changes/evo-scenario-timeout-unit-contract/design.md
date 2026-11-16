# Design: scenario-timeout-unit-contract

## Context

校验器 core/verify_engine/scenarios.py:48 timeout 上限 1800 秒；提示词 agents/planner-plan.md:124 仅列 timeout 可选、无单位；2026-10-22 的量级门（65cf52653）挡落盘不消除错位；11-08（m0-a2a 8 条）与 11-10（m3-audio 15 条）两次整批拒绝。

## Goals / Non-Goals

- Goals：单位约定在提示词层显式化；报错提供换算嫌疑线索；保持既有预校验闸门语义。
- Non-Goals：不改 timeout 上限与校验规则；不给场景 schema 增加单位字段（保持秒为唯一约定，避免双单位兼容面）；不追溯已冻结场景。

## Design

1. **提示词（agents/planner-plan.md）**：timeout 字段描述补「单位为秒、上限 1800」与示例（如 120/900/1500），与校验器文案一致。
2. **报错（scenarios.py timeout 校验分支）**：值 >1800 且 value % 1000 == 0 时，报错文案追加「疑似毫秒，建议除以 1000 后重写」；其余超限维持现文案。
3. **一致性防回归**：单测断言提示词含单位约定（文本断言）+ 校验嫌疑提示触发条件，防止未来提示词改版再次丢失单位语义。

## Risks / Trade-offs

- 提示词为自然语言约定、无运行时强制——量级门（既有）仍是最后防线，本 SPEC 消除的是「错位频繁触发」而非「不可能写错」。
- 嫌疑提示对「恰好可被 1000 整除的秒值」（如 2000 秒）会误提示——概率低且提示为非阻断建议，可接受。

## Migration

无数据迁移；提示词与报错文案即时生效。