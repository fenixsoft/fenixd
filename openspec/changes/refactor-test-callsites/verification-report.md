# 验证报告

**日期**: 2026-08-31T17:39:56.495153+00:00

## 总结

- 总场景数: 26
- 通过: 0
- 失败: 25
- 警告: 1
- 错误: 0
- 环境阻止: 0

## 缺陷列表

### 1. Dashboard 项目概览页面正确展示项目列表与状态统计 (出处: core/dashboard/server.py:14-16)

- **场景**: dashboard-project-overview
- **严重性**: critical
- **断言类型**: element_visible .project-card, [data-testid='project-card'], .dark-Card
- **根因**: 步骤3: wait .project-card, [data-testid='project-card'], .dark-Card 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_visible",
      "selector": ".project-card, [data-testid='project-card'], .dark-Card",
      "expected": "visible",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\".project-card, [data-testid='project-card'], .dark-Card\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/dashboard-project-overview_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/dashboard-project-overview_current.png"
  ],
  "first_failed_step": "步骤3: wait .project-card, [data-testid='project-card'], .dark-Card 失败"
}

### 2. GET /api/overview 返回正确的项目状态聚合结构 (出处: core/dashboard/server.py:15-16)

- **场景**: overview-api-response-structure
- **严重性**: critical
- **断言类型**: text_contains projects
- **根因**: 断言2: text_contains 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "text_contains",
      "selector": "projects",
      "expected": "projects",
      "actual": "Assertion failed"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/overview-api-response-structure_assert_fail.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/overview-api-response-structure_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/overview-api-response-structure_current.png"
  ],
  "first_failed_step": "断言2: text_contains 失败"
}

### 3. GET /api/spec-doc 正确返回 Proposal 文档原文 (出处: core/dashboard/server.py:20)

- **场景**: spec-doc-api-proposal
- **严重性**: critical
- **断言类型**: text_contains 门面委托
- **根因**: 断言2: text_contains 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "text_contains",
      "selector": "门面委托",
      "expected": "门面委托",
      "actual": "Assertion failed"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-doc-api-proposal_assert_fail.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-doc-api-proposal_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-doc-api-proposal_current.png"
  ],
  "first_failed_step": "断言2: text_contains 失败"
}

### 4. GET /api/spec-doc 正确返回 Design 文档原文 (出处: core/dashboard/server.py:20)

- **场景**: spec-doc-api-design
- **严重性**: critical
- **断言类型**: text_contains engine._dispatcher
- **根因**: 断言2: text_contains 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "text_contains",
      "selector": "engine._dispatcher",
      "expected": "engine._dispatcher",
      "actual": "Assertion failed"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-doc-api-design_assert_fail.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-doc-api-design_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-doc-api-design_current.png"
  ],
  "first_failed_step": "断言2: text_contains 失败"
}

### 5. GET /api/specs/<spec> 返回单个 SPEC 完整详情 (出处: core/dashboard/server.py:17)

- **场景**: spec-detail-api-response
- **严重性**: critical
- **断言类型**: text_contains refactor-test-callsites
- **根因**: 断言2: text_contains 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "text_contains",
      "selector": "refactor-test-callsites",
      "expected": "refactor-test-callsites",
      "actual": "Assertion failed"
    },
    {
      "type": "text_contains",
      "selector": "depends_on",
      "expected": "depends_on",
      "actual": "Assertion failed"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-detail-api-response_assert_fail.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-detail-api-response_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-detail-api-response_current.png"
  ],
  "first_failed_step": "断言2: text_contains 失败"
}

### 6. fenixd.py 与 core/dashboard 的 import 调用语句无修改 (出处: openspec/changes/refactor-test-callsites/spec.md:22)

- **场景**: production-path-fenixd-import
- **严重性**: critical
- **断言类型**: element_visible .project-card, [data-testid='project-card'], .dark-Card
- **根因**: 步骤3: wait .project-card, [data-testid='project-card'], .dark-Card 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_visible",
      "selector": ".project-card, [data-testid='project-card'], .dark-Card",
      "expected": "visible",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\".project-card, [data-testid='project-card'], .dark-Card\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/production-path-fenixd-import_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/production-path-fenixd-import_current.png"
  ],
  "first_failed_step": "步骤3: wait .project-card, [data-testid='project-card'], .dark-Card 失败"
}

### 7. SSE 长连接正确建立，实时推送功能可用 (出处: core/dashboard/server.py:56-77)

- **场景**: sse-connection-establish
- **严重性**: critical
- **断言类型**: element_visible .sse-status, [data-testid='sse-status'], .connection-indicator
- **根因**: 步骤3: wait .sse-status, [data-testid='sse-status'], .connection-indicator 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_visible",
      "selector": ".sse-status, [data-testid='sse-status'], .connection-indicator",
      "expected": "visible",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\".sse-status, [data-testid='sse-status'], .connection-indicator\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/sse-connection-establish_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/sse-connection-establish_current.png"
  ],
  "first_failed_step": "步骤3: wait .sse-status, [data-testid='sse-status'], .connection-indicator 失败"
}

### 8. test-callsite-inventory.md 文件正确记录迁移计划与调用点统计 (出处: test-callsite-inventory.md)

- **场景**: test-callsite-inventory-display
- **严重性**: critical
- **断言类型**: element_visible text=test-callsite-inventory, text=迁移计划
- **根因**: 步骤3: wait text=test-callsite-inventory, text=迁移计划 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_visible",
      "selector": "text=test-callsite-inventory, text=迁移计划",
      "expected": "visible",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\"text=test-callsite-inventory, text=迁移计划\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/test-callsite-inventory-display_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/test-callsite-inventory-display_current.png"
  ],
  "first_failed_step": "步骤3: wait text=test-callsite-inventory, text=迁移计划 失败"
}

### 9. v1 多视图往返切换回归：概览→配置→运维记录→概览，验证前端模块级视图状态不残留、概览统计重新渲染。顶栏按钮 id 固定为 #btn-overview / #btn-config / #btn-activities（core/dashboard/static/index.html:25-28），页内不存在 #btn-ops 等其他按钮 id，不得发明选择器。出处：视图渲染/切换 core/dashboard/static/app.js:674-714。

- **场景**: v1-view-roundtrip-regression
- **严重性**: critical
- **断言类型**: element_clickable #btn-config
- **根因**: 步骤3: click #btn-config 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_clickable",
      "selector": "#btn-config",
      "expected": "clickable",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\"#btn-config\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/v1-view-roundtrip-regression_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/v1-view-roundtrip-regression_current.png"
  ],
  "first_failed_step": "步骤3: click #btn-config 失败"
}

### 10. SPEC 详情页加载回归：进入 SPEC 详情，验证标签页主体渲染。详情主体选择器为 .spec-tab-body（core/dashboard/static/app.js:1116-1163），页内不存在 .spec-head 元素；no_click_interception 仅可用于断言时仍在 DOM 的元素——.spec-row 被点击导航后已离开 DOM，不得对其实施该断言。出处：core/dashboard/static/app.js:1024、1116-1163。

- **场景**: regression-spec-detail
- **严重性**: critical
- **断言类型**: element_clickable text=refactor-test-callsites
- **根因**: 步骤3: click text=refactor-test-callsites 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_clickable",
      "selector": "text=refactor-test-callsites",
      "expected": "clickable",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\"text=refactor-test-callsites\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/regression-spec-detail_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/regression-spec-detail_current.png"
  ],
  "first_failed_step": "步骤3: click text=refactor-test-callsites 失败"
}

### 11. 概览页加载回归：验证重构后首屏统计瓦片与项目列表渲染正常。出处：core/dashboard/static/app.js:699-714 (.totals-row/.cards-grid)

- **场景**: regression-overview-load
- **严重性**: critical
- **断言类型**: element_visible .totals-row, [data-testid='totals-row']
- **根因**: 断言1: element_visible 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_visible",
      "selector": ".totals-row, [data-testid='totals-row']",
      "expected": "统计瓦片区域存在",
      "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\".totals-row, [data-testid='totals-row']\").first to be visible\n"
    },
    {
      "type": "element_visible",
      "selector": ".cards-grid, [data-testid='cards-grid']",
      "expected": "项目卡网格存在",
      "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\".cards-grid, [data-testid='cards-grid']\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/regression-overview-load_assert_fail.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/regression-overview-load_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/regression-overview-load_current.png"
  ],
  "first_failed_step": "断言1: element_visible 失败"
}

### 12. v1 概览页加载回归（生产面未受扰实证）：本 SPEC 仅改写 tests/ 调用点并删除零调用者门面委托方法，生产代码（fenixd.py 与 core/dashboard）零修改——dashboard 能启动并渲染统计瓦片与项目卡，即证明门面收缩后的 import 链与数据管道（/api/overview）零行为变化。pytest 基线核对由 commands.test 与实现侧分批门禁承担，浏览器场景承担最终用户可见面回归。navigate 出处：路径 / 由 core/dashboard/server.py:225 提供 index.html，默认端口 8787 见 core/dashboard/server.py:5；渲染逻辑 core/dashboard/static/app.js:699-714（.totals-row 统计瓦片、.cards-grid 项目卡）。

- **场景**: v1-overview-load-regression
- **严重性**: critical
- **断言类型**: element_visible .totals-row, [data-testid='totals-row']
- **根因**: 断言1: element_visible 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_visible",
      "selector": ".totals-row, [data-testid='totals-row']",
      "expected": "统计瓦片正常渲染",
      "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\".totals-row, [data-testid='totals-row']\").first to be visible\n"
    },
    {
      "type": "element_visible",
      "selector": ".cards-grid .card, [data-testid='cards-grid'] .card",
      "expected": "项目卡正常渲染",
      "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\".cards-grid .card, [data-testid='cards-grid'] .card\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/v1-overview-load-regression_assert_fail.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/v1-overview-load-regression_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/v1-overview-load-regression_current.png"
  ],
  "first_failed_step": "断言1: element_visible 失败"
}

### 13. v2 AMIS 概览页渲染回归：验证 AMIS 引擎正确渲染统计瓦片与项目面板。出处：core/dashboard/static/v2/pages/overview.json, core/dashboard/static/v2/app.js:451-468

- **场景**: regression-v2-overview
- **严重性**: critical
- **断言类型**: element_visible .v2-totals, [data-testid='v2-totals']
- **根因**: 断言1: element_visible 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_visible",
      "selector": ".v2-totals, [data-testid='v2-totals']",
      "expected": "v2 统计瓦片存在",
      "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\".v2-totals, [data-testid='v2-totals']\").first to be visible\n"
    },
    {
      "type": "element_visible",
      "selector": ".v2-proj-grid, [data-testid='v2-proj-grid']",
      "expected": "v2 项目面板存在",
      "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\".v2-proj-grid, [data-testid='v2-proj-grid']\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/regression-v2-overview_assert_fail.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/regression-v2-overview_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/regression-v2-overview_current.png"
  ],
  "first_failed_step": "断言1: element_visible 失败"
}

### 14. v2 概览页加载回归（AMIS 界面）：统计瓦片（.v2-totals）与项目面板（.v2-proj-grid）经 /api/overview、/api/projects 渲染，验证重构后同一套 API 在 v2 壳下的零行为变化。navigate 出处：静态服务 core/dashboard/server.py:233（/v2/index.html 走 _serve_static），瓦片 tpl 见 core/dashboard/static/v2/pages/overview.json（.v2-totals/.v2-stat-tile）。

- **场景**: v2-overview-load
- **严重性**: critical
- **断言类型**: element_visible .v2-totals, [data-testid='v2-totals']
- **根因**: 断言1: element_visible 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_visible",
      "selector": ".v2-totals, [data-testid='v2-totals']",
      "expected": "v2 统计瓦片正常渲染",
      "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\".v2-totals, [data-testid='v2-totals']\").first to be visible\n"
    },
    {
      "type": "element_visible",
      "selector": ".v2-proj-grid, [data-testid='v2-proj-grid']",
      "expected": "v2 项目面板正常渲染",
      "actual": "Locator.wait_for: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\".v2-proj-grid, [data-testid='v2-proj-grid']\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/v2-overview-load_assert_fail.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/v2-overview-load_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/v2-overview-load_current.png"
  ],
  "first_failed_step": "断言1: element_visible 失败"
}

### 15. v1 进入项目 SPEC 列表（正向路径）：点击概览第一个项目卡进入项目视图，渲染 SPEC 过滤器与列表（或「该项目暂无 SPEC」空状态）；本 SPEC 自身应出现在该列表中，即 reporting 链路（/api/specs）与状态机零行为变化的直接观测面。注意：点击 .cards-grid .card 导航后卡片已离开 DOM，no_click_interception 不得用于导航后已消失的元素。出处：项目卡 onclick nav('project/<name>') core/dashboard/static/app.js:743；项目视图渲染 app.js:917-990（.spec-filter / .spec-table-wrap / .empty-state）。

- **场景**: v1-project-enter-spec-list
- **严重性**: critical
- **断言类型**: element_clickable .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child
- **根因**: 步骤3: click .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_clickable",
      "selector": ".cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child",
      "expected": "clickable",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\".cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/v1-project-enter-spec-list_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/v1-project-enter-spec-list_current.png"
  ],
  "first_failed_step": "步骤3: click .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child 失败"
}

### 16. v1 打开 SPEC 详情（多步骤交互：概览→项目→SPEC 行）：点击列表第一行进入详情页，渲染标签页主体（verdict/验证/任务/场景等分区）。详情主体选择器为 .spec-tab-body（app.js:1116-1163），页内不存在 .spec-head；点击 .spec-row 导航后该行已离开 DOM，no_click_interception 不得用于其后置断言。出处：行 onclick nav('spec/<project>/<spec>') core/dashboard/static/app.js:1024。

- **场景**: v1-spec-detail-open
- **严重性**: critical
- **断言类型**: element_clickable .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child
- **根因**: 步骤3: click .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_clickable",
      "selector": ".cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child",
      "expected": "clickable",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\".cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/v1-spec-detail-open_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/v1-spec-detail-open_current.png"
  ],
  "first_failed_step": "步骤3: click .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child 失败"
}

### 17. 项目 SPEC 过滤器交互回归：进入项目视图后在 .spec-filter 容器内的搜索输入框 #spec-filter-q 输入关键字（app.js:969-975：容器内为 #spec-filter-q 文本框与 #spec-filter-status / #spec-filter-type 原生下拉，页内不存在 .dark-Select-option 等 AMIS 类），验证列表随之过滤或呈现空状态。出处：core/dashboard/static/app.js:917-990。

- **场景**: regression-spec-filter
- **严重性**: critical
- **断言类型**: element_clickable .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child
- **根因**: 步骤3: click .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_clickable",
      "selector": ".cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child",
      "expected": "clickable",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\".cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/regression-spec-filter_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/regression-spec-filter_current.png"
  ],
  "first_failed_step": "步骤3: click .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child 失败"
}

### 18. SPEC 详情页正确展示 refactor-test-callsites 的提案与设计文档 (出处: core/dashboard/server.py:17)

- **场景**: spec-detail-page-refactor-test-callsites
- **严重性**: critical
- **断言类型**: element_clickable text=refactor-test-callsites
- **根因**: 步骤3: click text=refactor-test-callsites 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_clickable",
      "selector": "text=refactor-test-callsites",
      "expected": "clickable",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\"text=refactor-test-callsites\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-detail-page-refactor-test-callsites_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-detail-page-refactor-test-callsites_current.png"
  ],
  "first_failed_step": "步骤3: click text=refactor-test-callsites 失败"
}

### 19. 告警生命周期记录正确展示 (出处: core/alert_lifecycle.py)

- **场景**: alert-lifecycle-display
- **严重性**: critical
- **断言类型**: element_clickable text=告警, text=Alerts, text=运维记录
- **根因**: 步骤3: click text=告警, text=Alerts, text=运维记录 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_clickable",
      "selector": "text=告警, text=Alerts, text=运维记录",
      "expected": "clickable",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\"text=告警, text=Alerts, text=运维记录\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/alert-lifecycle-display_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/alert-lifecycle-display_current.png"
  ],
  "first_failed_step": "步骤3: click text=告警, text=Alerts, text=运维记录 失败"
}

### 20. Proposal 文档内容正确渲染，包含 Why/What Changes/Impact 章节 (出处: openspec/changes/refactor-test-callsites/proposal.md)

- **场景**: spec-proposal-document-display
- **严重性**: critical
- **断言类型**: element_clickable text=refactor-test-callsites
- **根因**: 步骤3: click text=refactor-test-callsites 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_clickable",
      "selector": "text=refactor-test-callsites",
      "expected": "clickable",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\"text=refactor-test-callsites\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-proposal-document-display_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-proposal-document-display_current.png"
  ],
  "first_failed_step": "步骤3: click text=refactor-test-callsites 失败"
}

### 21. Design 文档正确展示组件命名与迁移计划 (出处: openspec/changes/refactor-test-callsites/design.md)

- **场景**: spec-design-document-display
- **严重性**: critical
- **断言类型**: element_clickable text=refactor-test-callsites
- **根因**: 步骤3: click text=refactor-test-callsites 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_clickable",
      "selector": "text=refactor-test-callsites",
      "expected": "clickable",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\"text=refactor-test-callsites\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-design-document-display_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-design-document-display_current.png"
  ],
  "first_failed_step": "步骤3: click text=refactor-test-callsites 失败"
}

### 22. SPEC 状态标签正确显示优先级与运行状态 (出处: core/dashboard/data.py)

- **场景**: spec-status-pills-display
- **严重性**: critical
- **断言类型**: element_visible .status-pill, [data-testid='status-pill'], .dark-Tag
- **根因**: 步骤3: wait .status-pill, [data-testid='status-pill'], .dark-Tag 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_visible",
      "selector": ".status-pill, [data-testid='status-pill'], .dark-Tag",
      "expected": "visible",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\".status-pill, [data-testid='status-pill'], .dark-Tag\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-status-pills-display_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-status-pills-display_current.png"
  ],
  "first_failed_step": "步骤3: wait .status-pill, [data-testid='status-pill'], .dark-Tag 失败"
}

### 23. SPEC 依赖链正确展示 refactor-core-packages 前置依赖 (出处: openspec/changes/refactor-test-callsites/proposal.md:29)

- **场景**: spec-dependency-chain-display
- **严重性**: critical
- **断言类型**: element_clickable text=refactor-test-callsites
- **根因**: 步骤3: click text=refactor-test-callsites 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_clickable",
      "selector": "text=refactor-test-callsites",
      "expected": "clickable",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\"text=refactor-test-callsites\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-dependency-chain-display_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/spec-dependency-chain-display_current.png"
  ],
  "first_failed_step": "步骤3: click text=refactor-test-callsites 失败"
}

### 24. 无运行记录时 SPEC 详情页正确显示空状态 (出处: core/dashboard/data.py)

- **场景**: empty-state-no-runs
- **严重性**: critical
- **断言类型**: element_clickable text=refactor-test-callsites
- **根因**: 步骤3: click text=refactor-test-callsites 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_clickable",
      "selector": "text=refactor-test-callsites",
      "expected": "clickable",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\"text=refactor-test-callsites\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/empty-state-no-runs_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/empty-state-no-runs_current.png"
  ],
  "first_failed_step": "步骤3: click text=refactor-test-callsites 失败"
}

### 25. 面包屑导航正确显示项目路径 (出处: core/dashboard/server.py)

- **场景**: breadcrumb-navigation
- **严重性**: critical
- **断言类型**: element_clickable text=refactor-test-callsites
- **根因**: 步骤3: click text=refactor-test-callsites 失败
- **证据**: {
  "failed_assertions": [
    {
      "type": "element_clickable",
      "selector": "text=refactor-test-callsites",
      "expected": "clickable",
      "actual": "Locator.wait_for: Timeout 5000ms exceeded.\nCall log:\n  - waiting for locator(\"text=refactor-test-callsites\").first to be visible\n"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/breadcrumb-navigation_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/breadcrumb-navigation_current.png"
  ],
  "first_failed_step": "步骤3: click text=refactor-test-callsites 失败"
}

## 警告列表

### 1. GET /api/projects 返回项目列表与聚合摘要 (出处: core/dashboard/server.py:14)

- **场景**: projects-api-response-structure
- **严重性**: minor
- **断言类型**: visual_diff api_projects_baseline
- **根因**: 视觉断言: api_projects_baseline ssim 低于阈值
- **证据**: {
  "failed_assertions": [
    {
      "type": "visual_diff",
      "selector": "api_projects_baseline",
      "expected": "ssim >= 0.95",
      "actual": "ssim = 0.8892251460404674"
    }
  ],
  "screenshots": [
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/projects-api-response-structure_diff.png",
    "/root/fenixd/.fenix/verify-progress/refactor-test-callsites/screenshots/projects-api-response-structure_current.png"
  ],
  "first_failed_step": "视觉断言: api_projects_baseline ssim 低于阈值"
}

## 场景详细分析

### dashboard-project-overview

- **状态**: fail
- **分类**: product-bug
- **描述**: Dashboard 项目概览页面正确展示项目列表与状态统计 (出处: core/dashboard/server.py:14-16)
- **首次失败步骤**: 步骤3: wait .project-card, [data-testid='project-card'], .dark-Card 失败
- **断言归因**:
  - element_visible .project-card, [data-testid='project-card'], .dark-Card: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator(".project-card, [data-testid='project-card'], .dark-Card").first to be visible
)

### overview-api-response-structure

- **状态**: fail
- **分类**: product-bug
- **描述**: GET /api/overview 返回正确的项目状态聚合结构 (出处: core/dashboard/server.py:15-16)
- **首次失败步骤**: 断言2: text_contains 失败
- **断言归因**:
  - text_contains projects: product-bug (Assertion failed)

### projects-api-response-structure

- **状态**: warning
- **分类**: flaky
- **描述**: GET /api/projects 返回项目列表与聚合摘要 (出处: core/dashboard/server.py:14)
- **首次失败步骤**: 视觉断言: api_projects_baseline ssim 低于阈值
- **断言归因**:
  - visual_diff api_projects_baseline: flaky (ssim 0.8892251460404674 below threshold 0.95)

### spec-doc-api-proposal

- **状态**: fail
- **分类**: product-bug
- **描述**: GET /api/spec-doc 正确返回 Proposal 文档原文 (出处: core/dashboard/server.py:20)
- **首次失败步骤**: 断言2: text_contains 失败
- **断言归因**:
  - text_contains 门面委托: product-bug (Assertion failed)

### spec-doc-api-design

- **状态**: fail
- **分类**: product-bug
- **描述**: GET /api/spec-doc 正确返回 Design 文档原文 (出处: core/dashboard/server.py:20)
- **首次失败步骤**: 断言2: text_contains 失败
- **断言归因**:
  - text_contains engine._dispatcher: product-bug (Assertion failed)

### spec-detail-api-response

- **状态**: fail
- **分类**: product-bug
- **描述**: GET /api/specs/<spec> 返回单个 SPEC 完整详情 (出处: core/dashboard/server.py:17)
- **首次失败步骤**: 断言2: text_contains 失败
- **断言归因**:
  - text_contains refactor-test-callsites: product-bug (Assertion failed)
  - text_contains depends_on: product-bug (Assertion failed)

### production-path-fenixd-import

- **状态**: fail
- **分类**: product-bug
- **描述**: fenixd.py 与 core/dashboard 的 import 调用语句无修改 (出处: openspec/changes/refactor-test-callsites/spec.md:22)
- **首次失败步骤**: 步骤3: wait .project-card, [data-testid='project-card'], .dark-Card 失败
- **断言归因**:
  - element_visible .project-card, [data-testid='project-card'], .dark-Card: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator(".project-card, [data-testid='project-card'], .dark-Card").first to be visible
)

### sse-connection-establish

- **状态**: fail
- **分类**: product-bug
- **描述**: SSE 长连接正确建立，实时推送功能可用 (出处: core/dashboard/server.py:56-77)
- **首次失败步骤**: 步骤3: wait .sse-status, [data-testid='sse-status'], .connection-indicator 失败
- **断言归因**:
  - element_visible .sse-status, [data-testid='sse-status'], .connection-indicator: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator(".sse-status, [data-testid='sse-status'], .connection-indicator").first to be visible
)

### test-callsite-inventory-display

- **状态**: fail
- **分类**: product-bug
- **描述**: test-callsite-inventory.md 文件正确记录迁移计划与调用点统计 (出处: test-callsite-inventory.md)
- **首次失败步骤**: 步骤3: wait text=test-callsite-inventory, text=迁移计划 失败
- **断言归因**:
  - element_visible text=test-callsite-inventory, text=迁移计划: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("text=test-callsite-inventory, text=迁移计划").first to be visible
)

### v1-view-roundtrip-regression

- **状态**: fail
- **分类**: product-bug
- **描述**: v1 多视图往返切换回归：概览→配置→运维记录→概览，验证前端模块级视图状态不残留、概览统计重新渲染。顶栏按钮 id 固定为 #btn-overview / #btn-config / #btn-activities（core/dashboard/static/index.html:25-28），页内不存在 #btn-ops 等其他按钮 id，不得发明选择器。出处：视图渲染/切换 core/dashboard/static/app.js:674-714。
- **首次失败步骤**: 步骤3: click #btn-config 失败
- **断言归因**:
  - element_clickable #btn-config: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("#btn-config").first to be visible
)

### regression-spec-detail

- **状态**: fail
- **分类**: product-bug
- **描述**: SPEC 详情页加载回归：进入 SPEC 详情，验证标签页主体渲染。详情主体选择器为 .spec-tab-body（core/dashboard/static/app.js:1116-1163），页内不存在 .spec-head 元素；no_click_interception 仅可用于断言时仍在 DOM 的元素——.spec-row 被点击导航后已离开 DOM，不得对其实施该断言。出处：core/dashboard/static/app.js:1024、1116-1163。
- **首次失败步骤**: 步骤3: click text=refactor-test-callsites 失败
- **断言归因**:
  - element_clickable text=refactor-test-callsites: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("text=refactor-test-callsites").first to be visible
)

### regression-overview-load

- **状态**: fail
- **分类**: product-bug
- **描述**: 概览页加载回归：验证重构后首屏统计瓦片与项目列表渲染正常。出处：core/dashboard/static/app.js:699-714 (.totals-row/.cards-grid)
- **首次失败步骤**: 断言1: element_visible 失败
- **断言归因**:
  - element_visible .totals-row, [data-testid='totals-row']: product-bug (Locator.wait_for: Timeout 3000ms exceeded.
Call log:
  - waiting for locator(".totals-row, [data-testid='totals-row']").first to be visible
)
  - element_visible .cards-grid, [data-testid='cards-grid']: product-bug (Locator.wait_for: Timeout 3000ms exceeded.
Call log:
  - waiting for locator(".cards-grid, [data-testid='cards-grid']").first to be visible
)

### v1-overview-load-regression

- **状态**: fail
- **分类**: product-bug
- **描述**: v1 概览页加载回归（生产面未受扰实证）：本 SPEC 仅改写 tests/ 调用点并删除零调用者门面委托方法，生产代码（fenixd.py 与 core/dashboard）零修改——dashboard 能启动并渲染统计瓦片与项目卡，即证明门面收缩后的 import 链与数据管道（/api/overview）零行为变化。pytest 基线核对由 commands.test 与实现侧分批门禁承担，浏览器场景承担最终用户可见面回归。navigate 出处：路径 / 由 core/dashboard/server.py:225 提供 index.html，默认端口 8787 见 core/dashboard/server.py:5；渲染逻辑 core/dashboard/static/app.js:699-714（.totals-row 统计瓦片、.cards-grid 项目卡）。
- **首次失败步骤**: 断言1: element_visible 失败
- **断言归因**:
  - element_visible .totals-row, [data-testid='totals-row']: product-bug (Locator.wait_for: Timeout 3000ms exceeded.
Call log:
  - waiting for locator(".totals-row, [data-testid='totals-row']").first to be visible
)
  - element_visible .cards-grid .card, [data-testid='cards-grid'] .card: product-bug (Locator.wait_for: Timeout 3000ms exceeded.
Call log:
  - waiting for locator(".cards-grid .card, [data-testid='cards-grid'] .card").first to be visible
)

### regression-v2-overview

- **状态**: fail
- **分类**: product-bug
- **描述**: v2 AMIS 概览页渲染回归：验证 AMIS 引擎正确渲染统计瓦片与项目面板。出处：core/dashboard/static/v2/pages/overview.json, core/dashboard/static/v2/app.js:451-468
- **首次失败步骤**: 断言1: element_visible 失败
- **断言归因**:
  - element_visible .v2-totals, [data-testid='v2-totals']: product-bug (Locator.wait_for: Timeout 3000ms exceeded.
Call log:
  - waiting for locator(".v2-totals, [data-testid='v2-totals']").first to be visible
)
  - element_visible .v2-proj-grid, [data-testid='v2-proj-grid']: product-bug (Locator.wait_for: Timeout 3000ms exceeded.
Call log:
  - waiting for locator(".v2-proj-grid, [data-testid='v2-proj-grid']").first to be visible
)

### v2-overview-load

- **状态**: fail
- **分类**: product-bug
- **描述**: v2 概览页加载回归（AMIS 界面）：统计瓦片（.v2-totals）与项目面板（.v2-proj-grid）经 /api/overview、/api/projects 渲染，验证重构后同一套 API 在 v2 壳下的零行为变化。navigate 出处：静态服务 core/dashboard/server.py:233（/v2/index.html 走 _serve_static），瓦片 tpl 见 core/dashboard/static/v2/pages/overview.json（.v2-totals/.v2-stat-tile）。
- **首次失败步骤**: 断言1: element_visible 失败
- **断言归因**:
  - element_visible .v2-totals, [data-testid='v2-totals']: product-bug (Locator.wait_for: Timeout 3000ms exceeded.
Call log:
  - waiting for locator(".v2-totals, [data-testid='v2-totals']").first to be visible
)
  - element_visible .v2-proj-grid, [data-testid='v2-proj-grid']: product-bug (Locator.wait_for: Timeout 3000ms exceeded.
Call log:
  - waiting for locator(".v2-proj-grid, [data-testid='v2-proj-grid']").first to be visible
)

### v1-project-enter-spec-list

- **状态**: fail
- **分类**: product-bug
- **描述**: v1 进入项目 SPEC 列表（正向路径）：点击概览第一个项目卡进入项目视图，渲染 SPEC 过滤器与列表（或「该项目暂无 SPEC」空状态）；本 SPEC 自身应出现在该列表中，即 reporting 链路（/api/specs）与状态机零行为变化的直接观测面。注意：点击 .cards-grid .card 导航后卡片已离开 DOM，no_click_interception 不得用于导航后已消失的元素。出处：项目卡 onclick nav('project/<name>') core/dashboard/static/app.js:743；项目视图渲染 app.js:917-990（.spec-filter / .spec-table-wrap / .empty-state）。
- **首次失败步骤**: 步骤3: click .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child 失败
- **断言归因**:
  - element_clickable .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator(".cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child").first to be visible
)

### v1-spec-detail-open

- **状态**: fail
- **分类**: product-bug
- **描述**: v1 打开 SPEC 详情（多步骤交互：概览→项目→SPEC 行）：点击列表第一行进入详情页，渲染标签页主体（verdict/验证/任务/场景等分区）。详情主体选择器为 .spec-tab-body（app.js:1116-1163），页内不存在 .spec-head；点击 .spec-row 导航后该行已离开 DOM，no_click_interception 不得用于其后置断言。出处：行 onclick nav('spec/<project>/<spec>') core/dashboard/static/app.js:1024。
- **首次失败步骤**: 步骤3: click .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child 失败
- **断言归因**:
  - element_clickable .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator(".cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child").first to be visible
)

### regression-spec-filter

- **状态**: fail
- **分类**: product-bug
- **描述**: 项目 SPEC 过滤器交互回归：进入项目视图后在 .spec-filter 容器内的搜索输入框 #spec-filter-q 输入关键字（app.js:969-975：容器内为 #spec-filter-q 文本框与 #spec-filter-status / #spec-filter-type 原生下拉，页内不存在 .dark-Select-option 等 AMIS 类），验证列表随之过滤或呈现空状态。出处：core/dashboard/static/app.js:917-990。
- **首次失败步骤**: 步骤3: click .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child 失败
- **断言归因**:
  - element_clickable .cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator(".cards-grid .card:first-child, [data-testid='cards-grid'] .card:first-child").first to be visible
)

### spec-detail-page-refactor-test-callsites

- **状态**: fail
- **分类**: product-bug
- **描述**: SPEC 详情页正确展示 refactor-test-callsites 的提案与设计文档 (出处: core/dashboard/server.py:17)
- **首次失败步骤**: 步骤3: click text=refactor-test-callsites 失败
- **断言归因**:
  - element_clickable text=refactor-test-callsites: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("text=refactor-test-callsites").first to be visible
)

### alert-lifecycle-display

- **状态**: fail
- **分类**: product-bug
- **描述**: 告警生命周期记录正确展示 (出处: core/alert_lifecycle.py)
- **首次失败步骤**: 步骤3: click text=告警, text=Alerts, text=运维记录 失败
- **断言归因**:
  - element_clickable text=告警, text=Alerts, text=运维记录: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("text=告警, text=Alerts, text=运维记录").first to be visible
)

### spec-proposal-document-display

- **状态**: fail
- **分类**: product-bug
- **描述**: Proposal 文档内容正确渲染，包含 Why/What Changes/Impact 章节 (出处: openspec/changes/refactor-test-callsites/proposal.md)
- **首次失败步骤**: 步骤3: click text=refactor-test-callsites 失败
- **断言归因**:
  - element_clickable text=refactor-test-callsites: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("text=refactor-test-callsites").first to be visible
)

### spec-design-document-display

- **状态**: fail
- **分类**: product-bug
- **描述**: Design 文档正确展示组件命名与迁移计划 (出处: openspec/changes/refactor-test-callsites/design.md)
- **首次失败步骤**: 步骤3: click text=refactor-test-callsites 失败
- **断言归因**:
  - element_clickable text=refactor-test-callsites: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("text=refactor-test-callsites").first to be visible
)

### spec-status-pills-display

- **状态**: fail
- **分类**: product-bug
- **描述**: SPEC 状态标签正确显示优先级与运行状态 (出处: core/dashboard/data.py)
- **首次失败步骤**: 步骤3: wait .status-pill, [data-testid='status-pill'], .dark-Tag 失败
- **断言归因**:
  - element_visible .status-pill, [data-testid='status-pill'], .dark-Tag: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator(".status-pill, [data-testid='status-pill'], .dark-Tag").first to be visible
)

### spec-dependency-chain-display

- **状态**: fail
- **分类**: product-bug
- **描述**: SPEC 依赖链正确展示 refactor-core-packages 前置依赖 (出处: openspec/changes/refactor-test-callsites/proposal.md:29)
- **首次失败步骤**: 步骤3: click text=refactor-test-callsites 失败
- **断言归因**:
  - element_clickable text=refactor-test-callsites: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("text=refactor-test-callsites").first to be visible
)

### empty-state-no-runs

- **状态**: fail
- **分类**: product-bug
- **描述**: 无运行记录时 SPEC 详情页正确显示空状态 (出处: core/dashboard/data.py)
- **首次失败步骤**: 步骤3: click text=refactor-test-callsites 失败
- **断言归因**:
  - element_clickable text=refactor-test-callsites: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("text=refactor-test-callsites").first to be visible
)

### breadcrumb-navigation

- **状态**: fail
- **分类**: product-bug
- **描述**: 面包屑导航正确显示项目路径 (出处: core/dashboard/server.py)
- **首次失败步骤**: 步骤3: click text=refactor-test-callsites 失败
- **断言归因**:
  - element_clickable text=refactor-test-callsites: product-bug (Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("text=refactor-test-callsites").first to be visible
)

## 本轮场景集变更

场景集与持久化集一致，无变更。

