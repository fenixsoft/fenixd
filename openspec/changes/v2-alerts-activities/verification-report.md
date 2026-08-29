# 验证报告 - v2-alerts-activities

**验证时间**: 2026-08-29T11:16:11Z  
**验证结果**: ❌ Bug Found (3个产品Bug，2个测试问题，1个环境问题)

---

## 📊 总览

| 指标 | 数量 |
|------|------|
| 总场景数 | 11 |
| ✅ 通过 | 5 |
| ❌ 失败 | 6 |
| 🐛 产品Bug | 3 |
| ⚠️ 测试设计问题 | 1 |
| 🔧 环境问题 | 2 |

---

## 🐛 产品 Bug（需修复）

### Bug 1: 告警横幅 Toggle 列表功能失效 [CRITICAL]

**影响场景**: `alert-banner-expand-list`

**问题描述**:  
点击 `#alert-toggle` 按钮后，`#alert-list` 容器仍保持 `hidden` 类，列表无法展开显示告警项。

**断言失败**:
- `element_visible` (Layer 1): `#alert-list` — 超时 3000ms，元素仍为 hidden
- `element_visible` (Layer 1): `#alert-list .alert-item` — 超时 3000ms，元素仍为 hidden

**证据**:
```
Locator.wait_for: Timeout 3000ms exceeded.
Call log:
  - waiting for locator("#alert-list").first to be visible
    10 × locator resolved to hidden <div id="alert-list" class="alert-list hidden">…</div>
```

**根因推断**:  
toggle hidden 类的逻辑未生效。可能是：
1. `#alert-toggle` 的事件委托未正确绑定
2. toggle 逻辑存在条件判断错误
3. CSS 类操作被覆盖或阻止

**参考代码**: `core/dashboard/static/app.js:378`（事件委托 toggle）、`app.js:383`（toggle hidden）

---

### Bug 2: 标记已处理按钮乐观移除失败 [MAJOR]

**影响场景**: `alert-banner-handle-single`, `activities-mark-handled-inline`

**问题描述**:  
点击"标记已处理"按钮后，该行未从 DOM 移除，乐观更新未生效。影响告警横幅和运维记录两个页面。

**断言失败**:
- `element_not_exist` (Layer 1): `.alert-handled-btn[data-id='a1']` — 实际数量 1，期望 0
- `element_not_exist` (Layer 1): `.activity-handled-btn[data-id='e9']` — 实际数量 1，期望 0

**证据**:
```
期望: element_not_exist
实际: actual_count = 1 (元素仍存在)
```

**根因推断**:  
`markAlertHandled` 函数的乐观移除（`row.remove`）未执行。可能是：
1. 事件委托路径不匹配
2. `remove()` 调用被跳过（条件判断问题）
3. DOM 操作被异步覆盖

**参考代码**: `core/dashboard/static/app.js:344`（markAlertHandled）、`app.js:352`（row.remove 乐观移除）

---

### Bug 3: 单项目路由页面缺少预期文案 [MAJOR]

**影响场景**: `activities-single-project-route`

**问题描述**:  
导航到 `#/activities/fenixd` 后，页面标题可见但不包含预期的 "fenixd" 和 "仅 fenixd 活动" 文案。

**断言失败**:
- `text_contains` (Layer 3): "fenixd" — 未找到
- `text_contains` (Layer 3): "仅 fenixd 活动" — 未找到

**证据**:
```
路由: #/activities/fenixd
页面标题: 可见
缺失文案: ["fenixd", "仅 fenixd 活动"]
```

**根因推断**:  
单项目路由渲染分支未正确拼接项目名到标题文案。可能是：
1. 路由解析未正确提取 `:project` 参数
2. 标题模板缺少项目名插值
3. API 请求参数传递错误

**参考代码**: `core/dashboard/static/app.js:120`（parseHash activities）、`app.js:452`（单项目渲染分支）

---

## ⚠️ 测试设计问题（非产品Bug）

### alert-banner-empty-hidden

**问题**: 测试断言与场景语义矛盾

**详情**:
- 场景描述明确："无告警环境：横幅不可见（带 hidden 类）"
- 但第1层断言 `element_visible` 期望 `#alert-banner` 可见
- 第3层断言 `attribute_match` 期望 `class='hidden'`，但实际是 `class='alert-banner hidden'`（多类名是正常行为）

**建议**: 调整测试断言，改为验证元素存在且带 hidden 类，而非验证元素可见。

---

## 🔧 环境/隔离问题（非产品Bug）

### alert-banner-clear-all-accept

**问题**: Mock 数据导致横幅隐藏，按钮不可见

**详情**:
- Mock 返回空数据 → 横幅带 hidden 类 → `#alert-clear-all` 按钮不可见
- 步骤 `click #alert-clear-all` 超时找不到可见元素

**建议**: 检查 mock 配置，确保返回非空告警数据。

---

## ✅ 通过的场景

| 场景ID | 描述 |
|--------|------|
| `alert-banner-show-count` | 有未处理告警时横幅显示条数 |
| `activities-page-render-timeline` | 运维记录页时间线组件渲染 |
| `activities-page-empty-state` | 运维记录页空态显示 |
| `alert-banner-clear-all-dismiss` | 清空取消后告警项仍在 |
| `activities-tab-switch` | 运维记录跨项目页签切换 |

---

## 📋 修复优先级

1. **[P0] Bug 1**: Toggle 列表功能失效 — 核心交互功能完全不可用
2. **[P1] Bug 2**: 标记已处理乐观移除失败 — 影响两个主要页面
3. **[P1] Bug 3**: 单项目路由文案缺失 — 用户体验问题

---

**生成工具**: Fenix Planner Agent  
**验证引擎**: Playwright + Mock API
