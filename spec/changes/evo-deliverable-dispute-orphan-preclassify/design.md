# Design: deliverable-dispute-orphan-preclassify

## 背景与目标

refactor-giant-classes（2026-09-17）事故：孤儿交付物声明 `tests/test_giant_classes_contract.py` 触发交付物守卫缺件 → 实现者 dispute 异议 → blocked 待人工裁决，空转 76 分钟 + 44 分钟 admin 处置。目标：让「零引用」的孤儿声明不再占用人工裁决通道；让孤儿声明在晋升期即暴露。

## 孤儿判定

判定按声明 `kind` 分化——查询工具与覆盖范围各异。原「三条一律 AND」的设计有两处工具误用（裸 grep 扫全树、pickaxe 判历史），且历史判据对 `kind: new` 零信息量。

### 共同覆盖范围（引用面 vs 观测面）

引用面 = tracked 文件中除框架记账面以外的部分，用 `git grep`（只扫 tracked 文件，天然排除 `.fenix/verify-serving` 等未跟踪运行时报产物），并以 pathspec 显式排除：

- `.fenix/**`——自省报告、admin 处置记录、STATE、`todo.md` 是**观测面**而非引用面。一条孤儿声明一旦被写进自省报告，文本匹配即出现非零命中，把判定反向污染（本次事故的路径在事故后被 todo.md 记录，`-S` 命中数由 1 变 4，其中 2 条纯属「提到」）；
- `spec/changes/<本 spec>/**`——声明行自身所在面，自引用不计（声明路径必然在本文档出现，须排除以免自证非孤儿）；
- `.history/**`、`dist/**` 等产物目录。

### 规则 1 — 源码面零引用

`git grep -n -F <path> -- ':!.fenix/**' ':!spec/changes/<本 spec>/**' ':!.history/**' ':!dist/**'` 零命中。

> **路径规格必须写负向 magic（`:!`）**：`git grep <pattern> -- <pathspec>` 的 pathspec 是**包含**语义，写作 `-- '.fenix/**' 'spec/changes/<本 spec>/**'` 会只在被排除的两个面上搜索——恰好恒零命中，等于把所有缺件都判成孤儿并机械删除。排除面一律写成 `':!<glob>'`（实测本命令全仓 0.012s，`git grep` 只扫 tracked 文件，`-F` 关闭正则以免路径中 `[]()` 等元字符被解释）。

原设计用 `grep -rn <path> --include=* .`：本仓库工作树 35G、`.fenix/verify-serving` 单项 30G，该命令**实测 >120s 未跑完**（晋升期 daemon 同步调用，直接卡住晋升）；`--include=*` 未加引号时 `*` 被 shell 展开而非作为过滤器，形同失效。`git grep` 同语义实测 0.018s。

### 规则 2 — 历史判据（按 kind 分化）

- **`kind: new`：不查历史。** 新建文件的本义即「主树不存在且历史未出现过」，全历史查询对 new 零信息量——合法 new 声明天然全部命中「历史零出现」，该判据在 new 上只贡献成本与假信号。原 `git log --all -S <path>`（pickaxe）匹配的是**文本内容**而非「该路径曾作为文件存在」，会命中任何**提到**该词的提交（自省报告、admin 记录），把观测面污染成引用面，令判定结果随记录行为翻转。
- **`kind: modify`：`git log --all --oneline -- <path>`（路径限定，非 pickaxe）判定。** 命中非空 = 该路径**曾作为文件存在过**，缺失更可能是拆包/改名**漂移**（本仓库高频真实形态：`core/dashboard/data.py`、`core/pm_engine/dispatch.py`、`verification.py`、`core/worktree_manager.py` 均被 refactor 拆分/改名后删除）→ 走人工，不判孤儿；零命中 = 从未作为文件存在过 → 进入孤儿判定。路径限定语义走 tree diff，实测 0.015s（pickaxe 同查询 2.2s，且语义错）。

### 规则 3 — 任务清单零出现

tasks.md 全部任务行（`- [ ]` / `- [x]` 开头）文本不含该路径**及其 basename**（末段文件名）。任务行是交付需求的第一语义位，判别力最强——抽样 `fix-impl-resultfile-contract-gap` / `add-deliverable-delete-kind` / `evo-stuck-signal-hygiene` 三个正常 spec，首组任务行均逐字点名了 Deliverables 声明路径。

> **basename 计入的理由（实测）**：全仓 kind: new 且主树不存在的声明共 17 条，其中 `spec/archive/add-architect-agent-1789628607` 的 `core/dashboard/static/src/pages/settings/components/ArchitectPanel.tsx` 任务行 4.3 只写 basename（`新增 ArchitectPanel.tsx 并在「自进化」页签挂载`，tasks.md:75），全路径零命中——只认全路径会把这条**非孤儿**声明误拦在晋升门外（同族还有 4 条 `docs/help/*.md` 仅靠规则 1 命中才未误拦）。basename 命中只让判定更保守（回退人工，不误删）。事故案的 basename 在其 spec 任务行命中 0 次（40 条任务行全零），放宽后检出能力不减。

### 判定合成

| kind | 判定 = 孤儿（机械删除声明）的条件 |
|------|-----------------------------------|
| `new` | 规则 1 零命中 **AND** 规则 3 全零 |
| `modify` | 规则 1 零命中 **AND** 规则 2 零命中 **AND** 规则 3 全零 |
| `delete` | **不参与孤儿预分类**（add-deliverable-delete-kind D4 防洗白：delete 声明一律进人工裁决） |

任一规则有命中 → 非孤儿 → 维持 blocked 待人工裁决（宁可多走人工，不误删真实交付物）。

## 机械预分类在裁决链中的位置

现有裁决链（core/pm_engine/dispatch/queue.py:796-820；`_disputed_deliverables` 调用在 802 行、blocked 分支 806-820）：缺件 → 实现者异议检查（_disputed_deliverables，定义见 core/pm_engine/verification/branch_guard.py:303）→ 异议命中 → blocked 待人工；异议未命中 → _adjudicate_deliverable_missing LLM 终审（typo/reference/missing/unclear）。

本变更在「异议命中」分支内插入预分类：先跑按 kind 分化的孤儿判定，孤儿 → 机械删除 + 审计，不 blocked；非孤儿 → 维持 blocked 待人工。对齐 add-declaration-premechanize 的 guard-preclassify 范式（core/pm_engine/dispatch/adjudication.py:295 `_preclassify_missing`）。

### 删除后的续走契约（对齐 `_preclassify_missing` 的 proceed 分支）

「机械删除后随即怎样」是本次改动的关键实现位，MUST 与既有范式逐条对齐，不得写成「删完 return」或「删完置 blocked」：

1. **删声明**：改写主树 `spec/changes/<本 spec>/tasks.md` 的声明段（只删该条的 path+kind 两行，其余内容不动），并留 `.history` 备份；
2. **立即提交**：改写后 MUST 立即提交该 tasks.md（同 `_commit_softened_declaration`，adjudication.py:257-273 的 fix-merge-back-deadlock 教训）——主树 spec 文件被 merge-back 的 autostash 显式排除，残留 dirty 会让「主树改了 tasks.md + 实现分支也改了 tasks.md」的 merge 被 git 拒绝，spec 被 merge 指纹熔断冻结 blocked（2026-09-15 事故原形）。提交失败仅 WARNING，交派发前 `ensure_spec_committed` 兜底；
3. **重跑守卫对账**：删除后以重跑 `_deliverable_gate_missing(spec_name, result)` 的结果替换 `missing`；全清 → `status=implementing` + `error=None` + `{"action":"proceed"}`（对齐 `_preclassify_missing` 全清分支），放行 merge；
4. **仍有缺件**：把重跑后的 remaining 作为新的 `missing` 续走既有后续代码（剩余项仍带 dispute 异议 → 维持 blocked 待人工；无异议项 → 既有 `_adjudicate_deliverable_missing` LLM 终审），不得因「已判过一批孤儿」就整段跳过；
5. **异常回退**：判定/改写/提交任一环节异常 → 全量回退既有 blocked 待人工路径（fail-open，不因预分类故障改变处置）。

## 审计

DisputeAuditStore（core/admin_store.py:582 `DisputeAuditStore`，落 `.fenix/dispute_audits.jsonl`）追加条目，字段沿用既有约定（`spec` / `trigger_run_id` / `judge_run_id` / `verdicts` / `diff`）：`verdicts` 逐元素载 `{"element": <缺件路径>, "verdict": "orphan-preclassify", "reasoning": "orphan-preclassify: <各规则零引用证据摘要>"}`，`judge_run_id` 置空串（本路径无 judge run），`diff` 记删除声明前后文本。`DisputeAuditStore.append` 为自由字段追加、无 schema 校验（admin_store.py:601-618），新增 verdict 取值不破坏既有消费者（全仓除 `admin_store.py` 外无 `dispute_audits` 读取方）。

## lint_declared 增强

core/deliverables.py lint_declared（core/deliverables.py:774，规则 4 即既有 basename 模糊匹配）新增规则：kind: new 声明在主树不存在时，在规则 4 之后增加孤儿判定——规则 1（源码面 `git grep` 零命中，负向 pathspec 写法同规则 1）+ 规则 3（任务清单全路径与 basename 皆零出现）同时成立即命中；命中 → 报错附孤儿证据（声明行位置、任务清单搜索、git grep 结果摘要），拒绝晋升。kind: new 不查历史（规则 2 分化结论同上）。

> **与规则 4 的边界（MUST 写清，否则与新测试互斥）**：basename 在仓库内**多命中**时沿用规则 4 的 fail-open 放行（语义矛盾需 LLM 裁决，lint 只拦确定性形态），孤儿检查不触发；basename **唯一命中**已由规则 4 拦截；孤儿检查覆盖的是规则 4 原本放行的「basename 零命中」形态。三者合起来 = 主树不存在 + basename 零命中 + 任务清单全路径与 basename 皆零出现 + 源码面零引用 → 拦；其余一律放行。规则 1 的实现需以 `project_root` 为 cwd（`git -C <project_root> grep …`），lint 自身故障仍 fail-open（返回空清单放行晋升）。

## 边界

- 不预分类：basename 多命中（同目录/异目录同名文件）、语境等价（旧名 vs 新名）、运行时产物路径——仍需语义判断，走人工。
- kind: modify 历史命中（路径曾存在，疑似漂移）不在 lint 期机械删除；lint 期仅对 kind: new 做孤儿拦截（modify 缺件本就由规则 3 存在性校验报错），漂移处置留在裁决通道。
- 机械删除只删声明行（tasks.md ## Deliverables 段的 path+kind 两行），不动其他内容；删除前备份留痕（对齐 admin 处置 .history 备份惯例）。

## 回归测试

tests/test_deliverable_orphan_preclassify.py：

1. kind: new 三方（规则 1/3）零引用 → 机械删除 + 审计留痕 + spec 不 blocked；
2. 存在任一引用 → 维持 blocked 待人工；
3. kind: modify 规则 2 命中（`git log --all -- <path>` 非空，路径历史存在过）→ 非孤儿，维持人工裁决；
4. kind: delete → 不参与预分类；
5. 排除面用例：仅 .fenix 记账面（todo.md/admin 记录）命中 → 仍判孤儿（观测面不算引用）；
6. lint_declared 孤儿检查：kind: new 孤儿拒绝晋升、正常声明放行、basename 多命中放行。