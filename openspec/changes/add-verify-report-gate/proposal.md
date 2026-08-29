# Proposal: add-verify-report-gate

## Why

验证裁决 Agent 被要求在结论之外写入人类可读的 `openspec/changes/<spec>/verification-report.md`（prompt Step 5），但该步骤无任何结构化闸门校验。实际事故（v2-shell-hash-router，2026-08-29）：裁决 Agent 返回 `bug-found` 且 `.fenix-run-result.json` 中根因分析完整，却未写报告文件；`pm_engine._ensure_fix_spec_files` 随后生成的 fix SPEC 盲目引用了不存在的路径，implementer 只能从第一性原理重新诊断（worktree 中留下 6 个探针页面、24+ 分钟的重复 token 消耗），fix SPEC 的输入契约实际断裂。

## What Changes

- 新增**验证报告产物闸门**：验证裁决放行（verified / bug-found 被采纳）前，框架 MUST 校验 spec 目录下存在 `verification-report.md`；缺失时由框架从结构化数据（`report.json` + `.fenix-run-result.json`）确定性合成该报告并告警，不重跑验证。
- 新增**fix 派生输入校验**：`_ensure_fix_spec_files` 生成 fix SPEC 的 proposal/tasks 引用父 SPEC 报告路径前，MUST 校验该文件存在；缺失时先触发同一合成兜底，保证「fix SPEC 派生时父报告必然在磁盘上」这一不变量。
- 不变量：**任何被 fix SPEC 引用的 `verification-report.md` 必然存在**——要么由裁决 Agent 写入（优先，不覆盖），要么由框架合成。

## Capabilities

### New Capabilities
- `verify-report-gate`: 校验并兜底保障 verification-report.md 产物完整性的闸门与合成器，覆盖验证裁决放行与 fix SPEC 派生两个入口。

### Modified Capabilities
<!-- 无。verification-completion-gate（improve-verify-adjudication）只裁决 report.json 场景结论，
     不涉及本变更管的人读 Markdown 产物；两者互补，不修改其既有 Requirements。 -->

## Impact

- **代码**：`.fenix/core/`（裁决放行路径、`pm_engine._ensure_fix_spec_files`、新增共享合成 helper）
- **行为**：裁决 Agent 漏写报告不再导致 fix SPEC 引用断裂；fix implementer 拿到的任务引用必然可读
- **成本**：消除「implementer 重复诊断」一类 token 浪费（本事故实测 24+ 分钟 agent 运行时间）
- **风险**：合成报告为结构化 JSON 的忠实渲染，不含 Agent 的额外叙述；已通过告警提示人工留意
