# 验证报告：fix-fix-fix-add-spec-context-menu

**验证时间**：2026-08-28T16:30:39Z
**验证引擎**：Fenix 浏览器端到端验证
**验证结论**：❌ 验证未通过（发现产品 Bug）

---

## 总览

| 指标 | 数值 |
|------|------|
| 场景总数 | 20 |
| 通过 | 1 |
| 失败 | 19 |
| 警告 | 0 |
| 错误 | 0 |
| 环境阻塞 | 0 |

仅 `ctx-menu-non-target-no-show`（回归：非目标区域右键不弹出自绘菜单）通过。

---

## 发现的产品 Bug

### Bug #1 [Critical] 右键菜单功能完全不可用（系统性问题）

**影响范围**：17 个场景（占失败场景 89.5%）

**受影响的场景**：
- `ctx-menu-open-and-render`
- `ctx-menu-close-on-esc`
- `ctx-menu-close-on-outside-click`
- `ctx-menu-viewport-flip-no-overflow`
- `ctx-menu-delete-success-row-removed`
- `ctx-menu-delete-info-row-removed`
- `ctx-menu-delete-cancel-no-change`
- `ctx-menu-admin-invoke-success`
- `ctx-menu-admin-invoke-no-error`
- `ctx-menu-priority-apply-success`
- `ctx-menu-priority-cancel-noop`
- `ctx-menu-delete-409-running`
- `ctx-menu-admin-invoke-409-conflict`
- `ctx-menu-priority-boundary-values`
- `ctx-menu-multi-spec-target-different`
- `ctx-menu-scroll-closes-menu`
- `ctx-menu-admin-invoke-500-server-error`
- `ctx-menu-delete-500-server-error`

**断言类型**：第1-2层 `element_not_found_or_not_actionable`

**现象**：所有场景在执行 `contextmenu` 步骤时超时失败，选择器 `.spec-name-cell[data-spec='<spec-id>']` 始终不可见。

**错误信息**：
```
Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator(".spec-name-cell[data-spec='live-spec']").first to be visible
```

**根因推断**：前端未正确渲染 spec 名称单元格。代码 `core/dashboard/static/app.js:2673 initSpecContextMenu` 监听 `.spec-name-cell[data-spec]` 选择器，但页面上该元素不存在。可能原因：
1. Mock API 返回的 specs 数据格式与前端期望不匹配；
2. 前端 `renderSpecs`/`renderProject` 渲染逻辑未生成带 `data-spec` 属性的单元格；
3. 项目选择流程（点击 `.card`）未正确触发 spec 列表加载。

**证据**：17 个场景在点击 `.card` 进入项目视图后，均无法找到任何 `.spec-name-cell[data-spec]` 元素。

---

### Bug #2 [Major] 空状态未正确显示

**影响范围**：1 个场景 `project-spec-empty-state`

**断言类型**：第1层 `element_visible` + 第3层 `text_contains` / `element_not_exist`

**现象**：当项目无 SPEC 时，应显示 `.empty-state` 提示「该项目暂无 SPEC」，但实际页面中：
- `.empty-state` 元素不可见（超时 3000ms）
- 文字「暂无 SPEC」不存在
- `.spec-table` 元素实际存在（预期不应存在）

**根因推断**：前端 `core/dashboard/static/app.js:842 renderProject` 在 `specs` 为空时应返回空状态 HTML，但实际返回了 spec 表格。说明 specs 数组空判断逻辑有误，或 mock 的空数据被错误处理。

**证据**：
```json
{
  "type": "element_visible",
  "selector": ".empty-state",
  "pass": false,
  "error": "Locator.wait_for: Timeout 3000ms exceeded"
}
{
  "type": "element_not_exist",
  "selector": ".spec-table",
  "actual_count": 1,
  "pass": false
}
```

---

## 通过场景

| 场景 ID | 说明 |
|---------|------|
| `ctx-menu-non-target-no-show` | 在表头等非 spec 行区域右键不弹出自绘菜单（原生默认行为）✅ |

---

## 验证结论

**验证未通过。** 发现 1 个 Critical 级系统性问题（spec 名称单元格未渲染，导致右键上下文菜单功能完全不可用，影响 17 个场景）和 1 个 Major 级问题（空状态未正确显示）。

这两个 Bug 具有共同根因特征——**前端渲染层未正确生成 spec 相关 DOM 结构**，建议优先检查 `renderProject` / `renderSpecs` 的渲染逻辑与 mock 数据格式的兼容性，修复后重新运行验证。
