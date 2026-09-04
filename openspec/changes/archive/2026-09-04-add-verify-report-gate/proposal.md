# Proposal: add-verify-report-gate

## Why

验证裁决 Agent 被要求在结论之外写入人类可读的 `openspec/changes/<spec>/verification-report.md`（prompt Step 5），但该步骤无任何结构化闸门校验。实际事故（v2-shell-hash-router，2026-08-29）：裁决 Agent 返回 `bug-found` 且 `.fenix-run-result.json` 中根因分析完整，却未写报告文件；`pm_engine._ensure_fix_spec_files` 随后生成的 fix SPEC 盲目引用了不存在的路径，implementer 只能从第一性原理重新诊断（worktree 中留下 6 个探针页面、24+ 分钟的重复 token 消耗），fix SPEC 的输入契约实际断裂。

## What Changes

- 新增**验证报告产物闸门**：验证裁决放行（verified / bug-found 被采纳）前，框架 MUST 校验 spec 目录下存在 `verification-report.md`；缺失时由框架从结构化数据（`report.json` + `.fenix-run-result.json`）确定性合成该报告并告警，不重跑验证。
- 不变量：**任何被修复任务引用的 `verification-report.md` 必然存在**——要么由裁决 Agent 写入（优先，不覆盖），要么由框架合成。
- ~~fix 派生入口校验~~：原规划的 `_ensure_fix_spec_files` 前置校验不再需要——闸门在裁决采纳时点先行兜底，派生发生在其后，正常流中校验恒为 no-op；且 add-inplace-bug-repair（depends_on 本 SPEC）将退役 fix 派生路径，避免为先建后删的代码立项。

## Capabilities

### New Capabilities
- `verify-report-gate`: 校验并兜底保障 verification-report.md 产物完整性的闸门与合成器，作用于验证裁决放行入口。

### Modified Capabilities
<!-- 无。verification-completion-gate（improve-verify-adjudication）只裁决 report.json 场景结论，
     不涉及本变更管的人读 Markdown 产物；两者互补，不修改其既有 Requirements。 -->

## Impact

- **代码**：`.fenix/core/`（裁决放行路径、新增共享合成 helper）
- **行为**：裁决 Agent 漏写报告不再导致下游修复任务引用断裂；修复 implementer 拿到的引用必然可读
- **成本**：消除「implementer 重复诊断」一类 token 浪费（本事故实测 24+ 分钟 agent 运行时间）
- **风险**：合成报告为结构化 JSON 的忠实渲染，不含 Agent 的额外叙述；已通过告警提示人工留意
