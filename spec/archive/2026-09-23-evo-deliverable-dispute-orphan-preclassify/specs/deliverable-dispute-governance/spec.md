# deliverable-dispute-governance

## ADDED Requirements

### Requirement: dispute 裁决通道孤儿声明机械预分类

交付物守卫缺件且实现者提出 deliverable-dispute 异议时，缺件路径 MUST 先经孤儿声明机械预分类。判定按声明 kind 分化：

- 引用面 MUST 用 `git grep` 扫描 tracked 文件，MUST 以**负向 pathspec magic（`:!`）**显式排除 `.fenix/**`（自省报告/admin 记录/STATE/todo.md 是观测面，非引用面）、`spec/changes/<本 spec>/**`（声明行自身）、`.history/**`、`dist/**`，即 `git grep -n -F <path> -- ':!.fenix/**' ':!spec/changes/<本 spec>/**' ':!.history/**' ':!dist/**'`；MUST NOT 写 `-- '.fenix/**' 'spec/changes/<本 spec>/**'`（pathspec 为包含语义，该写法只在被排除面上搜索、恒零命中，会把一切缺件误判为孤儿并机械删除）；MUST NOT 用裸 `grep -rn` 扫工作树（本仓库工作树含 30G 运行时报产物，实测 >120s 未完成，晋升期同步调用会卡住晋升）。
- `kind: new` MUST NOT 查历史——新建文件本义即历史未出现，该判据零信息量。
- `kind: modify` 的历史判据 MUST 用路径限定 `git log --all --oneline -- <path>`，MUST NOT 用 pickaxe `-S <path>`（`-S` 匹配文本内容，会把「提到」该词的记账提交误判为引用）。
- 「任务清单零出现」MUST 同时比对声明路径**及其 basename**（任务行 `- [ ]`/`- [x]` 文本），任一命中即视为有交付需求、非孤儿（实测 `add-architect-agent-1789628607` 的任务行只写 basename `ArchitectPanel.tsx`，只认全路径会误拦非孤儿声明）。

判定为「孤儿声明（声明残留）」（kind: new：源码面零引用 AND 任务清单零出现；kind: modify：源码面零引用 AND 路径限定历史零命中 AND 任务清单零出现）时，MUST 机械删除声明并写审计（DisputeAuditStore，`verdicts` 内 `verdict=orphan-preclassify`），MUST NOT 置 spec 为 blocked 待人工裁决。

删除后 MUST 按既有 guard-preclassify 范式续走，MUST NOT 以「已删除」直接结束本轮处置：①删除仅限声明段该条的 path+kind 两行并留 `.history` 备份；②改写的 tasks.md MUST 立即提交（未提交的 spec 文件不被 merge-back 的 autostash 排除，会使 merge 被 git 拒绝并冻结 spec）；③重跑 `_deliverable_gate_missing`，全清则置 `implementing` 并放行 merge；④仍有缺件则以重跑结果续走既有后续处置（仍带 dispute 异议 → blocked 待人工；无异议 → 既有 LLM 终审）；⑤判定/改写/提交任一环节异常 MUST 全量回退既有 blocked 待人工路径（fail-open）。

非孤儿形态（basename 多命中、语境等价、运行时产物、kind: modify 历史命中疑似漂移等任一引用存在）MUST 维持既有 blocked 待人工裁决通道。`kind: delete` MUST NOT 参与孤儿预分类（一律进人工裁决）。

#### Scenario: kind: new 零引用的孤儿声明直接清除

- **WHEN** 交付物守卫缺件、实现者已提 dispute 异议，缺件声明为 `kind: new` 且源码面 `git grep` 零命中、任务清单零出现
- **THEN** 声明被机械删除、审计留痕，spec 不进入 blocked，恢复路径继续

#### Scenario: 删除后重跑守卫全清放行 merge

- **WHEN** 孤儿声明被机械删除（主树 tasks.md 已提交）
- **THEN** 重跑 `_deliverable_gate_missing` 无缺件，spec 置 `implementing` 并放行 merge，不因 tasks.md dirty 触发 merge 失败熔断；若重跑仍有缺件，则以重跑结果续走既有后续处置（仍带异议 → blocked 待人工；无异议 → 既有 LLM 终审）

#### Scenario: 任务行只写 basename 时不判孤儿

- **WHEN** `kind: new` 声明路径主树不存在，但 tasks.md 任务行含该路径的 basename（未含全路径），且源码面全路径零引用
- **THEN** 视为有交付需求，非孤儿，lint 与裁决通道均不机械删除

#### Scenario: kind: modify 历史零命中方可判孤儿

- **WHEN** 缺件声明为 `kind: modify`，源码面零引用、任务清单零出现，且 `git log --all -- <path>` 零命中（该路径从未作为文件存在过）
- **THEN** 判为孤儿，声明被机械删除、审计留痕

#### Scenario: kind: modify 历史命中维持人工裁决

- **WHEN** 缺件声明为 `kind: modify`，`git log --all -- <path>` 非空（该路径曾作为文件存在、疑似拆包/改名漂移）
- **THEN** 维持既有 blocked 待人工裁决，不机械删除

#### Scenario: 记账面提及不构成引用

- **WHEN** 缺件路径仅在 `.fenix/todo.md` 自省报告或 admin 处置记录中被文本提及，源码面 `git grep` 零命中
- **THEN** 该提及不计为引用，仍判孤儿

#### Scenario: 存在引用的缺件仍走人工裁决

- **WHEN** 缺件路径存在任一引用（如 basename 多命中、语境等价、运行时产物）
- **THEN** 维持既有 blocked 待人工裁决，不机械删除

### Requirement: 晋升期 lint_declared 孤儿声明检查

`lint_declared` MUST 对 kind: new 声明增加孤儿检查：声明路径在 tasks.md 任务清单文本（全路径与 basename 皆）零出现且源码面（`git grep`，覆盖范围与负向 pathspec 写法同裁决通道）零引用时，MUST 报错拒绝晋升（spec 停留 drafted + error 提示），拦截孤儿声明进入实现链。kind: new MUST NOT 查历史（同上分化结论）。该检查 MUST 只覆盖既有 basename 模糊匹配规则（lint 规则 4）原本放行的「basename 零命中」形态：basename 在仓库内多命中时 MUST 沿用规则 4 的 fail-open 放行、孤儿检查不触发；basename 唯一命中仍由规则 4 拦截；lint 自身故障 MUST 保持 fail-open（返回空清单放行晋升）。

#### Scenario: 孤儿声明晋升被拦

- **WHEN** spec 的 Deliverables 声明了主树不存在的 kind: new 路径，且该路径在任务清单零出现、源码面零引用
- **THEN** lint_declared 报错，spec 停留 drafted 并附孤儿判定证据

#### Scenario: 正常新建声明放行

- **WHEN** kind: new 声明路径在任务清单出现或被仓库引用
- **THEN** lint_declared 放行