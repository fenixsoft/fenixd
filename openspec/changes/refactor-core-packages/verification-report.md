# 验证报告：refactor-core-packages

- 运行时间：2026-08-31T06:03:46Z
- 结果：**12 场景，7 PASS / 5 FAIL / 0 warning / 0 error**
- 裁决：**verified（无产品 Bug）**——5 个失败场景经逐断言归因（assertion_triage）全部判定为 `test-defect`，并均映射为 `failed`（不悬置为 warning）。

## 一、通过场景（7）

| 场景 | 覆盖面 |
|---|---|
| v1-overview-load-regression | daemon 启动即 import PMEngine/AgentRunner 两大门面；概览瓦片+项目卡渲染、/api/overview 管道正常 |
| v1-activities-view-switch | 顶栏「运维记录」视图切换、页签栏/时间线/空状态渲染 |
| v1-config-view-switch | 顶栏「配置」视图切换、配置管理页渲染 |
| v1-view-roundtrip-regression | 概览→配置→运维记录→概览往返，视图状态无残留 |
| v1-project-select-ready | 项目下拉与三导航按钮就绪可用（/api/projects 填充） |
| v1-sse-stream-stability | /api/stream SSE 实时通道保持连接、4 秒观测无报错（daemon 运行安全观测面） |
| v2-overview-load | v2 AMIS 壳下 .v2-totals/.v2-proj-grid 经同一套 API 渲染正常 |

## 二、失败场景裁决（5，全部 test-defect）

> 每条失败断言均已单独归类并写回 report.json（classification / evidence / assertion_triage）。
> 所有失败场景的功能性断言均通过：页面渲染、导航跳转、过滤输入、无 console/network 错误——被测功能本身零异常。

### 系统性测试缺陷 ①：no_click_interception 用于导航型点击后复检已卸载元素（3 场景，同一 root cause，按聚合规则合并）

点击步骤本身 success，且同场景后续功能断言证明导航已发生；但 no_click_interception 断言在**导航之后**重新定位源元素，元素已随视图切换从 DOM 卸载 → Locator 3000ms 超时。属断言时序问题（应在导航前校验，或改断言持久 DOM）。

| 场景 | 失败断言 | 佐证 |
|---|---|---|
| v1-project-enter-spec-list | `no_click_interception .cards-grid .card` | click 成功 + 「个 SPEC」/`.spec-filter`/列表或空状态均可见 → 已进入项目视图 |
| v1-spec-detail-open | `no_click_interception .spec-row >> nth=0` | click 成功 + `.spec-tab-body` 可见 → 已进入 SPEC 详情页 |
| v2-project-enter-and-filter-empty | `no_click_interception button:has-text('→ 进入')` | click 成功 + 「SPEC 列表」文本通过 → 已进入项目页 |

### 系统性测试缺陷 ②：v2 断言使用 dark-* 主题前缀，与默认 light 主题实际前缀 cxd-* 不符（2 场景，同一 root cause，合并）

v2 默认主题为 light（`app.js:98` `theme()` 缺省 `'light'`），amis embed 传入 theme `'cxd'`（`app.js:192`、`app.js:392`），实际渲染类前缀为 `cxd-*`；`app.js:567` 注释已明确「类前缀随主题变化(dark-*/cxd-*),必须主题无关匹配」。断言的 `dark-*` 选择器在默认状态下永不命中。

| 场景 | 失败断言 | 佐证 |
|---|---|---|
| v2-config-page-load | `element_visible .dark-SelectControl` | 「LLM Provider 列表」文本通过、无 console/network 错误；另 config.json 默认激活页签为 combo+input-text 结构，select 在未激活页签且 `unmountOnExit:true` 不渲染（双重不成立） |
| v2-activities-page-load | `element_visible .dark-Tabs, .dark-TimeLine, #root .empty-state` | 页标题「运维记录」通过；activities.json 跨项目模式下 act-tabs/act-timeline 配置为可见 |

### 测试缺陷 ③：v2 空结果断言与 amis 空表占位行 DOM 不符（1 断言）

- 场景 `v2-project-enter-and-filter-empty`：`element_not_exist tbody tr`（actual_count=1）。
- kw 过滤链路配置齐备且工作正常：`project.json:35` `submitOnChange:true`、`:16` 请求带 kw 参数、`:20` adaptor 按 kw 过滤；输入值精确写入（text_match actual=expected），无任何报错。actual_count=1 是 amis crud 空结果时 tbody 内的一行「暂无数据」占位（colspan td），并非真实数据行。应改断言空态文案或排除占位行。

## 三、产品 Bug

**无。** 本次重构仅触及 core/ Python 包（pm_engine 包化、dispatch/recovery/reporting/verification 提取），未触碰 core/dashboard 前端；两套界面（v1/v2）在全部功能性断言上均证明 /api/overview、/api/projects、/api/specs、/api/admin-activities、/api/config、/api/stream 数据管道零行为变化。

## 四、分类-状态映射核对

| 场景 | classification | status | 合规 |
|---|---|---|---|
| v1-project-enter-spec-list | test-defect | failed | ✅ |
| v2-project-enter-and-filter-empty | test-defect | failed | ✅ |
| v2-config-page-load | test-defect | failed | ✅ |
| v2-activities-page-load | test-defect | failed | ✅ |
| v1-spec-detail-open | test-defect | failed | ✅ |

所有失败断言均逐条归类为非 product-bug，场景级豁免（不记产品 Bug）成立。

## 五、测试改进建议（不阻塞本次交付）

1. **导航型点击**：no_click_interception 校验前置到导航发生前执行；或导航后不再复检源元素。
2. **v2 选择器**：改用主题无关匹配（如 `[class*="-Tabs"]`、`[class*="-SelectControl"]`），与 app.js:567 的既有约定一致。
3. **空列表断言**：改为 `text_contains 暂无数据` 或排除 amis 占位行，而非「tbody 无 tr」。

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

