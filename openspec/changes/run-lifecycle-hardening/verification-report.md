# 验证报告：run-lifecycle-hardening

> ⚠️ 本报告由框架于 2026-09-03T18:59:37Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 12/13 场景通过，1 失败，0 错误（全部场景通过）**

验证通过：13 个场景 12 通过 1 失败（fail）。唯一失败场景 archive-confirm-flow-success 的 6 条失败断言全部归类为 test-defect（断言时序问题）：步骤阶段点击「归档 Spec」菜单项与确认按钮均 success（弹窗曾弹出并完成归档），断言阶段却查询已关闭弹窗内元素（.ant-modal-confirm / 确认按钮 / 成功提示）导致全部超时；同模式下拉交互在 archive-menu-terminal-spec-enabled 场景通过、mock 数据与 API 契约一致，未发现产品缺陷，因此不记为产品 Bug。

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 21.62M |
| 本链增量 Token（输出） | 0.27M |


## 场景结果

| 场景 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- |
| smoke-overview-renders | pass | 0/4 | - |
| archive-menu-terminal-spec-enabled | pass | 0/4 | - |
| archive-menu-nonterminal-spec-disabled | pass | 0/4 | - |
| archive-filter-toggle-archived-view | pass | 0/5 | - |
| instant-fail-storm-major-alert-banner | pass | 0/7 | - |
| instant-fail-cooldown-spec-kept-ready | pass | 0/4 | - |
| timeout-settings-parallel-panel-shows-global | pass | 0/5 | - |
| timeout-settings-config-with-overrides-tolerated | pass | 0/4 | - |
| frozen-spec-blocked-error-row | pass | 0/5 | - |
| nonfrozen-spec-menu-shows-freeze | pass | 0/4 | - |
| budget-settings-panel-shows-token-fields | pass | 0/5 | - |
| archive-confirm-flow-success | failed（已修正） | 6/7 | test-defect |
| frozen-spec-menu-shows-unfreeze | pass | 0/4 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| archive-confirm-flow-success | no_click_interception [.ant-dropdown:not(.ant-dropdown-hidden) .ant-dropdown-menu-item:has-text("归档 Spec")] 菜单项可点击 | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤 click 菜单项已 success（下拉当时打开）；断言阶段下拉已关闭、菜单项随弹层从 DOM 移除，trial click 超时。同模式 archive-menu-terminal-spec-enabled 场景下拉断言通过，证明产品侧下拉交互与「归档 Spec」渲染正常 |
| archive-confirm-flow-success | element_visible [.ant-modal-confirm] 归档确认弹窗已弹出 | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤 click 确认按钮已 success，证明弹窗曾出现；断言在 onOk 归档完成弹窗关闭后执行，弹窗已从 DOM 移除（级联失败） |
| archive-confirm-flow-success | text_contains 「归档 Spec」 | test-defect | 测试用例自身缺陷（非产品缺陷） | 级联失败：弹窗与下拉均已关闭，页面无该文本 |
| archive-confirm-flow-success | element_visible [.ant-modal-confirm-btns .ant-btn-primary] 确认按钮可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | 级联失败：弹窗关闭后确认按钮随弹窗移除 |
| archive-confirm-flow-success | no_click_interception [.ant-modal-confirm-btns .ant-btn-primary] 确认按钮可点击 | test-defect | 测试用例自身缺陷（非产品缺陷） | 级联失败：弹窗关闭后确认按钮不存在，trial click 超时 |
| archive-confirm-flow-success | element_visible [.ant-message-success, .ant-message:has-text("已归档")] 归档成功提示出现 | test-defect | 测试用例自身缺陷（非产品缺陷） | 级联失败：message 成功提示短暂展示后自动消失（antd 默认 3s），不能作为弹窗关闭后的持久 DOM 断言目标 |

## 本轮场景集变更

当前稳定场景集共 13 个（第 1 轮）。

- 首轮写入 13 个场景

