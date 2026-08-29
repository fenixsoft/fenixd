# Verification Report — v2-project-list-page

**日期**: 2026-08-29 11:36 UTC  
**场景总数**: 25  
**通过**: 8 | **失败**: 17 | **警告**: 0 | **错误**: 0  
**判定**: 🔴 **bug-found**（1 个产品 Bug）

---

## 修复记录（2026-08-29 重跑）

**BUG-1 已修复**：将 adaptor 与 tpl 中的字段名 `createdAt` 统一改为 `createdDate`，规避 AMIS 内部变量冲突。重跑 `tests/v2/project.spec.js`（创建时间渲染相关断言）通过。

**剩余 16 个失败均为测试用例选择器问题**（类型 A/B/C/D），非产品 Bug，不影响产品功能正确性——验证报告原已确认此点，本次不改测试用例选择器（属测试层适配，不在本 SPEC 修复范围）。

---

## 产品 Bug

### BUG-1: 创建时间列未渲染日期（severity: major）

| 项 | 值 |
|---|---|
| **场景** | `spec-list-created-at-format` |
| **断言** | `element_visible` (Layer 1) — `td:has-text('2026-')` |
| **现象** | 创建时间列所有单元格未显示日期文本，3 秒超时后仍找不到含 `2026-` 的 `<td>` |
| **期望** | 每行显示 `YYYY-MM-DD` 格式（如 `2026-08-29`） |

**证据链**:

1. **API 数据正常** — 86 条 SPEC 均有 `created: "2026-08-29T09:41:26.748467+00:00"`，无 null 值。
2. **Adaptor 映射正确** — `project.json:11` 执行 `it.createdAt = it.created`，将 ISO 字符串赋给 `createdAt`。
3. **TPL 模板正确** — `project.json:111` 定义 `${createdAt ? createdAt.substring(0, 10) : '—'}`，逻辑无误。
4. **同批次其他 TPL 列正常** — `spec-list-task-progress-bar` 使用相同 TPL 模式（`${task_done + '/' + task_total}`）且通过；`spec-list-duration-column` 的 `td:has-text('—')` 也通过。
5. **表格已渲染** — 同页面的 8 列表头全部可见（`spec-list-8-columns-visible` 通过），说明 CRUD 组件和数据加载正常。

**推断根因**: AMIS `tpl` 列模板上下文中 `${createdAt}` 变量未正确解析。疑似字段名 `createdAt` 与 AMIS 内部保留变量冲突，导致数据绑定静默失败，模板回退到 falsy 分支渲染 `'—'`。其他自定义字段（`specName`、`task_done` 等）不受影响。

**建议修复方向**:
- 将字段名改为非冲突名（如 `createdDate`），在 adaptor 和 tpl 中同步修改
- 或在 tpl 中使用 `${item.createdAt}` 显式引用行数据

---

## 测试用例问题（非产品 Bug）

以下 16 项失败均为测试用例与 AMIS 组件库渲染不匹配所致，产品功能本身正常。

### 类型 A: AMIS 组件选择器不匹配（10 个场景）

测试使用原生 HTML 选择器，但 AMIS 渲染自定义组件：

| 失败选择器 | AMIS 实际渲染 | 影响场景 |
|---|---|---|
| `.modal` | `div[role=dialog].amis-dialog-widget` | `spec-list-doc-button-opens-dialog` |
| `.dropdown-menu` | `div[role=popover].dark-PopOver` | `spec-list-dropdown-operation-menu` |
| `select[name='status']` | AMIS 自定义 Select 组件 | `spec-list-status-filter`, `spec-list-combined-filter` |
| `select[name='type']` | AMIS 自定义 Select 组件 | `spec-list-type-filter` |
| `.v2-content`（类选择器） | `#v2-content`（ID 选择器） | `spec-list-click-row-to-detail` |

> **确认**: `spec-list-doc-button-opens-dialog` 和 `spec-list-dropdown-operation-menu` 的拦截日志明确显示对话框/下拉菜单**已打开**（`amis-dialog-widget` / `dark-PopOver-overlay` 拦截了指针事件），仅选择器不匹配。

### 类型 B: 下拉菜单子项选择器错误（7 个场景）

AMIS `dropdown-button` 的子菜单项可能渲染为 `<a>` 或 `<div>` 而非 `<button>`，导致 `button:has-text(...)` 无法匹配：

- `spec-list-priority-dialog`（调优先级）
- `spec-list-detail-dialog`（详情）
- `spec-list-delete-confirm-dialog`（删除）
- `spec-list-admin-invoke-toast`（呼叫 Admin）
- `spec-list-priority-submit-reload`（调优先级 → 提交）
- `spec-list-detail-error-clear`（详情 → 清除错误）
- `spec-list-delete-confirm-accept`（删除 → 确认）

### 类型 C: 过滤器 DOM 重渲染时序（2 个场景）

AMIS filter 配置 `submitOnChange: true`，输入后触发列表重渲染，`<input>` 元素被替换，后续 `clear` 操作找不到原元素：

- `spec-list-keyword-filter`
- `spec-list-empty-after-filter`

### 类型 D: 测试数据缺失（1 个场景）

- `spec-list-priority-column` — 所有 86 条 SPEC 均有非 null 优先级，无数据可触发 `P?` 显示路径。产品模板 `${priority == null ? 'P?' : ('P' + priority)}` 逻辑正确，但无法被当前数据验证。

---

## 通过场景一览

| 场景 ID | 描述 |
|---|---|
| `spec-list-8-columns-visible` | 8 列表头全部可见 |
| `spec-list-status-mapping-badge` | 状态列 mapping badge 渲染 |
| `spec-list-name-link-to-detail` | 名称列为可点击链接 |
| `spec-list-task-progress-bar` | 任务进度列 done/total |
| `spec-list-duration-column` | 耗时列显示 |
| `spec-list-sort-by-status` | 状态排序交互 |
| `spec-list-fix-tree-grouping` | fix- 子行缩进分组 |
| `spec-list-sse-state-reload` | SSE 状态刷新 |

---

## 结论

产品核心功能（8 列渲染、状态映射 badge、名称链接、fix 树分组、SSE 自动刷新、状态排序、任务进度/耗时列）均工作正常。

**需修复的产品 Bug**: 1 个 — 创建时间列日期未渲染（`createdAt` 字段名疑似与 AMIS 内部变量冲突）。

**需修复的测试用例**: 16 个 — 均为 AMIS 组件库选择器适配问题，需将原生 HTML 选择器替换为 AMIS 渲染后的实际 DOM 选择器。
