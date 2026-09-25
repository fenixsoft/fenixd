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

- [x] 1.1 `agents/code-fix.md` 新增「先 commit 再验证」契约段：逐条修复即 `git commit`；后台/定向验证 MUST NOT 作为 commit 前置；回合结束前工作区必须干净；注明违约后果（触发编排 salvage 或整批拒合回）
- [x] 1.2 排查 `agents/code-fix.md` 全文，改写与该契约矛盾的既有表述（已定位：「验证与提交（契约不变）」段、「验证（一次，提交前）」段的验证先行语义、「单次提交 + MUST NOT 多次提交」措辞——须与 `code-fix-batch-parallel` 能力 delta（本 SPEC `specs/code-fix-batch-parallel/spec.md`）的「边修复边提交、收尾一次验证」口径一致）

## 2. 编排机械兜底

- [x] 2.1 `core/code_fix.py` 批收尾「分支无提交」分支前插 salvage 检测：产物行 `fixed>0` ∧ 分支无提交 ∧ `git status --porcelain` 非空 → 自动 commit（message `orchestrator-salvage: batch <batch_no> run <run_id>`），进度 current 与 warning 日志留痕，随后继续既有回归/合回裁决路径
- [x] 2.2 三元组任一不满足时维持既有 `no_effective_fix` 拒合回语义；MUST NOT 空提交

## 3. 验证

- [x] 3.1 单测（tests/test_code_fix_salvage.py）：搁浅批（fixed 声明 + 未提交修改 + 零提交）→ salvage commit 触发、message 可追溯、合回核销成功
- [x] 3.2 单测：真零改动批（fixed 声明 + 零提交 + 工作区干净）→ 维持拒合回、无 salvage 提交、链继续
- [x] 3.3 单测：salvage 后分支 diff 与原工作区改动一致（无 gitignored 噪音卷入）
- [x] 3.4 契约段存在性断言（「逐条修复即 commit」「验证不阻塞 commit」「收尾工作区干净」三要点可机械检出）

## 验证修复（原地打回第 1 轮）

- [x] 先复核失败有效性：逐条核对 `spec/changes/add-codefix-commit-first-contract/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [x] 修复后重跑验证确认通过（复核结论：4 失败场景同根因为真实产品 Bug——首轮回归 passed 快路径批收尾 salvage 守卫引用未初始化 retry_run_id 抛 UnboundLocalError；core/code_fix.py 预初始化修复后 code-fix 家族 6 文件 181 passed + 15 subtests 全绿，3 例 salvage 单测复现失败转通过）
