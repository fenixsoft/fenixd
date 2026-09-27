<!-- knowledge: capability=deliverable-dispute-governance rev=1 sources=spec/archive/2026-09-23-evo-deliverable-dispute-orphan-preclassify -->

# 交付物争议孤儿声明治理

实现者对缺件提出 dispute 异议时的机械预分类：确证为「孤儿声明」（声明残留、无任何交付需求证据）的直接机械删除续走，其余维持人工裁决。

## 现行规则

- 引用面判定口径：引用面用 `git grep` 扫描 tracked 文件，以负向 pathspec magic（`:!`）显式排除 `.fenix/**`（自省报告/admin 记录/STATE/todo.md 是观测面，非引用面）、`spec/changes/<本 spec>/**`（声明行自身）、`.history/**`、`dist/**`——形如 `git grep -n -F <path> -- ':!.fenix/**' ':!spec/changes/<本 spec>/**' ':!.history/**' ':!dist/**'`。不得写包含语义 pathspec（该写法只在被排除面上搜索、恒零命中，会把一切缺件误判为孤儿并机械删除）；不得用裸 `grep -rn` 扫工作树（运行时报产物巨大，实测 >120s 未完成，会卡死同步调用）。
- 按 kind 分化的判据：`kind: new` 不查历史（新建文件本义即历史未出现，零信息量）；`kind: modify` 的历史判据用路径限定 `git log --all --oneline -- <path>`，不用 pickaxe `-S <path>`（`-S` 匹配文本内容，会把「提到」该词的记账提交误判为引用）；「任务清单零出现」同时比对声明路径及其 basename（任务行文本任一命中即视为有交付需求、非孤儿）。
- 孤儿判定与处置：`kind: new` 源码面零引用且任务清单零出现、或 `kind: modify` 源码面零引用且路径限定历史零命中且任务清单零出现 → 判孤儿声明，机械删除声明并写审计（DisputeAuditStore，`verdict=orphan-preclassify`），不置 spec 为 blocked 待人工。
- 删除后续走（guard-preclassify 范式）：删除仅限声明段该条的 path+kind 两行并留 `.history` 备份；改写的 tasks.md 立即提交（未提交的 spec 文件不被 merge-back 的 autostash 排除，会使 merge 被 git 拒绝并冻结 spec）；重跑交付物收工守卫，全清则置 `implementing` 并放行 merge；仍有缺件则以重跑结果续走既有后续处置（仍带 dispute 异议 → blocked 待人工；无异议 → 既有 LLM 终审）；判定/改写/提交任一环节异常全量回退既有 blocked 待人工路径（fail-open）。
- 非孤儿形态维持人工：basename 多命中、语境等价、运行时产物、`kind: modify` 历史命中疑似漂移等任一引用存在时，维持既有 blocked 待人工裁决通道，不机械删除。`kind: delete` 不参与孤儿预分类（一律进人工裁决）。
- 晋升期孤儿检查：`lint_declared` 对 `kind: new` 声明增加孤儿检查——声明路径在 tasks.md 任务清单文本（全路径与 basename）零出现且源码面（`git grep`，覆盖范围与负向 pathspec 写法同裁决通道）零引用时，报错拒绝晋升（spec 停留 drafted + error 附孤儿判定证据）。该检查只覆盖 basename 模糊匹配规则原本放行的「basename 零命中」形态：basename 多命中沿用既有规则 fail-open 放行、孤儿检查不触发；basename 唯一命中仍由既有规则拦截；lint 自身故障保持 fail-open（返回空清单放行晋升）。

## 溯源

- 2026-09-23 2026-09-23-evo-deliverable-dispute-orphan-preclassify — 确立孤儿判定口径（负向 pathspec 引用面、kind 分化历史判据、basename 比对）、机械删除续走范式与晋升期 lint 孤儿检查
