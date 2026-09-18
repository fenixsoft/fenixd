# Proposal: deliverable-dispute-orphan-preclassify

## Why

2026-09-17 refactor-giant-classes 事故：spec 立项时声明了一条从未被任务要求创建的交付物 `tests/test_giant_classes_contract.py`（孤儿声明），实现完成后交付物守卫按分支 HEAD 对账缺件，实现者提出 deliverable-dispute 异议，守卫「质疑不得自动放行」置 blocked 待人工裁决——而「源码面零引用 + 任务清单零出现」本可由机械规则判定。后果：已 37/37 任务完工的 spec 空转约 76 分钟、下游依赖 spec 每轮巡检被拒、另耗 44 分钟 admin 人工裁决（处置记录 admin_disposition-admin-refactor-giant-classes-1789664978.json）。

根因：dispute 裁决通道（core/pm_engine/dispatch/queue.py 缺件异议分支）无孤儿声明的机械预分类出口——缺件异议一律进人工裁决；晋升期 lint_declared（core/deliverables.py 规则 4）对 kind: new 声明只做 basename 模糊匹配、零命中即放行，拦不住「任务清单零出现 + 源码面零引用」的孤儿形态。

## What Changes

- **dispute 裁决通道补孤儿声明机械预分类**：缺件路径经按 kind 分化的孤儿判定——kind: new 看「源码面 `git grep` 零引用 + tasks.md 任务文本零出现」，kind: modify 另加「路径限定历史（`git log --all -- <path>`）零命中」——判定为孤儿声明（声明残留）时，直接机械删除声明并留审计（DisputeAuditStore 追加 verdict=orphan-preclassify），spec 不进 blocked、直接走既有恢复路径；人工裁决只留给真正需要语义判断的争议（basename 多命中、语境等价、运行时产物、kind: modify 的路径漂移）。
- **晋升期 lint_declared 孤儿检查**：kind: new 声明在任务清单文本零出现且源码面（`git grep`）零引用时，晋升（drafted → ready）期即报错拦截，让孤儿声明在立项当下暴露，不再等到收工守卫才发现。

## Capabilities

### New Capabilities

- `deliverable-dispute-governance`: 交付物 dispute 裁决通道的孤儿声明机械预分类 + 晋升期 lint_declared 孤儿声明检查。