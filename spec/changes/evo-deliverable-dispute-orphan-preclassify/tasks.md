# Tasks: deliverable-dispute-orphan-preclassify

## Deliverables

```yaml
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/pm_engine/dispatch/adjudication.py
  kind: modify
- path: core/deliverables.py
  kind: modify
- path: tests/test_deliverable_orphan_preclassify.py
  kind: new
```

## 1. dispute 孤儿预分类

- [ ] 1.1 core/pm_engine/dispatch/queue.py：缺件异议分支（queue.py:802 `_disputed_deliverables` 命中处，blocked 分支 806-820）接入孤儿声明机械预分类——判为孤儿即不置 blocked，非孤儿维持人工。删除后的续走契约 MUST 与 `_preclassify_missing`（adjudication.py:295）逐条对齐：①删除声明两行并留 .history 备份；②**立即提交**改写的 tasks.md（同 `_commit_softened_declaration`，adjudication.py:257，否则 merge-back 被 git 拒绝 → spec 被 merge 指纹熔断冻结）；③重跑 `_deliverable_gate_missing` 全清 → `status=implementing` + `error=None` + `proceed` 放行 merge；④仍有缺件 → 以重跑后的 remaining 续走既有后续（仍带异议 → blocked 待人工；无异议 → 既有 `_adjudicate_deliverable_missing` 终审）；⑤任一环节异常 → 全量回退既有 blocked 待人工（fail-open）
- [ ] 1.2 core/pm_engine/dispatch/adjudication.py：新增孤儿判定函数。三条规则按 kind 分化：
  - 规则 1 源码面零引用：用 `git grep`（只扫 tracked 文件，勿用裸 `grep -rn` 扫 35G 工作树），**排除面必须写负向 pathspec magic**：`git grep -n -F <path> -- ':!.fenix/**' ':!spec/changes/<本 spec>/**' ':!.history/**' ':!dist/**'`（`-- 'x/**'` 是**包含**语义，照字面写只在被排除面上搜索、恒零命中 = 一切缺件被误判孤儿；`-F` 关闭正则避免路径元字符被解释）；
  - 规则 2 历史（仅 kind: modify）：路径限定 `git log --all --oneline -- <path>`，勿用 pickaxe `-S`（文本匹配会把记账面「提到」误判为引用）；kind: new 不查历史；
  - 规则 3 任务清单零出现：tasks.md 全部任务行（`- [ ]`/`- [x]` 开头）文本不含该路径**及其 basename**（实测 `add-architect-agent-1789628607` 的 `ArchitectPanel.tsx` 任务行只写 basename，只认全路径会误拦非孤儿声明；事故案 basename 在任务行命中 0/40，放宽不减检出）。
  合成：new = 规则1 AND 规则3；modify = 规则1 AND 规则2 AND 规则3；delete 不参与。命中 → 机械删除 + 审计（DisputeAuditStore，`verdicts:[{element, verdict:"orphan-preclassify", reasoning:"orphan-preclassify: …"}]`，`judge_run_id` 空串，`diff` 记前后文本）
- [ ] 1.3 边界：basename 多命中 / 语境等价 / 运行时产物 / kind: modify 历史命中（疑似漂移）等存在任一引用时维持 blocked 待人工。规则 3 的「basename 计入」只放宽判定入参，不放宽结论：basename 命中 → 非孤儿（回退人工），不自动删除

## 2. 晋升期 lint_declared 增强

- [ ] 2.1 core/deliverables.py：lint_declared（core/deliverables.py:774）对 kind: new 声明增加「任务清单零出现（全路径与 basename 皆零）+ 源码面 git grep 零引用」孤儿检查（覆盖范围与负向 pathspec 写法同 1.2 规则 1，`git -C <project_root> grep`），违规报错拒绝晋升；kind: new 不查历史。**与规则 4 的边界 MUST 写清**：basename 多命中沿用规则 4 fail-open 放行（孤儿检查不触发），basename 唯一命中已由规则 4 拦，孤儿检查只覆盖规则 4 原本放行的「basename 零命中」形态；lint 自身故障仍 fail-open
- [ ] 2.2 报错文案附孤儿证据（声明行位置、任务清单搜索、git grep 结果摘要）

## 3. 测试

- [ ] 3.1 tests/test_deliverable_orphan_preclassify.py：kind: new 三方（规则1/3）零引用 → 机械删除 + 审计留痕 + spec 不 blocked
- [ ] 3.2 非孤儿用例：任一引用存在 → 走既有人工裁决
- [ ] 3.3 kind: modify 规则 2 命中（路径历史存在过）→ 非孤儿，维持人工；kind: delete → 不参与预分类
- [ ] 3.4 排除面用例：仅 .fenix 记账面（todo.md/admin 记录）文本提及 → 仍判孤儿；另证负向 pathspec 生效——排除面之外的 tracked 文件提及 → 非孤儿（若 pathspec 误写成包含语义则本用例必失败，防「恒零命中」回归）
- [ ] 3.5 lint_declared 孤儿检查用例：孤儿拒绝晋升、正常声明放行、basename 多命中放行
- [ ] 3.6 续走契约用例：删除后重跑守卫全清 → spec 置 implementing 且放行 merge（不被 merge 指纹熔断）；删除后主树 tasks.md 已提交（merge-back 无 dirty 死锁）；重跑后仍有非异议缺件 → 交既有终审；判定异常 → 回退 blocked 待人工