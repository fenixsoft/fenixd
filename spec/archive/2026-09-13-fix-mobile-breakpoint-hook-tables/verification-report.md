# 验证报告：fix-mobile-breakpoint-hook-tables

> ⚠️ 本报告由框架于 2026-09-07T04:49:12Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 3/13 场景通过，10 失败，0 错误（1 个真实产品 Bug）**

验证发现10个失败场景，均为测试用例设计缺陷（hallucinated testid），根因相同：选择器在源码中不存在

| 指标 | 数量 |
| --- | --- |
| 通过 | 3 |
| 失败 | 10 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 3.36M |
| 本链增量 Token（输出） | 0.04M |


## 真实产品 Bug

### BUG-01（severity=major）· 步骤2: 点击选择器超时

- 关联场景：hook-adapt-scroll-no-page-overflow-390、hook-adapt-settings-panel-scroll、hook-adapt-pc-table-unchanged、hook-adapt-effective-card-fields、hook-adapt-crud-card-interaction、hook-adapt-readonly-final-state、hook-adapt-audit-card-info、hook-adapt-pc-interaction-unchanged、bp-unification-modal-mobile-limit、bp-unification-modal-pc-normal
- 描述：测试场景文件使用臆测的 data-testid 选择器（hallucinated testid），导致点击步骤失败
- 根因：测试场景文件中的选择器 [data-testid='spec-row']、[data-testid='spec-row-final']、[data-testid='project-scope-switch'] 在源码中不存在，属于测试用例设计缺陷
- 证据（场景 hook-adapt-scroll-no-page-overflow-390 结构化证据，引用）：
  - failed_assertions: []
  - screenshots: []
  - first_failed_step: 步骤2: 点击 [data-testid='spec-row'] 超时，选择器在源码中不存在（hallucinated testid）


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| bp-unification-page-container-padding | 空窗带内留白收紧生效：600px视口打开任意PageContainer页面，padding-inline为12px（出处：specs/mobile-breakpoint-unification/spec.md Scenario 1） | pass | 0/2 | - |
| bp-unification-settings-label-wrap | 空窗带内设置页label换行规则生效：600px视口打开设置页，表单label以block排版正常换行（出处：specs/mobile-breakpoint-unification/spec.md Scenario 2） | pass | 0/2 | - |
| bp-unification-pc-no-change | PC端样式零影响：>=768px视口下:is(.screen-xs,.screen-sm)规则全部不命中，桌面端渲染与改动前一致（出处：specs/mobile-breakpoint-unification/spec.md Scenario 3） | pass | 0/2 | - |
| hook-adapt-scroll-no-page-overflow-390 | 390px视口下整页不横滚：390×844视口打开spec详情页Hook页签，document.scrollingElement.scrollWidth等于390，页面无横向滚动（出处：specs/hook-tables-mobile-adaptation/spec.md Scenario 1） | failed | - | test-defect |
| hook-adapt-settings-panel-scroll | 设置页项目作用域Hook面板同受兜底：390px视口在设置页切换到项目级作用域并打开Hook面板，页面scrollWidth等于390（出处：specs/hook-tables-mobile-adaptation/spec.md Scenario 2） | failed | - | test-defect |
| hook-adapt-pc-table-unchanged | PC端表格渲染不变：>=768px视口且内容区宽度足够容纳表格，三张表格的列数、列宽、无横向滚动条的表现与改动前一致（出处：specs/hook-tables-mobile-adaptation/spec.md Scenario 3） | failed | - | test-defect |
| hook-adapt-effective-card-fields | 生效合并卡字段完整：390px视口打开含生效Hooks的spec详情Hook页签，每条生效Hook以卡片呈现：来源标注Tag、事件Tag列表、动作名称、启用/停用状态Tag、参数全文（出处：specs/hook-tables-mobile-adaptation/spec.md Scenario 4） | failed | - | test-defect |
| hook-adapt-crud-card-interaction | CRUD Hook卡交互保留：390px视口下Hook列表存在可编辑Hook，卡片上启停Switch可切换且立即保存生效；编辑按钮打开既有Modal且表单回填正确；删除按钮经Popconfirm确认后删除（出处：specs/hook-tables-mobile-adaptation/spec.md Scenario 5） | failed | - | test-defect |
| hook-adapt-readonly-final-state | 终态只读形态：390px视口打开已推送（终态）spec的Hook页签，卡片不呈现编辑/删除入口，Switch置灰不可操作（出处：specs/hook-tables-mobile-adaptation/spec.md Scenario 6） | failed | - | test-defect |
| hook-adapt-audit-card-info | 审计卡信息完整：390px视口查看「最近执行」审计卡片，每卡呈现执行时间、结果Tag、SPEC名、动作、耗时与摘要全文（出处：specs/hook-tables-mobile-adaptation/spec.md Scenario 7） | failed | - | test-defect |
| hook-adapt-pc-interaction-unchanged | PC端交互路径不变：>=768px视口打开Hook页签，三张表格按既有Table渲染，启停/编辑/删除经表格内控件操作，行为与改动前一致（出处：specs/hook-tables-mobile-adaptation/spec.md Scenario 8） | failed | - | test-defect |
| bp-unification-modal-mobile-limit | 固定宽度Modal不溢出视口：390px视口下打开HookManager的新增/编辑Hook Modal，Modal实际宽度≤358px（出处：specs/mobile-breakpoint-unification/spec.md Scenario 4） | failed | - | test-defect |
| bp-unification-modal-pc-normal | PC端Modal宽度不受限：>=768px视口打开同一Modal，Modal宽度仍为桌面设定值（出处：specs/mobile-breakpoint-unification/spec.md Scenario 5） | failed | - | test-defect |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| hook-adapt-scroll-no-page-overflow-390 | 步骤2: 点击 [data-testid='spec-row'] 超时，选择器在源码中不存在 | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（DOM snapshot 佐证） |
| hook-adapt-settings-panel-scroll | 步骤2: 点击 [data-testid='project-scope-switch'] 超时，选择器在源码中不存在 | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（DOM snapshot 佐证） |
| hook-adapt-pc-table-unchanged | 步骤2: 点击 [data-testid='spec-row'] 超时，选择器在源码中不存在 | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（DOM snapshot 佐证） |
| hook-adapt-effective-card-fields | 步骤2: 点击 [data-testid='spec-row'] 超时，选择器在源码中不存在 | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（DOM snapshot 佐证） |
| hook-adapt-crud-card-interaction | 步骤2: 点击 [data-testid='spec-row'] 超时，选择器在源码中不存在 | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（DOM snapshot 佐证） |
| hook-adapt-readonly-final-state | 步骤2: 点击 [data-testid='spec-row-final'] 超时，选择器在源码中不存在 | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（DOM snapshot 佐证） |
| hook-adapt-audit-card-info | 步骤2: 点击 [data-testid='spec-row'] 超时，选择器在源码中不存在 | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（DOM snapshot 佐证） |
| hook-adapt-pc-interaction-unchanged | 步骤2: 点击 [data-testid='spec-row'] 超时，选择器在源码中不存在 | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（DOM snapshot 佐证） |
| bp-unification-modal-mobile-limit | 步骤2: 点击 [data-testid='spec-row'] 超时，选择器在源码中不存在 | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（DOM snapshot 佐证） |
| bp-unification-modal-pc-normal | 步骤2: 点击 [data-testid='spec-row'] 超时，选择器在源码中不存在 | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器含臆测类名，元素从未存在（DOM snapshot 佐证） |

## 本轮场景集变更

当前稳定场景集共 13 个（第 1 轮）。

- 首轮写入 13 个场景

