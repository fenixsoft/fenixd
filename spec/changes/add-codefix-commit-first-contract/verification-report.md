# 验证报告：add-codefix-commit-first-contract

> ⚠️ 本报告由框架于 2026-09-25T07:23:14Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-25T07:16:33.773601+00:00

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 5/9 场景通过，4 失败，0 错误（1 个真实产品 Bug）**

9 场景：5 pass / 4 fail。4 个失败场景同根因聚 合为 1 个 critical 产品 Bug：core/code_fix.py:2699 在首轮回归 passed 的正常快路径引用未初始化的 retry_run_id（仅 :2574 重试循环内赋值）触发 UnboundLocalError，批 worker 收尾中断，salvage/合回/chain_skipped 全部未执行——add-codefix-targeted-retry 引入、其自身测试盲区（只构造回归失败路径）。任务 1.x 提示词契约类场景（code-fix.md 措辞与单测门）全绿。修复点：循环外预初始化 retry_run_id（如 retry_run_id = ''）或 :2699 改用局部安全回退。

| 指标 | 数量 |
| --- | --- |
| 通过 | 5 |
| 失败 | 4 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 5.29M |
| 本链增量 Token（输出） | 0.09M |


## 真实产品 Bug

### BUG-01（severity=critical）· exit_code / output_match（pytest 批 worker UnboundLocalError）

- 关联场景：codefix-salvage-stranded-batch-merged、codefix-salvage-zero-change-still-rejected、codefix-salvage-diff-fidelity-no-noise、codefix-family-regression-green
- 描述：批收尾 salvage 守卫在「首轮回归一次通过」的正常快路径崩溃：local variable 'retry_run_id' referenced before assignment（core/code_fix.py:2699）。每批回归 passed 的合回/核销/salvage 收尾全部异常，code-fix 车道收尾失效
- 根因：add-codefix-targeted-retry 引入定向重试轮时，retry_run_id 仅在首轮回归失败后的重试循环（core/code_fix.py:2574）内赋值；首轮回归 passed 跳过整个重试块，:2698 salvage 守卫条件短路求值到 :2699 的 retry_run_id 即抛 UnboundLocalError，批 worker 整段收尾中断（定向重试自身用例构造回归失败场景，未覆盖首轮 passed 路径，故其轮内验证绿）
- 证据（场景 codefix-salvage-stranded-batch-merged 结构化证据，引用）：
  - failed_assertions: [{"type": "exit_code", "expected": 0, "actual": 1}, {"type": "output_match", "expected": "test_stranded_batch_salvaged_and_merged PASSED", "actual": "exit 1，无该 PASSED 行；:171 AssertionError 0 != 1 搁浅批 salvage 后 MUST 合回"}]
  - screenshots: []
  - first_failed_step: 步骤1: pytest TestSalvageStrandedBatch exit 1 — 批 worker 异常（第 1 批）: local variable 'retry_run_id' referenced before assignment，salvage 未触发（merge_calls=0），断言 :171 len(wm.merge_calls)==1 失败


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| codefix-contract-section-present | 提示词契约段存在性：agents/code-fix.md 存在「先 commit 再验证（契约）」段，且「逐条修复即 commit」「验证不阻塞 commit」「收尾工作区干净」三要点与「违约后果」（salvage 兜底 no_effective_fix 拒合回）机械可检（任务 1.1；出处 agents/code-fix.md:25-29，commit e7969f76 新增） | pass | 0/10 | - |
| codefix-contract-parallel-prompt-aligned | 并行/提交段口径改写到位：并行段标题改「提交与验证（边修复边提交）」、验证段改「验证（一次，提交后）」、提交段改「边修复边提交到当前 worktree 分支」、「MUST NOT 逐组验证」保留（任务 1.2 与 code-fix-batch-parallel delta 对齐；出处 agents/code-fix.md:56-59、:92-96） | pass | 0/6 | - |
| codefix-contract-conflicting-wording-purged | 与「先 commit 再验证」互斥的旧口径清除：「MUST NOT 多次提交」「验证（一次，提交前）」「全部条目处置并验证后，单次提交」「验证与提交（契约不变）」四条旧措辞 MUST NOT 残留于 agents/code-fix.md（任务 1.2；出处 tests/test_code_fix_salvage.py:267-272 同口径） | pass | 0/5 | - |
| codefix-prompt-contract-unit-gate | 交付的单测契约门通过：TestPromptContractSection 两用例（契约段三要点可检出 + 旧口径清除）全绿（任务 3.4；出处 tests/test_code_fix_salvage.py:248-272；PASSED 行为实测照抄，无 parametrize 后缀） | pass | 0/3 | - |
| codefix-salvage-stranded-batch-merged | 搁浅批 salvage 兜底正向路径：产物行 fixed、分支零提交、worktree 有未提交改动 → 自动以「orchestrator-salvage: batch <批号> run <run_id>」提交到批分支，回归后正常合回、fixed 条目置 resolved、warning 日志 + 进度 current 双留痕（任务 2.1/3.1；出处 core/code_fix.py:2211-2241、:2452-2457） | failed（已修正） | 2/2 | product-bug |
| codefix-salvage-zero-change-still-rejected | 真零改动批维持拒合回（D4 空状态守卫）：产物行声明 fixed 但分支零提交且工作区干净（声明与事实不符）→ MUST NOT 空提交、MUST NOT 合回、条目保持 open 入 chain_skipped、链继续推进（任务 2.2/3.2；出处 core/code_fix.py:2216-2219、tests/test_code_fix_salvage.py:196-224） | failed（已修正） | 2/2 | product-bug |
| codefix-salvage-diff-fidelity-no-noise | salvage 提交保真回归点：salvage 后分支 diff 与原工作区源码改动一致（README.md + salvaged_fix.py），gitignored 噪音（debug.log、.fenix/ 运行时产物）不被卷入（任务 3.3 与 design Risks 第 2 条验收约定；出处 core/code_fix.py:1147-1165、tests/test_code_fix_salvage.py:230-245） | failed（已修正） | 2/2 | product-bug |
| codefix-salvage-source-anchor | 机械兜底源码锚点：core/code_fix.py 存在 salvage 三元组检测函数 _salvage_stranded_batch（porcelain 探测 + add -A + orchestrator-salvage message 模板）且已接入批收尾「分支无提交」判定分支（任务 2.1；出处 core/code_fix.py:1147、:1167、:2211、:2224、:2452） | pass | 0/6 | - |
| codefix-family-regression-green | 回归点：code-fix 家族全部测试（编排收尾分支插入无回归、同批改写的 test_code_fix.py 并行契约断言）整体绿：180 passed / exit 0（实测；tasks 3.1-3.4 不破坏存量；出处 tests/test_code_fix.py:261-292、tests/test_code_fix_salvage.py 全文件） | failed（已修正） | 3/4 | product-bug |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景

