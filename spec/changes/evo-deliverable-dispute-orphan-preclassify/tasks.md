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

- [ ] 1.1 core/pm_engine/dispatch/queue.py：缺件异议分支（约 782-801 行 _disputed_deliverables 命中处）接入孤儿声明机械预分类——判为孤儿即不置 blocked，非孤儿维持人工
- [ ] 1.2 core/pm_engine/dispatch/adjudication.py：新增孤儿判定函数。三条规则按 kind 分化：
  - 规则 1 源码面零引用：用 `git grep`（只扫 tracked 文件，勿用裸 `grep -rn` 扫 35G 工作树），pathspec 排除 `.fenix/**`（观测面）、`spec/changes/<本 spec>/**`（声明行自身）、`.history/**`、`dist/**`；
  - 规则 2 历史（仅 kind: modify）：路径限定 `git log --all --oneline -- <path>`，勿用 pickaxe `-S`（文本匹配会把记账面「提到」误判为引用）；kind: new 不查历史；
  - 规则 3 任务清单零出现：tasks.md 全部任务行文本不含该路径。
  合成：new = 规则1 AND 规则3；modify = 规则1 AND 规则2 AND 规则3；delete 不参与。命中 → 机械删除 + 审计（DisputeAuditStore verdict=orphan-preclassify）
- [ ] 1.3 边界：basename 多命中 / 语境等价 / 运行时产物 / kind: modify 历史命中（疑似漂移）等存在任一引用时维持 blocked 待人工

## 2. 晋升期 lint_declared 增强

- [ ] 2.1 core/deliverables.py：lint_declared 对 kind: new 声明增加「任务清单零出现 + 源码面 git grep 零引用」孤儿检查（覆盖范围同 1.2 规则 1），违规报错拒绝晋升；kind: new 不查历史
- [ ] 2.2 报错文案附孤儿证据（声明行位置、任务清单搜索、git grep 结果摘要）

## 3. 测试

- [ ] 3.1 tests/test_deliverable_orphan_preclassify.py：kind: new 三方（规则1/3）零引用 → 机械删除 + 审计留痕 + spec 不 blocked
- [ ] 3.2 非孤儿用例：任一引用存在 → 走既有人工裁决
- [ ] 3.3 kind: modify 规则 2 命中（路径历史存在过）→ 非孤儿，维持人工；kind: delete → 不参与预分类
- [ ] 3.4 排除面用例：仅 .fenix 记账面（todo.md/admin 记录）文本提及 → 仍判孤儿
- [ ] 3.5 lint_declared 孤儿检查用例：孤儿拒绝晋升、正常声明放行、basename 多命中放行