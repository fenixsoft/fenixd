# 验证报告：evo-deliverable-dispute-orphan-preclassify

> ⚠️ 本报告由框架于 2026-09-18T12:34:23Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-18T12:34:23.641977+00:00

## 结论：✅ 通过（verified）

**状态：verified — 19/19 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 19/19 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 19 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.86M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| orphan-new-zero-ref-is-orphan | is_orphan_declaration: kind: new 零引用（源码面 git grep 零 + tasks.md 全路径/basename 零出现）→ orphan=True（规则1+3 合成） | pass | 0/2 | - |
| orphan-new-task-fullpath-mention | is_orphan_declaration: kind: new 任务清单含全路径 → 非孤儿（规则3 命中，任务行是交付需求第一语义位） | pass | 0/2 | - |
| orphan-new-basename-only-mention | is_orphan_declaration: kind: new 任务清单仅 basename 提及 → 非孤儿（basename 计入规则3，add-architect-agent 实测反例） | pass | 0/2 | - |
| orphan-new-source-ref-not-orphan | is_orphan_declaration: kind: new 源码面 tracked 文件引用 → 非孤儿（规则1 命中） | pass | 0/2 | - |
| orphan-modify-history-hit-not-orphan | is_orphan_declaration: kind: modify git log --all -- 命中（路径曾存在，疑似拆包/改名漂移）→ 非孤儿（规则2 命中，走人工） | pass | 0/2 | - |
| orphan-modify-no-history-is-orphan | is_orphan_declaration: kind: modify 路径历史零命中 + 源码零引用 + 任务零出现 → 孤儿（规则1+2+3 合成） | pass | 0/2 | - |
| orphan-delete-never-classified | is_orphan_declaration: kind: delete 不参与孤儿预分类 → 恒非孤儿（防洗白，一律人工裁决） | pass | 0/2 | - |
| exclusion-fenix-mention-still-orphan | 排除面验证：仅 .fenix/todo.md 记账面提及 → 仍判孤儿（观测面不计引用，负向 pathspec :!.fenix/** 生效） | pass | 0/2 | - |
| exclusion-tracked-file-not-orphan | 排除面反向验证：排除面之外 tracked 文件引用 → 非孤儿（负向 pathspec 未误写成包含语义，防恒零命中回归） | pass | 0/2 | - |
| remove-entry-exact-target-only | remove_declared_entry: 仅删除目标 path+kind 两行，保留其余声明条目与任务文本，diff.before/after 留痕 | pass | 0/2 | - |
| lint-orphan-blocks-promotion | lint_declared 规则11：kind: new 孤儿声明（主树不存在+任务零出现+源码零引用）→ 报错含孤儿证据，拒绝晋升 | pass | 0/2 | - |
| lint-normal-passes | lint_declared：正常声明（modify 路径存在 + new 任务提及）→ 零违规放行 | pass | 0/2 | - |
| preclassify-orphan-deleted-gate-clear | _preclassify_orphan 集成：kind: new 孤儿 → 机械删除+tasks.md已提交+审计留痕+重跑守卫全清 → action=proceed，spec 不 blocked 放行 merge | pass | 0/4 | - |
| preclassify-non-orphan-fallback | _preclassify_orphan 集成：存在源码引用/任务提及的缺件 → 非孤儿 → action=fallback，维持 blocked 待人工 | pass | 0/3 | - |
| preclassify-delete-not-participating | _preclassify_orphan 集成：kind: delete 不参与预分类 → action=fallback，维持 blocked | pass | 0/2 | - |
| preclassify-exception-fallback | _preclassify_orphan 集成：判定/删除/守卫重跑异常 → action=fallback 全量回退 blocked（fail-open） | pass | 0/4 | - |
| preclassify-continuation-still-missing | _preclassify_orphan 续走契约：删除孤儿后重跑守卫仍有缺件 → action=continue，remaining 续走既有终审/blocked | pass | 0/3 | - |
| full-regression-suite | test_deliverable_orphan_preclassify.py 全量回归：33 passed（覆盖孤儿判定/排除面/删除/审计/lint/续走契约/异常回退） | pass | 0/2 | - |
| affected-suites-regression | 受影响存量测试零回归：test_deliverable_gate + test_tasksmd_relint_gate + test_deliverable_declaration_premechanize + test_deliverable_declaration_triage | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 19 个（第 1 轮）。

- 首轮写入 19 个场景

