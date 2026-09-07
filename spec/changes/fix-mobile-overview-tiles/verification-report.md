# 验证报告：fix-mobile-overview-tiles

> ⚠️ 本报告由框架于 2026-09-07T08:09:28Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 2/8 场景通过，6 失败，0 错误（2 个真实产品 Bug）**

验证完成：8个场景中2个通过、6个失败。其中5个失败由测试场景臆测选择器导致（test-defect），1个由产品统计卡数量变化导致（product-bug）。

| 指标 | 数量 |
| --- | --- |
| 通过 | 2 |
| 失败 | 6 |
| 错误 | 0 |
| 产品 Bug | 2 |
| 本链增量 Token（输入） | 14.43M |
| 本链增量 Token（输出） | 0.10M |


## 真实产品 Bug

### BUG-01（severity=major）· element_visible

- 关联场景：mobile-overview-eyebrow-hidden、mobile-overview-padding-tight、mobile-overview-numrow-wrap、mobile-project-searchbox-fullwidth、desktop-overview-baseline
- 描述：测试场景使用臆测的 CSS 类名选择器（.overview-intro-row/.overview-tile-numrow/.overview-project-card/.overview-tile-eyebrow）定位元素，这些类名在实际 DOM 中不存在，导致所有依赖选择器的断言失败
- 根因：场景文件中的 CSS 选择器与产品实际 DOM 结构不匹配，选择器为臆测类名
- 证据（场景 mobile-overview-eyebrow-hidden 结构化证据，引用）：
  - failed_assertions: [{"type": "element_visible", "selector": ".overview-intro-row", "expected": "可见", "actual": "元素不存在（Timeout 3000ms）"}, {"type": "element_visible", "selector": ".ant-card-head-title", "expected": "可见", "actual": "元素不存在（Timeout 3000ms）"}, {"type": "no_overflow", "selector": ".overview-intro-row", "expected": "无溢出", "actual": "元素不存在"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/fix-mobile-overview-tiles/screenshots/mobile-overview-eyebrow-hidden_assert_fail.png"]
  - first_failed_step: 步骤1: .overview-intro-row 选择器在DOM中不存在

### BUG-02（severity=minor）· element_count

- 关联场景：desktop-overview-card-layout-unchanged
- 描述：桌面端概览页统计卡数量与 SPEC 预期不符：检测到5个卡头标题而非预期的4个，产品可能新增了统计卡
- 根因：产品概览页新增了第5张统计卡，与 SPEC 设计文档（design.md）中的4张卡预期不符
- 证据（场景 desktop-overview-card-layout-unchanged 结构化证据，引用）：
  - failed_assertions: [{"type": "element_count", "selector": ".ant-card-head-title", "expected": 4, "actual": 5}, {"type": "alignment", "selector": ".ant-card-head-title", "axis": "left", "expected": "4个元素对齐一致", "actual": "5个元素值 [312, 552, 792, 1032, 320]"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/fix-mobile-overview-tiles/screenshots/desktop-overview-card-layout-unchanged_assert_fail.png"]
  - first_failed_step: 步骤1: 卡头标题数量为5而不是预期的4


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| mobile-overview-eyebrow-hidden | 移动端（390×844）概览页统计卡灰眉题隐藏：验证四张统计卡（SPEC总数/任务进度/Token消耗/活跃Agent运行）的灰眉题 div 仅在移动端 display:none（出处：global.less L165-166） | failed（已修正） | 3/4 | test-defect |
| mobile-overview-padding-tight | 移动端（390×844）概览页统计卡 body padding 收紧为 12px 16px：验证每张卡 body 左右内边距为 16px（出处：global.less L162-163） | failed（已修正） | 2/4 | test-defect |
| mobile-overview-numrow-wrap | 移动端（390×844）概览页统计卡数字行允许换行：验证 Token 卡「平均每 SPEC」注释行和活跃 Agent 图例行可完整换行展示，无 nowrap/overflow:hidden 截断（出处：global.less L168-171, IntroduceRow.tsx L171/239） | failed（已修正） | 3/4 | test-defect |
| mobile-project-searchbox-fullwidth | 移动端（390×844）概览页项目清单搜索框全宽可用：验证搜索框宽度撑满卡体可用宽度，可正常聚焦输入；过滤组不与标题挤压同一行（出处：global.less L175-184） | failed（已修正） | 4/5 | test-defect |
| desktop-overview-baseline | 桌面端（1920×1080）概览页基线回归验证：确保四张统计卡保持双标题（卡头黑粗 + 灰眉题）、body padding 16px 24px、数字行 nowrap 单行、项目清单搜索框 160px 宽度（出处：design.md L10-13） | failed（已修正） | 3/9 | test-defect |
| desktop-overview-searchbox-fixed-width | 桌面端（1920×1080）概览页项目清单搜索框宽度固定 160px：验证搜索框宽度为 160px（内联样式），不撑满整行（出处：ProjectCards.tsx L153 style={{ width: 160 }}） | pass | 0/4 | - |
| desktop-overview-card-layout-unchanged | 桌面端（1920×1080）概览页卡片布局不变：验证四张统计卡仍以 grid 布局渲染（minmax(170px,1fr)），每卡包含卡头标题和灰眉题双标题（出处：IntroduceRow.tsx L293） | failed（已修正） | 2/6 | product-bug |
| mobile-project-searchbox-interaction | 移动端（390×844）概览页搜索框输入过滤交互：在搜索框中输入项目名称关键词，列表只显示匹配的项目；清空输入后恢复显示全部项目（出处：ProjectCards.tsx L60-66） | pass | 0/4 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| mobile-overview-eyebrow-hidden | element_visible .overview-intro-row | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（Timeout 3000ms） |
| mobile-overview-eyebrow-hidden | element_visible .ant-card-head-title | test-defect | 测试用例自身缺陷（非产品缺陷） | 父容器不存在导致无法定位到标题元素 |
| mobile-overview-eyebrow-hidden | no_overflow .overview-intro-row | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在 |
| mobile-overview-padding-tight | no_overflow .overview-intro-row | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在 |
| mobile-overview-padding-tight | dom_structure .overview-intro-row > .ant-card-body | test-defect | 测试用例自身缺陷（非产品缺陷） | 父容器选择器臆测类名导致无法建立DOM关系 |
| mobile-overview-numrow-wrap | element_visible .overview-tile-numrow | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（Timeout 3000ms） |
| mobile-overview-numrow-wrap | text_contains 平均每 SPEC | test-defect | 测试用例自身缺陷（非产品缺陷） | 依赖的父容器不存在导致文本搜索失败 |
| mobile-overview-numrow-wrap | no_overflow .overview-tile-numrow | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在 |
| mobile-project-searchbox-fullwidth | element_visible .overview-project-card | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（Timeout 3000ms） |
| mobile-project-searchbox-fullwidth | element_visible .overview-project-card .ant-input-search | test-defect | 测试用例自身缺陷（非产品缺陷） | 父容器不存在导致无法定位搜索框 |
| mobile-project-searchbox-fullwidth | no_overflow .overview-project-card .ant-card-extra | test-defect | 测试用例自身缺陷（非产品缺陷） | 父容器不存在导致无法检查溢出 |
| mobile-project-searchbox-fullwidth | no_click_interception .overview-project-card .ant-input-search | test-defect | 测试用例自身缺陷（非产品缺陷） | 元素不存在导致无法测试点击 |
| desktop-overview-baseline | element_visible .overview-intro-row | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（Timeout 3000ms） |
| desktop-overview-baseline | element_visible .overview-tile-eyebrow | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（Timeout 3000ms） |
| desktop-overview-baseline | element_visible .ant-card-head-title | test-defect | 测试用例自身缺陷（非产品缺陷） | 父容器不存在导致无法定位到标题元素 |

## 本轮场景集变更

当前稳定场景集共 8 个（第 1 轮）。

- 首轮写入 8 个场景

