# Design: add-verify-report-gate

## Context

验证链路现状：裁决 Agent（planner 兼任）按 prompt（`agent_runner.py` 裁决 prompt Step 4/5）写 `.fenix-run-result.json`（结构化终局结论）与 `verification-report.md`（人读报告）。既有 `verification-completion-gate` 能力已对 report.json 场景结论做 fail-closed 裁决，但**人读 Markdown 产物无任何结构化校验**。2026-08-29 v2-shell-hash-router 事故：Agent 返回 bug-found 且根因分析完整（在 .fenix-run-result.json 中），却跳过 Step 5；`pm_engine._ensure_fix_spec_files`（pm_engine.py:551-594）盲写引用该路径的 proposal/tasks，implementer 只能自行重新诊断 24+ 分钟。

## Goals / Decisions

### D1: 兜底用确定性合成，而非重跑验证或阻断
报告的全部关键内容（场景结论、真实产品 Bug、根因、证据）已结构化存在于 `report.json` 与 `.fenix-run-result.json`。合成是纯本地渲染，零额外成本；重跑验证烧钱且裁决可能漂移；一律阻断则让一个 Markdown 文件瘫痪整条验证链。合成失败（结构化数据也不可用）才 fail-closed 阻断 + 告警。

### D2: 合成器为共享 helper，单一实现
新增一个模块级函数（建议置于 `.fenix/core/` 下裁决/pm_engine 共同可达处），输入 spec 名，输出写好的报告文件；两个入口（裁决放行闸门、`_ensure_fix_spec_files`）都调用它。禁止第二套渲染逻辑（spec 中已作为 MUST 约束）。

### D3: Agent 报告优先，框架只兜底
prompt Step 5 保持不变——Agent 写的报告含叙述性分析，质量更高。闸门仅在文件缺失时介入，且 MUST NOT 覆盖既有文件。兜底合成时发 human-escalation-alerts 告警，使「Agent 未遵守 Step 5」这一劣化信号对 Administrator 可见，而不是被静默吸收。

### D4: fix 派生入口的前置校验是防御性重复，仍需要
裁决闸门理论上保证报告在派生前已存在，但两个入口是独立代码路径（闸门在裁决采纳处，派生在 bug-found 处理器），且状态可能被重置/手工推进绕过闸门。在 `_ensure_fix_spec_files` 内再做一次存在性校验 + 兜底，使不变量不依赖调用顺序假设。

## Risks / Trade-offs

- 合成报告比 Agent 手写的叙述更「干」——可接受，内容以结构化 JSON 为准，且发生时伴随告警。
- `[REAL PRODUCT BUGS]` 等章节标记需与现行 Dashboard 解析（`dashboard/data.py` 对 verification-report.md 的解析）兼容——实现前须核对解析函数的期望格式，以解析器可读为准。
- 极端场景（结构化数据全缺失）走 fail-closed，SPEC 滞留 + 人工告警，与既有 verification-completion-gate 语义一致。

## Migration Plan

纯增量：不改既有数据格式、不改状态机。上线后历史 SPEC 若缺报告，只会在其下次进入裁决/派生路径时被兜底，不回溯补写。

## Open Questions

无。
