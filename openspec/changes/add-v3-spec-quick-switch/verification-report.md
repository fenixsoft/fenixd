# 验证报告：add-v3-spec-quick-switch

> ⚠️ 本报告由框架于 2026-09-02T05:54:11Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 3/5 场景通过，2 失败，0 错误（1 个真实产品 Bug）**

5 个场景中 3 个通过、2 个失败。v3-quick-switch-select-navigates 为真实产品 Bug：选中 SPEC 后面板未自动收起（spec.md:31-34 要求收起，DOM 中面板仍存在）。v3-quick-switch-getspec-failure-degrade 为测试设计缺陷：场景故意 mock /api/specs 返回 500 来验证静默降级，no_console_error 断言对预期的 500 错误响应误报失败，非产品缺陷。其余 3 个场景（箭头可见、单 SPEC 隐藏、下拉行排除当前）全部通过，快速切换核心功能正常。

| 指标 | 数量 |
| --- | --- |
| 通过 | 3 |
| 失败 | 2 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 4.74M |
| 本链增量 Token（输出） | 0.03M |


## 真实产品 Bug

### BUG-01（severity=major）· element_not_exist

- 关联场景：v3-quick-switch-select-navigates
- 描述：选中下拉面板中的目标 SPEC 后，下拉面板未自动关闭（actual_count=1，面板仍存在于 DOM）。spec.md:31-34 要求选中后收起面板并跳转，但只有跳转生效，收起逻辑失效。
- 根因：detail.tsx 中选中 SPEC 行时仅执行 history.push 跳转，但面板的 open 状态未在该交互路径上被重置（或关闭逻辑在路由变化后未触发 setState），导致面板保持展开。
- 证据（场景 v3-quick-switch-select-navigates 结构化证据，引用）：
  - failed_assertions: [{"type": "element_not_exist", "layer": 1, "selector": ".spec-quick-switch-panel", "expected": "元素不存在（面板应关闭）", "actual": "元素存在（actual_count: 1，面板未关闭）"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/add-v3-spec-quick-switch/screenshots/v3-quick-switch-select-navigates_assert_fail.png"]
  - first_failed_step: 步骤5: 选中目标 SPEC 后，下拉面板未自动关闭


## 场景结果

| 场景 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- |
| v3-quick-switch-arrow-visible | pass | 0/4 | - |
| v3-quick-switch-arrow-hidden-single-spec | pass | 0/3 | - |
| v3-quick-switch-getspec-failure-degrade | failed（已修正） | 1/4 | test-defect |
| v3-quick-switch-dropdown-rows-exclude-current | pass | 0/7 | - |
| v3-quick-switch-select-navigates | failed（已修正） | 1/5 | product-bug |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| v3-quick-switch-getspec-failure-degrade | no_console_error 第3层断言：控制台无错误 | test-defect | 测试用例自身缺陷（非产品缺陷） | 测试场景 mock /api/specs 返回 500，这是预期的错误路径测试。控制台出现 500 错误是 mock API 返回错误的正常表现，不应作为断言失败。no_console_error 断言未排除预期的 API 错误响应 |

## 本轮场景集变更

当前稳定场景集共 5 个（第 1 轮）。

- 首轮写入 5 个场景

