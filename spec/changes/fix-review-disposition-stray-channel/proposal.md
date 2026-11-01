# 评审处置留痕落点治理与散件 gitignore 草案误伤交付物目录

## Why

spec-review run 会把处置留痕物化进主树 spec/changes/<name>/（3bf67a 实证），随即触发 untracked 散件告警；而散件盘点自动起草的 gitignore 草案把 spec/changes 交付物目录归类为「运行时产物目录」建议 ignore（admin_alerts L2836 实证）——若被采纳将永久遮蔽正常 spec 交付物。建议：处置留痕落点迁至 .fenix/spec-review/<name>/（评审结果文件已在该处）或按 _materialize_proposal 同款 best-effort 提交；散件盘点的 gitignore 草案生成器须排除 spec/ 交付物路径。

## What Changes

- （arbiter 提案待人工成文：本文件为调查报告提案的最小诚实成文，补全 What Changes / Capabilities / Impact 后走既有晋升流程）

## Capabilities

### New Capabilities

- `<capability>`: （待成文）

### Modified Capabilities

（无）

## Impact

（待成文）

---

- 立项来源：Arbiter 调查（run_id=None，signature=fix-arbiter-proposal-materialize-spec-dir::spec-review-rejected，source=escalation-alert）
- 立项时间：2026-11-01T01:22:50.719598+00:00
