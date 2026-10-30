# self-review-evidence-bound-attribution

## Why

2026-10-08 的 daily self-review（提交 4e64e220）在 [2026-10-08#浪费#1] 写下「直接根因是模型修复质量（修 A 破 B 的回归）」并建议「失败面预检重跑」，而同一条目的证据段自己写明「回归失败清单 items 为空时 fallback_full=true（无法定位失败面）」——当时不掌握任何失败面证据，却给出单因确定性归因。核查（evolution run evo-1791477251）证实矛盾在场：10-07 可回收的 9 份回归失败明细全部 items=[]、fallback_full=true（两窗现存口径实为 20 份无一例外）。若 evo lane 按该建议立项预检重跑，对 timeout 形态无效（重跑同样撞死），将烧掉一个 spec 预算；当日未走该方向属侥幸（a26dbe88 落地的是 anomaly 预算熔断，与归因无关），复发敞口仍在。agents/self-review.md 的调查评估质量标准只有「核实不了的写明未核实」（:22），缺「证据只覆盖形态时结论只写到形态层」的下位纪律——归因层级是语义判断，代码层无可加校验的判定点（core/self_review.py 对 analysis 字段仅渲染），纪律只能落在模板层。

## What Changes

- agents/self-review.md「调查评估」质量标准段（约 :22-24）追加归因证据边界纪律：凡结论涉及根因归因，必须逐项对照当日可回收证据（明细档/告警/日志/commit）；证据只覆盖失败形态（如 items 空、fallback_full=true、total=0）时，结论只写到形态层，根因写「未定、多假说并存」，MUST NOT 给出单因确定性叙事、MUST NOT 据此建议针对特定根因的修复方向（此形态下建议动作转向取证/止损方向，不依赖未证实假说）；发现既有条目归因有误时以新条目更正、不回改历史条目原文。

## Impact

- Affected specs: self-review（提示词纪律）
- Affected code:
  - agents/self-review.md：调查评估质量标准段（模板经 prompt_builder 装载、缺失 fail-fast，改模板即生效、无代码改动）
- Tests:
  - 无单测（纯提示词文本变更；归因层级是语义判断，机械校验误报高）；由下一窗 daily self-review 的归因措辞作验收观测
- 风险：极低——只收紧结论措辞要求，不改数据聚合与渲染链路。