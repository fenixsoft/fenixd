# 验证报告：add-deliverable-delete-kind

> ⚠️ 本报告由框架于 2026-09-13T15:42:07Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 21/22 场景通过，1 失败，0 错误（1 个真实产品 Bug）**

21/22 场景通过；唯一失败 full-suite-regression 为产品回归：delete kind 扩展后旧测试软化 promote 路径失效（spec 卡在 reviewing 不转 ready），新功能场景全部通过，但既有行为被破坏，需 implementer 修复后重验。

| 指标 | 数量 |
| --- | --- |
| 通过 | 21 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 3.80M |
| 本链增量 Token（输出） | 0.07M |


## 真实产品 Bug

### BUG-01（severity=major）· exit_code

- 关联场景：full-suite-regression
- 描述：删除 kind（delete）引入后核心回归：受影响 5 个测试文件全量回归退出码 1，复现确认 5 个失败用例全部位于旧文件 tests/test_deliverable_lint.py（TestPromotionLintGate::test_clean_declaration_promotes、test_lint_crash_fails_open）与 tests/test_deliverable_declaration_premechanize.py（TestPromotionSoftening::test_gitignored_modify_softened_promotes、test_mixed_clean_and_softenable_promotes、test_outside_root_softened_promotes）；新文件 tests/test_deliverable_delete_kind.py 全部通过。失败模式统一：_on_spec_drafted 后预期 entry["status"]=="ready"，实际为 "reviewing"——原 gitignored/仓库外路径/mixed 声明的 softening→promote 路径失效。
- 根因：core.deliverables 中 _DECLARED_KINDS 由三值扩展为四值（含 delete）及关联预分类/软化逻辑变更，导致 _on_spec_drafted 的 guard-preclassify 或 softening 对既有合法声明（gitignored modify、仓库外 new、mixed）的判定变化，spec 不再自动 promote 到 ready 而停留在 reviewing，破坏既有产品行为。
- 证据（场景 full-suite-regression 结构化证据，引用）：
  - failed_assertions: [{"type": "exit_code", "selector": "pytest 回归: tests/test_deliverable_delete_kind.py tests/test_deliverable_lint.py tests/test_deliverable_gate.py tests/test_deliverable_declaration_premechanize.py tests/test_deliverable_declaration_triage.py -q", "expected": "0（全部通过）", "actual": "1（存在失败用例，output_match 含 passed 表明部分文件仍通过）"}]
  - screenshots: []
  - first_failed_step: 步骤1: 受影响 5 个测试文件全量回归退出码 1，复现确认 5 个失败用例全部位于旧文件：test_deliverable_lint.py::TestPromotionLintGate::test_clean_declaration_promotes / test_lint_crash_fails_open（2 个），test_deliverable_declaration_premechanize.py::TestPromotionSoftening::test_gitignored_modify_softened_promotes / test_mixed_clean_and_softenable_promotes / test_outside_root_softened_promotes（3 个）；新文件 test_deliverable_delete_kind.py 全部通过。失败模式：_on_spec_drafted 后 assertEqual(entry["status"], "ready") 实际为 "reviewing"——delete kind 引入后预分类逻辑回归，旧测试预期的 softening→promote 路径失效


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| deliverable-kind-schema-four-values | 声明 schema 扩展：_DECLARED_KINDS 由三值扩为四值含 delete | pass | 0/2 | - |
| lint-gitignored-delete-rejected | lint 拒绝 gitignored 路径声明 delete，消息含路径、gitignore 规则与「不进 Deliverables 段」处方 | pass | 0/2 | - |
| lint-nonexistent-delete-rejected | lint 拒绝主树不存在的 delete 声明，消息含「在主树不存在」「无可删」 | pass | 0/2 | - |
| lint-directory-delete-rejected | lint 拒绝目录声明 delete，消息含「是目录」 | pass | 0/2 | - |
| lint-outside-root-delete-rejected | lint 拒绝仓库外路径声明 delete，消息含「仓库外路径」 | pass | 0/2 | - |
| lint-valid-delete-passes | 合法 delete（主树存在的入库具体文件）通过 lint 无违规 | pass | 0/2 | - |
| soften-delete-excluded-classify | classify_unsatisfiable 对 delete 恒返回 False（不参与软化） | pass | 0/2 | - |
| soften-delete-kind-rejected | soften_declared_kind 对 delete 上抛异常，声明段不被改写 | pass | 0/2 | - |
| soften-unsatisfiable-skips-delete | soften_unsatisfiable_declarations 跳过 delete 条目，不加入软化记录 | pass | 0/2 | - |
| gate-delete-guard-reversal | 守卫反判：delete 仍存在→undeleted；已删除→放行；delete+new 混合逐条返回 kind/violation 一一对应 | pass | 0/2 | - |
| anti-whitewash-delete-preclassify | guard-preclassify 不软化 delete 条目，delete 保留在 remaining 进入后继流程 | pass | 0/2 | - |
| judge-delete-reference-rewritten | judge 对 delete 裁决 reference→机械改写为 unclear 转人工，声明段不改写 | pass | 0/2 | - |
| prescription-delete-exists | 派发前处方：delete 主树存在→「删除目标确认」，不出现「修改目标确认」 | pass | 0/2 | - |
| prescription-delete-nonexistent | 派发前处方：delete 主树不存在→「无可删，疑似声明笔误」+ basename 候选 | pass | 0/2 | - |
| teaching-schema-yaml-four-kinds | schema.yaml 教学注入：四值 kind 语义、不可交付模式禁 new/modify/delete、删除不可交付明示 | pass | 0/2 | - |
| teaching-skill-delete-guidance | SKILL.md 含四值 kind 语义、不可交付模式表（禁 new/modify/delete）与删除不可交付明示 | pass | 0/2 | - |
| teaching-no-legacy-reference-advice | 两文件无旧处方「删除目标声明 reference」表述，防止引导到软校验 | pass | 0/2 | - |
| new-test-file-delivered | tests/test_deliverable_delete_kind.py 落盘存在 | pass | 0/2 | - |
| full-suite-regression | 受影响测试文件零失败，确认 kind 词表扩展与返回结构变更无回归 | failed | 1/2 | product-bug |
| extract-delete-goes-to-deliverables | extract_declared 将 delete 归入 deliverables 硬校验组，reference 归入 references | pass | 0/2 | - |
| extract-illegal-kind-ignored | extract_declared 对四类之外的 kind（如 archive）忽略 | pass | 0/2 | - |
| extract-same-path-first-seen-wins | 同路径重复声明保留首见 delete（delete 优先于 new） | pass | 0/2 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

场景集与持久化集一致，无变更。

