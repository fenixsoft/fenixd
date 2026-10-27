# 验证报告：evo-code-review-vendored-scope

> ⚠️ 本报告由框架于 2026-10-06T19:54:25Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-06T19:54:24.950849+00:00+run-result@mtime1791316464974579926

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.77M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| full-collect-excludes-vendored | full 档全仓收集中 thirdparty/third_party/vendor 目录段文件不入 manifest，非 vendored 源码照常收集（spec vendored-review-scope「vendored 文件不入 manifest」；出处 core/code_review.py:858 collect_manifest、:815 _is_source_file，vendored 排除表 :790-792） | pass | 0/6 | - |
| window-collect-excludes-vendored | window 档变更面收集对 vendored 路径改动同样排除，非 vendored 改动照常收集（spec vendored-review-scope「window 档同样生效」；出处 core/code_review.py:858 collect_manifest window 分支，admin_monitor 侧共用消费点 core/admin_monitor.py:1569-1571） | pass | 0/3 | - |
| vendored-dir-segment-exact-match | vendored 目录段精确匹配：任意层级目录段命中即排除，近名目录（vendors/vendorkit）与 external 自有代码不误伤，非 vendored 收集行为不变（spec「非 vendored 路径的收集行为 MUST NOT 变化」+ 目录段精确匹配语义，external 歧义大不收；出处 core/code_review.py:798 _EXCLUDED_DIRS 单段比较、:805 _EXCLUDED_PREFIXES） | pass | 0/6 | - |
| exclusion-table-single-source | 排除表单表派生：_EXCLUDED_TOP_DIRS 含三段 vendored 目录，_EXCLUDED_DIRS 为其超集、_EXCLUDED_PREFIXES 覆盖其前缀派生（tasks 1.1「单表派生消除漂移面」约束，MUST NOT 在派生表重复手写；出处 core/code_review.py:773-805） | pass | 0/6 | - |
| prompt-honest-collection-scope | 评审提示词如实描述收集范围：说明框架侧已排除测试/文档/生成物与 vendored 第三方目录（thirdparty / third_party / vendor），旧措辞「其中的路径是产品代码」不再出现（tasks 1.2；出处 agents/code-review.md:20 区域） | pass | 0/5 | - |
| prompt-fenix-ignore-second-line | 评审提示词第二道防线：对漏出排除表但带 fenix-ignore 标注且理由为保持上游同步的文件，复核规则指示只记录不上报缺陷条目、findings 置空数组（spec「漏出文件按标注不出题」的规则面，tasks 1.2；出处 agents/code-review.md:63 第二道防线段） | pass | 0/5 | - |
| pytest-vendored-exclusion-cases | 交付物测试：tests/test_code_review.py 的 vendored 排除用例（full 档 test_excludes_vendored_dirs + window 档 test_window_scope_excludes_vendored_dirs）在交付树上全部通过（tasks 2.1；出处 tests/test_code_review.py:1152/:1178） | pass | 0/4 | - |
| pytest-legacy-exclusion-regression | 回归点：既有排除语义用例（tests/ 目录排除 test_excludes_tests、生成物排除 test_excludes_generated_artifacts）在 vendored 排除合入后仍通过，排除表扩展不破坏既有排除（出处 tests/test_code_review.py:1144/:1191） | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 8 个（第 1 轮）。

- 首轮写入 8 个场景

