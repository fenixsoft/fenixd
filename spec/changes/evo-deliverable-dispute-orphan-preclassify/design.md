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

`git grep -n <path> -- '.fenix/**' 'spec/changes/<本 spec>/**'`（pathspec 取反语义）零命中。

原设计用 `grep -rn <path> --include=* .`：本仓库工作树 35G、`.fenix/verify-serving` 单项 30G，该命令**实测 >120s 未跑完**（晋升期 daemon 同步调用，直接卡住晋升）；`--include=*` 未加引号时 `*` 被 shell 展开而非作为过滤器，形同失效。`git grep` 同语义实测 0.018s。

### 规则 2 — 历史判据（按 kind 分化）

- **`kind: new`：不查历史。** 新建文件的本义即「主树不存在且历史未出现过」，全历史查询对 new 零信息量——合法 new 声明天然全部命中「历史零出现」，该判据在 new 上只贡献成本与假信号。原 `git log --all -S <path>`（pickaxe）匹配的是**文本内容**而非「该路径曾作为文件存在」，会命中任何**提到**该词的提交（自省报告、admin 记录），把观测面污染成引用面，令判定结果随记录行为翻转。
- **`kind: modify`：`git log --all --oneline -- <path>`（路径限定，非 pickaxe）判定。** 命中非空 = 该路径**曾作为文件存在过**，缺失更可能是拆包/改名**漂移**（本仓库高频真实形态：`core/dashboard/data.py`、`core/pm_engine/dispatch.py`、`verification.py`、`core/worktree_manager.py` 均被 refactor 拆分/改名后删除）→ 走人工，不判孤儿；零命中 = 从未作为文件存在过 → 进入孤儿判定。路径限定语义走 tree diff，实测 0.015s（pickaxe 同查询 2.2s，且语义错）。

### 规则 3 — 任务清单零出现

tasks.md 全部任务行（`- [ ]` / `- [x]` 开头）文本不含该路径。任务行是交付需求的第一语义位，判别力最强——抽样 `fix-impl-resultfile-contract-gap` / `add-deliverable-delete-kind` / `evo-stuck-signal-hygiene` 三个正常 spec，首组任务行均逐字点名了 Deliverables 声明路径。

### 判定合成

| kind | 判定 = 孤儿（机械删除声明）的条件 |
|------|-----------------------------------|
| `new` | 规则 1 零命中 **AND** 规则 3 全零 |
| `modify` | 规则 1 零命中 **AND** 规则 2 零命中 **AND** 规则 3 全零 |
| `delete` | **不参与孤儿预分类**（add-deliverable-delete-kind D4 防洗白：delete 声明一律进人工裁决） |

任一规则有命中 → 非孤儿 → 维持 blocked 待人工裁决（宁可多走人工，不误删真实交付物）。

## 机械预分类在裁决链中的位置

现有裁决链（core/pm_engine/dispatch/queue.py:775-816）：缺件 → 实现者异议检查（_disputed_deliverables）→ 异议命中 → blocked 待人工；异议未命中 → _adjudicate_deliverable_missing LLM 终审（typo/reference/missing/unclear）。

本变更在「异议命中」分支内插入预分类：先跑按 kind 分化的孤儿判定，孤儿 → 机械删除 + 审计，不 blocked；非孤儿 → 维持 blocked 待人工。对齐 add-declaration-premechanize 的 guard-preclassify 范式。

## 审计

DisputeAuditStore（.fenix/dispute_audits.jsonl）追加条目：verdict=orphan-preclassify、spec、缺件路径、各规则（源码面 git grep / 路径限定历史 / 任务清单）零引用证据摘要、删除声明 diff 前后。

## lint_declared 增强

core/deliverables.py lint_declared 新增规则：kind: new 声明在主树不存在时，除既有 basename 模糊匹配（规则 4）外，增加孤儿判定——规则 1（源码面 `git grep` 零命中）+ 规则 3（任务清单零出现）同时成立即命中；命中 → 报错附孤儿证据，拒绝晋升。kind: new 不查历史（规则 2 分化结论同上）。

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