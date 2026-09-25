## Deliverables

```yaml
- path: agents/code-fix.md
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: tests/test_code_fix_salvage.py
  kind: new
```

## 1. 提示词契约

- [ ] 1.1 `agents/code-fix.md` 新增「先 commit 再验证」契约段：逐条修复即 `git commit`；后台/定向验证 MUST NOT 作为 commit 前置；回合结束前工作区必须干净；注明违约后果（触发编排 salvage 或整批拒合回）
- [ ] 1.2 排查 `agents/code-fix.md` 全文，改写与该契约矛盾的既有表述（已定位：「验证与提交（契约不变）」段、「验证（一次，提交前）」段的验证先行语义、「单次提交 + MUST NOT 多次提交」措辞——须与 `code-fix-batch-parallel` 能力 delta（本 SPEC `specs/code-fix-batch-parallel/spec.md`）的「边修复边提交、收尾一次验证」口径一致）

## 2. 编排机械兜底

- [ ] 2.1 `core/code_fix.py` 批收尾「分支无提交」分支前插 salvage 检测：产物行 `fixed>0` ∧ 分支无提交 ∧ `git status --porcelain` 非空 → 自动 commit（message `orchestrator-salvage: batch <batch_no> run <run_id>`），进度 current 与 warning 日志留痕，随后继续既有回归/合回裁决路径
- [ ] 2.2 三元组任一不满足时维持既有 `no_effective_fix` 拒合回语义；MUST NOT 空提交

## 3. 验证

- [ ] 3.1 单测（tests/test_code_fix_salvage.py）：搁浅批（fixed 声明 + 未提交修改 + 零提交）→ salvage commit 触发、message 可追溯、合回核销成功
- [ ] 3.2 单测：真零改动批（fixed 声明 + 零提交 + 工作区干净）→ 维持拒合回、无 salvage 提交、链继续
- [ ] 3.3 单测：salvage 后分支 diff 与原工作区改动一致（无 gitignored 噪音卷入）
- [ ] 3.4 契约段存在性断言（「逐条修复即 commit」「验证不阻塞 commit」「收尾工作区干净」三要点可机械检出）
