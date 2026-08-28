# Proposal: 修复 fix-improve-run-lifecycle-governance 验证发现的缺陷

## Why

`fix-improve-run-lifecycle-governance` 的验证报告（见 `openspec/changes/fix-improve-run-lifecycle-governance/verification-report.md`）结论为「无真实产品 Bug」：17 场景中 2 通过 / 15 失败，15 例失败全部为验证脚手架 mock 层未注入场景专用治理固件所致（伪失败），非 fenixd 产品缺陷。父 SPEC 已据此在 `a6f44ea` / `be482f0` 完成根因分析并闭环。

## What Changes

本 SPEC 是 daemon 依据父 SPEC 陈旧的 `bug-found` 状态派生出的**伪派生 SPEC**：其父级已在实现合入后判定「无真实产品 Bug（伪失败排除）」，故派生链在此断裂，**范围内无真实产品缺陷可修复**。

实现者已复核父 SPEC 验证报告与结论，确认：
- 后端过滤正确（56 条真实 spec 来自项目 59 个 SPEC），dashboard 渲染层健康，全部 17 场景 `no_console_error` 通过；
- 治理可观察数据（`governance-*` 行、`recovery deferred` / `backoff until` / `dispatch_stalled` / `liveness judge unavailable` 文本）缺失系验证 mock 未注入场景固件，属验证基础设施缺陷，依父子两级 proposal.md 界定不在本 fix SPEC 范围。

故本 SPEC **不做任何产品代码改动**，仅以根因分析结论闭环，与父 SPEC 的处理方式一致。

## Impact

- **代码**：无（范围内无真实产品缺陷）
- **行为**：无变化；父 SPEC 验证报告中失败的场景需在验证脚手架补注入治理固件后重跑方可真正覆盖，属验证基础设施范畴，不在本 SPEC 范围
