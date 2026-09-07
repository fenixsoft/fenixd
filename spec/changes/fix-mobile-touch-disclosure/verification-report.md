# 验证报告：fix-mobile-touch-disclosure

> ⚠️ 本报告由框架于 2026-09-07T07:02:24Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 6/16 场景通过，10 失败，0 错误（5 个真实产品 Bug）**

发现 5 类 bug：1) 移动端场景选择器 .ant-list 应为 .ant-table-row（影响 3 场景）；2) 桌面端场景 .ant-table-row 在桌面 viewport 不可见（影响 2 场景）；3) 断言时序问题：点击后 modal 遮挡按钮（1 场景）；4) 概览卡片进入按钮选择器错误（1 场景）；5) mock_api 数据未应用到页面（3 场景）。

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 10 |
| 错误 | 0 |
| 产品 Bug | 5 |
| 本链增量 Token（输入） | 21.80M |
| 本链增量 Token（输出） | 0.20M |


## 真实产品 Bug

### BUG-01（severity=critical）· wait (selector mismatch)

- 关联场景：mobile-touch-expand-basic、mobile-progress-completed、mobile-progress-incomplete
- 描述：移动端场景在 /projects 路由使用选择器 .ant-list，但该路由 mobile viewport 下列表渲染为 Table 组件，应使用 .ant-table-row
- 根因：场景文件选择器与实际 DOM 结构不匹配：/projects mobile viewport 下列表使用 antd Table（.ant-table-row）而非 List（.ant-list）
- 证据（场景 mobile-touch-expand-basic 结构化证据，引用）：
  - failed_assertions: []
  - screenshots: []
  - first_failed_step: 等待列表加载超时：选择器 .ant-list 在 mobile-touch-expand-basic 对应页面不存在

### BUG-02（severity=critical）· wait (selector mismatch)

- 关联场景：mobile-touch-expand-pc、desktop-progress-unchanged
- 描述：桌面端场景在 /projects/fenixd 路由使用选择器 .ant-table-row，但桌面端 viewport 下该选择器不可见
- 根因：场景文件选择器在桌面端 viewport 下不适用：同选择器在 mobile viewport（通过场景 mobile-detail-breadcrumb-hidden）中可用，但桌面端渲染形式不同
- 证据（场景 mobile-touch-expand-pc 结构化证据，引用）：
  - failed_assertions: []
  - screenshots: []
  - first_failed_step: 等待列表加载超时：.ant-table-row 在 /projects/fenixd 桌面端视口下不可见

### BUG-03（severity=major）· no_click_interception

- 关联场景：mobile-touch-expand-conflict
- 描述：点击'查看处置过程'按钮触发 modal 后，no_click_interception 断言再次点击同一按钮被 modal 遮挡（断言时序问题）
- 根因：断言时序设计缺陷：步骤已成功点击按钮触发 modal，随后断言尝试再次点击被 ant-modal-wrap 遮挡的按钮
- 证据（场景 mobile-touch-expand-conflict 结构化证据，引用）：
  - failed_assertions: [{"type": "no_click_interception", "selector": ".touch-expand:has-text('查看处置过程')", "expected": "点击不被拦截", "actual": "步骤点击触发 modal 打开后，断言再次点击同一按钮被 ant-modal-wrap 遮挡（断言时序问题）"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/fix-mobile-touch-disclosure/screenshots/mobile-touch-expand-conflict_assert_fail.png"]
  - first_failed_step: 断言时序问题：点击"查看处置过程"后modal打开，断言再点击被modal遮挡

### BUG-04（severity=major）· click (selector mismatch)

- 关联场景：mobile-touch-expand-overview
- 描述：概览卡片中 .touch-expand:has-text('进入') 按钮选择器与实际渲染 DOM 不匹配，按钮不存在
- 根因：场景文件选择器错误：概览卡片中的进入按钮选择器与实际 DOM 结构不匹配
- 证据（场景 mobile-touch-expand-overview 结构化证据，引用）：
  - failed_assertions: []
  - screenshots: []
  - first_failed_step: 点击进入按钮超时：.touch-expand:has-text('进入') 在概览卡片中不存在

### BUG-05（severity=major）· mock_api / element_visible

- 关联场景：mobile-activities-long-summary-fold、mobile-activities-expand-collapse、mobile-activities-sse-refresh
- 描述：运维记录场景声明 mock_api 注入长摘要数据，但页面渲染的卡片无长摘要内容，展开全文按钮不存在
- 根因：mock_api 前置数据未被应用到页面渲染：场景声明了 mock_api 步骤注入长摘要运维记录，但实际页面渲染的运维记录卡片无长摘要内容
- 证据（场景 mobile-activities-long-summary-fold 结构化证据，引用）：
  - failed_assertions: [{"type": "element_visible", "selector": ".touch-expand:has-text('展开全文')", "expected": "元素可见", "actual": "元素不存在（mock_api 未注入长摘要数据，页面无长摘要卡片）"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/fix-mobile-touch-disclosure/screenshots/mobile-activities-long-summary-fold_assert_fail.png"]
  - first_failed_step: 展开全文按钮不可见：mock_api 前置数据未生效，运维记录卡片无长摘要内容


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| mobile-touch-expand-basic | 移动端 SPEC 列表卡片「更多」按钮触控目标扩展验证（出处：spec/changes/fix-mobile-touch-disclosure/specs/mobile-touch-targets/spec.md:6-10） | failed（已修正） | - | test-defect |
| mobile-touch-expand-overview | 移动端概览项目卡「进入/更多」按钮触控目标扩展验证（出处：spec/changes/fix-mobile-touch-disclosure/tasks.md:21, ProjectCards.tsx:190-201） | failed（已修正） | - | test-defect |
| mobile-touch-expand-detail-doc | 移动端 spec 详情页「文档」链接触控目标扩展验证（出处：spec/changes/fix-mobile-touch-disclosure/tasks.md:21, detail.tsx） | pass | 0/2 | - |
| mobile-touch-expand-conflict | 运维记录「查看处置过程」按钮内联 padding 冲突处理验证——命中区 ≥32px 且视觉不变形（出处：spec/changes/fix-mobile-touch-disclosure/specs/mobile-touch-targets/spec.md:12-14） | failed（已修正） | 1/2 | test-defect |
| mobile-touch-expand-pc | PC 端触控目标扩展规则不生效验证——桌面端按钮可见可点（出处：spec/changes/fix-mobile-touch-disclosure/specs/mobile-touch-targets/spec.md:16-18） | failed（已修正） | - | test-defect |
| mobile-progress-completed | 移动端已完成 SPEC 卡片进度单一表达——显示「已完成」替代 100%（出处：spec/changes/fix-mobile-touch-disclosure/specs/mobile-touch-targets/spec.md:20-24） | failed（已修正） | - | test-defect |
| mobile-progress-incomplete | 移动端未完成 SPEC 卡片进度表达不变——显示百分比（出处：spec/changes/fix-mobile-touch-disclosure/specs/mobile-touch-targets/spec.md:26-28） | failed（已修正） | - | test-defect |
| desktop-progress-unchanged | 桌面端 SPEC 表格进度列不变——done/total + 百分比双表达（出处：spec/changes/fix-mobile-touch-disclosure/specs/mobile-touch-targets/spec.md:30-32） | failed（已修正） | - | test-defect |
| mobile-detail-breadcrumb-hidden | 移动端详情页顶栏面包屑隐藏——页面头部为返回箭头 + SPEC 名 + Tag 行两层结构（出处：spec/changes/fix-mobile-touch-disclosure/specs/mobile-detail-header-density/spec.md:4-8） | pass | 0/3 | - |
| desktop-detail-breadcrumb-visible | PC 端详情页面包屑正常显示（出处：spec/changes/fix-mobile-touch-disclosure/specs/mobile-detail-header-density/spec.md:10-12） | pass | 0/2 | - |
| mobile-detail-tag-wrap | 移动端详情页标题 Tag 行换行不溢出——scrollWidth ≤ 390（出处：spec/changes/fix-mobile-touch-disclosure/specs/mobile-detail-header-density/spec.md:14-18） | pass | 0/3 | - |
| mobile-activities-long-summary-fold | 移动端运维记录长摘要默认折叠——maxHeight 截断 + 渐隐 mask + 展开全文按钮（出处：spec/changes/fix-mobile-touch-disclosure/specs/mobile-activities-disclosure/spec.md:4-10） | fail | 1/2 | env |
| mobile-activities-expand-collapse | 移动端运维记录长摘要展开收起往返——点击展开全文后正文完整、点击收起后恢复折叠（出处：spec/changes/fix-mobile-touch-disclosure/specs/mobile-activities-disclosure/spec.md:12-14） | fail | - | env |
| mobile-activities-short-summary-no-fold | 移动端短摘要（≤300 字符）不折叠——全文展开且无切换按钮（出处：spec/changes/fix-mobile-touch-disclosure/specs/mobile-activities-disclosure/spec.md:16-18） | pass | 0/2 | - |
| mobile-activities-safety-info-visible | 移动端运维记录操作安全信息始终可见——失败原因/处置/建议区块不折叠（出处：spec/changes/fix-mobile-touch-disclosure/specs/mobile-activities-disclosure/spec.md:20-22） | pass | 0/3 | - |
| mobile-activities-sse-refresh | 移动端运维记录 SSE 刷新后展开态不串卡——Timeline items 有稳定 key，重渲后展开态保持（出处：spec/changes/fix-mobile-touch-disclosure/specs/mobile-activities-disclosure/spec.md:26-30） | fail | - | env |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| mobile-touch-expand-basic | wait .ant-list >> nth=0 等待列表加载 | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤在 waitForSelector 阶段超时（5s），assertion 从未执行。选择器 .ant-list 在 mobile 390px viewport 对应页面中不存在，正确的选择器应为 .ant-table-row（参照同 viewport 下通过的 mobile-detail-breadcrumb... |
| mobile-touch-expand-overview | click .ant-card >> nth=0 >> .touch-expand:has-text('进入') 点击概览卡片进入按钮 | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤在 click 阶段超时（5s），assertion 从未执行。概览卡片（.ant-card）已加载但其中不存在 .touch-expand:has-text('进入') 子元素。mock_api 已执行但按钮选择器与实际渲染的 DOM 不匹配。 |
| mobile-touch-expand-conflict | no_click_interception .touch-expand:has-text('查看处置过程') | test-defect | 测试用例自身缺陷（非产品缺陷） | 断言时序问题：步骤已成功点击该按钮（触发 modal 弹出），随后 no_click_interception 断言尝试再次点击同一按钮时被 ant-modal-wrap 遮挡。应在点击前校验可点性，而非点击后断言。 |
| mobile-touch-expand-pc | wait .ant-table-row >> nth=0 等待列表加载 | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤在 waitForSelector 阶段超时（5s），assertion 从未执行。该场景为桌面端 viewport（默认 1280px），路由 /projects/fenixd 下 .ant-table-row 不可见。同场景 mobile-touch-expand-detail-doc 在 mobile ... |
| mobile-progress-completed | wait .ant-list >> nth=0 等待列表加载 | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤在 waitForSelector 阶段超时（5s），assertion 从未执行。路由为 /projects（项目列表页），mobile 390px viewport 下列表渲染为 Table 组件而非 List，应使用 .ant-table-row（参照同 viewport 通过场景 mobile-det... |
| mobile-progress-incomplete | wait .ant-list >> nth=0 等待列表加载 | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤在 waitForSelector 阶段超时（5s），assertion 从未执行。与 mobile-progress-completed 同一根因：/projects 路由 mobile viewport 下列表渲染为 Table 组件，应使用 .ant-table-row。 |
| desktop-progress-unchanged | wait .ant-table-row >> nth=0 等待列表加载 | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤在 waitForSelector 阶段超时（5s），assertion 从未执行。该场景为桌面端 viewport（默认 1280px），路由 /projects/fenixd 下 .ant-table-row 不可见。同选择器在 mobile-detail-breadcrumb-hidden（mobile... |
| mobile-activities-long-summary-fold | element_visible .touch-expand:has-text('展开全文') 展开全文按钮可见 | env | 环境因素（非产品缺陷） | Locator.wait_for: Timeout 3000ms exceeded. 场景声明了 mock_api 注入长摘要运维记录，但页面渲染的运维记录卡片无长摘要内容，.touch-expand:has-text('展开全文') 按钮不存在。mock_api 数据未被应用到页面渲染。 |
| mobile-activities-expand-collapse | click .touch-expand:has-text('展开全文') 点击展开全文 | env | 环境因素（非产品缺陷） | 步骤在 click 阶段超时（5s），assertion 从未执行。场景声明了 mock_api 注入长摘要运维记录，但页面渲染的卡片无长摘要内容，.touch-expand:has-text('展开全文') 按钮不存在，mock_api 数据未被应用到页面渲染。 |
| mobile-activities-sse-refresh | click .touch-expand:has-text('展开全文') 展开第一个长摘要 | env | 环境因素（非产品缺陷） | 步骤在 click 阶段超时（5s），assertion 从未执行。场景声明了 mock_api 注入长摘要运维记录，但页面渲染的卡片无长摘要内容，.touch-expand:has-text('展开全文') 按钮不存在，mock_api 数据未被应用到页面渲染。 |

## 本轮场景集变更

当前稳定场景集共 16 个（第 1 轮）。

- 首轮写入 16 个场景

