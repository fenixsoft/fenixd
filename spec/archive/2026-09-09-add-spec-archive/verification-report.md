# 验证报告：add-spec-archive

> ⚠️ 本报告由框架于 2026-09-02T05:55:31Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 0/15 场景通过，15 失败，0 错误（4 个真实产品 Bug）**

验证未通过（15/15 失败，0 通过）。根因：add-spec-archive 功能完全未实现——代码与 SPEC 文档脱节，仅创建了 spec/changes/add-spec-archive/ 规格，未提交任何实现代码。具体表现为三大系统性产品缺陷：(1) specMenuItems 无「归档 Spec」菜单项（6 场景）；(2) 列表无归档状态过滤控件且未按 archived 过滤行（6 场景）；(3) MiscSettingsPanel 无自动归档阈值字段（3 场景）。另发现 1 个测试场景缺陷（antd 两字按钮空格插入致「保存」按钮选择器失配，minor，不阻塞）。所有失败均为确定性失败（同一 mock 数据下稳定复现），非 flaky 或环境问题。建议：implementer 需补齐「归档 Spec」菜单项 + /api/spec-archive 后端端点 + archivedOnly 过滤 + 自动归档阈值设置，再重建 v3 dist 后重跑验证。

| 指标 | 数量 |
| --- | --- |
| 通过 | 0 |
| 失败 | 15 |
| 错误 | 0 |
| 产品 Bug | 4 |
| 本链增量 Token（输入） | 12.56M |
| 本链增量 Token（输出） | 0.12M |


## 真实产品 Bug

### BUG-01（severity=critical）· element_visible / element_not_found_or_not_actionable

- 关联场景：archive-menu-enabled-terminal-spec、archive-menu-disabled-non-terminal-spec、archive-confirm-flow、archive-cancel-no-side-effect、archive-api-non-terminal-rejected、archive-api-conflict-target-exists
- 描述：「归档 Spec」菜单项未实现：list.tsx specMenuItems（list.tsx:556-569）仅含呼叫 Admin 介入/调整优先级/冻结/删除四项，无「归档 Spec」菜单项。导致终态 SPEC 无法从菜单发起归档，6 个场景全部失败（含 4 个因无法点击菜单项而无法到达后续断言的场景）。
- 根因：产品代码未实现「归档 Spec」菜单项。specMenuItems 返回数组中缺少 key='archive' 的 MenuItem，onSpecMenu 也未处理 'archive' 分支；后端亦无 /api/spec-archive 端点（server.py 仅存在既有的 spec-delete 软删除）。归档功能仅存在于 SPEC 文档，未落地为代码。
- 证据（场景 archive-menu-enabled-terminal-spec 结构化证据，引用）：
  - failed_assertions: [{"type": "element_visible", "selector": ".ant-dropdown:not(.ant-dropdown-hidden) .ant-dropdown-menu-item:has-text(\"归档 Spec\")", "label": "「归档 Spec」菜单项在下拉菜单中可见", "expected": "「归档 Spec」菜单项在下拉菜单中可见", "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\".ant-dropdown:not(.ant-dropdown-hidden) .ant-dropdown-menu-item:has-text(\\\"归档 Spec\\\")\").first to be visible\n"}, {"type": "element_visible", "selector": ".ant-dropdown:not(.ant-dropdown-hidden) .ant-dropdown-menu-item:not(.ant-dropdown-menu-item-disabled):has-text(\"归档 Spec\")", "label": "终态 SPEC 的「归档 Spec」菜单项未置灰（可点击）", "expected": "终态 SPEC 的「归档 Spec」菜单项未置灰（可点击）", "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\".ant-dropdown:not(.ant-dropdown-hidden) .ant-dropdown-menu-item:not(.ant-dropdown-menu-item-disabled):has-text(\\\"归档 Spec\\\")\").first to be visible\n"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/add-spec-archive/screenshots/archive-menu-enabled-terminal-spec_assert_fail.png"]
  - first_failed_step: 步骤5: 点击「更多」按钮后，「归档 Spec」菜单项在下拉菜单中不存在

### BUG-02（severity=critical）· element_visible / element_count / element_not_exist

- 关联场景：archive-filter-default-shows-unarchived、archive-api-returns-archived-field、archive-filter-toggle-to-archived、archive-archived-view-menu-limited、archive-filter-toggle-back-to-unarchived、archive-filter-persists-auto-refresh
- 描述：归档状态过滤未实现：列表过滤区（list.tsx:749-758）仅有「全部/仅需求/仅问题」类型筛选，无「未归档/已归档」归档状态切换控件；表格也未按 archived 字段过滤行（mock 返回 archived=true 的 arch-old-done/arch-just-archived 行仍显示在默认视图）。6 个场景全部失败，其中 4 个因点击「已归档」切换控件失败而无法到达后续断言。
- 根因：产品代码未实现 archivedOnly 状态与归档过滤逻辑。list.tsx 中无 archivedOnly useState，filtered useMemo 未按 record.archived 过滤；过滤区无归档切换 Radio.Group。
- 证据（场景 archive-filter-default-shows-unarchived 结构化证据，引用）：
  - failed_assertions: [{"type": "element_visible", "selector": ".ant-radio-button-wrapper:has-text(\"未归档\")", "label": "归档状态切换控件「未归档」选项可见", "expected": "归档状态切换控件「未归档」选项可见", "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\".ant-radio-button-wrapper:has-text(\\\"未归档\\\")\").first to be visible\n"}, {"type": "element_visible", "selector": ".ant-radio-button-wrapper:has-text(\"已归档\")", "label": "归档状态切换控件「已归档」选项可见", "expected": "归档状态切换控件「已归档」选项可见", "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\".ant-radio-button-wrapper:has-text(\\\"已归档\\\")\").first to be visible\n"}, {"type": "element_count", "selector": "tr.ant-table-row[data-row-key]", "label": "", "expected": 3, "actual": "actual=4"}, {"type": "element_not_exist", "selector": "tr[data-row-key=\"arch-old-done\"]", "label": "", "expected": "满足断言", "actual": "actual=N/A"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/add-spec-archive/screenshots/archive-filter-default-shows-unarchived_assert_fail.png"]
  - first_failed_step: 断言: 未归档/已归档切换控件不存在；已归档 SPEC 行未被过滤

### BUG-03（severity=critical）· element_visible / text_contains / element_not_found_or_not_actionable

- 关联场景：settings-threshold-input-visible、settings-threshold-save-valid、settings-threshold-invalid-input
- 描述：自动归档阈值设置未实现：MiscSettingsPanel（settings/components/MiscSettingsPanel.tsx）表单仅渲染「运行产物保留数量」（runs.keep）一个字段，无「自动归档阈值」（auto_threshold）InputNumber、「0 = 禁用」说明文案。3 个场景全部失败。
- 根因：产品代码未实现归档阈值设置。MiscSettingsPanel 的 Form 仅含 name='keep' 的字段，未添加 auto_threshold 字段；后端 config 模型/存储也未实现 archive.auto_threshold。
- 证据（场景 settings-threshold-input-visible 结构化证据，引用）：
  - failed_assertions: [{"type": "element_visible", "selector": "label:has-text(\"自动归档阈值\")", "label": "「自动归档阈值」表单标签可见", "expected": "「自动归档阈值」表单标签可见", "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\"label:has-text(\\\"自动归档阈值\\\")\").first to be visible\n"}, {"type": "element_visible", "selector": ".ant-input-number:has-text(\"50\")", "label": "InputNumber 输入框可见且显示默认值 50", "expected": "InputNumber 输入框可见且显示默认值 50", "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\".ant-input-number:has-text(\\\"50\\\")\").first to be visible\n"}, {"type": "text_contains", "selector": "N/A", "label": "", "expected": "满足断言", "actual": "actual=N/A"}, {"type": "element_visible", "selector": "button:has-text(\"保存\")", "label": "保存按钮可见", "expected": "保存按钮可见", "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\"button:has-text(\\\"保存\\\")\").first to be visible\n"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/add-spec-archive/screenshots/settings-threshold-input-visible_assert_fail.png"]
  - first_failed_step: 断言: 「自动归档阈值」表单标签不存在；设置面板未实现归档阈值字段

### BUG-04（severity=minor）· element_visible (button:has-text("保存"))

- 关联场景：settings-threshold-save-valid、settings-threshold-invalid-input
- 描述：antd 两字 CJK 按钮空格插入导致选择器失配：Button 文本「保存」（恰好 2 个汉字）被 antd 自动渲染为「保 存」，Playwright `button:has-text("保存")` 选择器无法匹配，导致测试无法点击保存按钮。此为测试场景缺陷，非产品 Bug。
- 根因：测试选择器未考虑 antd twoCNChar 自动空格插入机制；应为 `button:has-text("保 存")` 或改用按 data-attribute/class 定位。
- 证据（场景 settings-threshold-save-valid 结构化证据，引用）：
  - failed_assertions: [{"type": "click", "selector": "button:has-text(\"保存\")", "label": "步骤执行失败: click", "expected": "元素存在且可交互", "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\"button:has-text(\\\"保存\\\")\").first to be visible\n"}]
  - screenshots: []
  - first_failed_step: 步骤11: 点击「保存」按钮失败（归档阈值字段未实现，且 antd 两字按钮空格导致选择器失配）


## 场景结果

| 场景 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- |
| archive-menu-enabled-terminal-spec | failed | 2/5 | product-bug |
| archive-menu-disabled-non-terminal-spec | failed | 2/4 | product-bug |
| archive-confirm-flow | failed | - | product-bug |
| archive-cancel-no-side-effect | failed | - | product-bug |
| archive-filter-default-shows-unarchived | failed | 4/6 | product-bug |
| settings-threshold-input-visible | failed | 4/7 | product-bug |
| archive-api-returns-archived-field | failed | 3/4 | product-bug |
| archive-api-non-terminal-rejected | failed | - | product-bug |
| archive-api-conflict-target-exists | failed | - | product-bug |
| archive-filter-toggle-to-archived | failed | - | product-bug |
| settings-threshold-save-valid | failed | - | product-bug |
| settings-threshold-invalid-input | failed | - | product-bug |
| archive-archived-view-menu-limited | failed | - | product-bug |
| archive-filter-toggle-back-to-unarchived | failed | - | product-bug |
| archive-filter-persists-auto-refresh | failed | - | product-bug |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| settings-threshold-input-visible | element_visible button:has-text("保存") 保存按钮可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | antd Button 两字 CJK 自动插入空格渲染为「保 存」，has-text("保存") 不匹配。选择器未考虑 antd twoCNChar 空格插入机制。 |
| settings-threshold-save-valid | click button:has-text("保存") | test-defect | 测试用例自身缺陷（非产品缺陷） | antd Button 两字 CJK 自动插入空格渲染为「保 存」，has-text("保存") 不匹配。且该场景同时因归档阈值字段未实现（product-bug）导致测试操作了错误的已有字段（运行产物保留数量），但按钮选择器失效是独立的测试缺陷。 |
| settings-threshold-invalid-input | click button:has-text("保存") | test-defect | 测试用例自身缺陷（非产品缺陷） | antd Button 两字 CJK 自动插入空格渲染为「保 存」，has-text("保存") 不匹配。且该场景同时因归档阈值字段未实现（product-bug）导致测试操作了错误的已有字段（运行产物保留数量），但按钮选择器失效是独立的测试缺陷。 |

## 本轮场景集变更

当前稳定场景集共 5 个（第 1 轮）。

- 首轮写入 5 个场景

