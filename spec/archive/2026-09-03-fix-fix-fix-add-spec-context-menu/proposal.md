# Proposal: 修复 add-spec-context-menu 验证发现的缺陷

## Why

`add-spec-context-menu` 的验证报告发现产品缺陷，导致验证未通过。详见 `openspec/changes/add-spec-context-menu/verification-report.md` 的「真实产品 Bug」部分。

## What Changes

修复验证报告中列出的真实产品缺陷。实现者应先阅读父 SPEC 的 `verification-report.md`，定位每个真实产品 Bug 的根因并修复；伪失败（测试框架/场景缺陷）不在本 SPEC 修复范围内。

## Impact

- **代码**：按验证报告修复真实产品缺陷
- **行为**：修复后，父 SPEC 验证报告中失败的场景应转为通过

## 根因结论（实现者复核 2026-08-29）

本 change 的 `verification-report.md`（2026-08-28T16:30:39Z，1 通过 / 19 失败）所列两个「真实产品 Bug」经实测复核**均为验证编排伪失败，产品代码无缺陷**，未做任何产品代码改动：

1. **时间线证据**：报告生成于 00:30，但冻结场景 `verify-progress/fix-fix-fix-add-spec-context-menu/test_scenarios.json` 在 01:33 才补上 `/api/overview`（注释明确「概览页卡片数据源 mock（cards 由 /api/overview 渲染，非 /api/projects）」）与 `/api/spec-doc*` 两个 mock。报告的 `step_results` 仅记录了 2 个 mock 步骤，证实其运行时用的是过期场景。
2. **失败机理**：缺 `/api/overview` mock 时概览页渲染真实 fenixd 项目卡片（65 个 spec），场景点击 `.card` 进入的是真实项目而非 mock 的 testproject → `.spec-name-cell[data-spec='live-spec']` 永不出现（Bug #1，17 个场景）；真实项目有 spec → `.spec-table` 存在、无空状态（Bug #2）。与上一轮 fix-fix 报告的 SSE 覆盖伪失败同型。
3. **实测复核**：用修正后的冻结场景经 VerifyEngine 完整重跑 20 个场景，**20/20 通过**（报告落盘于 `verify-progress/impl-scratch-ctxmenu-repro/`），右键菜单、空状态、删除/优先级/Admin 唤起的 409/500 分支全部符合预期；`core/`（含 app.js）与运行时副本逐字节一致。

冻结场景的修正已由 admin 于 01:33 落盘，本实现者未再改动验证基础设施。
