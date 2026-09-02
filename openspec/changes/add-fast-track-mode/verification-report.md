# 验证报告：add-fast-track-mode

**验证时间**：2026-09-02T08:18:34Z
**验证结果**：❌ 未通过（bug-found）
**总结**：共 7 个场景（冻结集全部覆盖），1 通过，2 warning（flaky，不阻塞），4 失败。发现 1 个系统性产品缺陷（major，同一根因影响 4 个场景），阻塞详情页模式标记交付。

---

## 裁决结论

修复轮验证：详情页模式标记能力**仍缺失**。与上一轮不同，源码 `pages/projects/detail.tsx:346-350` **已实现**模式标记 Tag（`detail?.mode === "fast-track" ? "fast-track" : "完整模式"`），但运行时静态产物 `dist/p__projects__detail.8b580bd6.async.js` **未包含**该代码——推断为前端构建产物过期（源码已改但未重新 build）。

### 影响范围

| 要求 | 说明 | 当前状态 |
|------|------|------|
| 详情页 fast-track 模式标签 | mode=fast-track 时，标题区域应渲染「fast-track」ant-tag | ❌ 未生效（源码已实现，产物缺失） |
| 详情页 full 模式标签 | mode=full 时，标题区域应渲染「完整模式」ant-tag | ❌ 未生效（源码已实现，产物缺失） |
| 存量 spec 缺省 full 展示 | 无 mode 字段时按缺省 full 展示等价标签 | ❌ 未生效（源码已实现，产物缺失） |
| 列表页模式标记 | spec 列表行展示模式标记 | ✅ 正常（真实 spec 行「完整模式」标签断言通过） |

---

## Bug：详情页模式标记未生效（构建产物过期）

**严重程度**：major
**分类**：product-bug
**影响场景**：4 个（detail-fast-track-mode-tag、detail-full-mode-tag、detail-legacy-default-mode、detail-fast-track-distinct-from-full）

### 现象

- 详情页标题区域 `.ant-page-header-heading-title` 正常加载（每个场景第一个断言通过）
- 但在标题区域内断言模式标记 `ant-tag`（fast-track / 完整模式）时，等待 3000ms 后超时——元素从未存在于 DOM
- 页面其余部分（标题文字、返回按钮、状态标签、无 console error）均正常，无级联影响
- 列表页真实 spec 行（`tbody tr:has-text('add-fast-track-mode') .ant-tag:has-text('完整模式')`）断言**通过**——列表 chunk 已含模式标记

### 根因

源码 `core/dashboard/static/v3/src/pages/projects/detail.tsx:346-350` 已实现模式标记 Tag（task 7.2），但运行时静态产物 `/root/fenixd/core/dashboard/static/v3/dist/p__projects__detail.8b580bd6.async.js` 经全量 grep **不含** `"fast-track"`、**不含** `"完整模式"` 及其 unicode 转义（唯一 `u5B8C` 命中为 ProgressBarTile 的「已完成」文案），即详情页 chunk 未包含模式标记代码；同在 dist 的列表 chunk `p__projects__list.e54fa56d.async.js` 含模式标记，故列表页断言通过。推断为前端构建产物过期（源码已改但未重新 build，或构建未包含详情页 chunk 更新）。

### 失败断言明细

| 场景 | 断言层 | 选择器 | 期望 | 实际 | 分类 |
|------|--------|--------|------|------|------|
| detail-fast-track-mode-tag | Layer 1 | `.ant-page-header-heading-title .ant-tag:has-text('fast-track')` | 标签可见 | 超时，元素不存在 | product-bug |
| detail-full-mode-tag | Layer 1 | `.ant-page-header-heading-title .ant-tag:has-text('完整模式')` | 标签可见 | 超时，元素不存在 | product-bug |
| detail-legacy-default-mode | Layer 1 | `.ant-page-header-heading-title .ant-tag:has-text('完整模式')` | 缺省 full 标记可见 | 超时，元素不存在 | product-bug |
| detail-fast-track-distinct-from-full | Layer 1 | `.ant-page-header-heading-title .ant-tag:has-text('完整模式')` | 第二页 full 标签可见 | 超时，元素不存在 | product-bug |

**断言证据截图**（4 张，均位于 verify-progress/add-fast-track-mode/screenshots/）：
- `detail-fast-track-mode-tag_assert_fail.png`
- `detail-full-mode-tag_assert_fail.png`
- `detail-legacy-default-mode_assert_fail.png`
- `detail-fast-track-distinct-from-full_assert_fail.png`

### 关联 Spec 要求

- fast-track-mode-selection/spec.md:33-35（存量 spec 缺省 full）
- fast-track-mode-selection/spec.md:39-44（fast-track 与 full 可辨识）

---

## 非阻塞场景（warning，flaky）

| 场景 | 说明 | 判定 |
|------|------|------|
| `list-mode-column-visible` | 列表页 spec 表格、真实 spec 行、模式标记标签全部功能断言通过；视觉对比 SSIM 0.8692（<0.95 且 >0.85 warn 阈值）因列表页 SSE 实时刷新动态内容 | ⚠️ flaky，不记产品 Bug |
| `regression-list-page-renders` | 列表页标题、表格、搜索框全部功能断言通过；SSIM 0.8692 与上场景完全一致，佐证为 SSE 动态内容系统性轻微差异 | ⚠️ flaky，不记产品 Bug |

## 通过场景一览

| 场景 | 描述 | 状态 |
|------|------|------|
| `regression-detail-existing-spec` | 真实 spec add-fast-track-mode 详情页标题、状态标签、描述区正常渲染，无回归 | ✅ pass |

---

## 结论

本变更验证**未通过**。fast-track 模式的详情页模式标记能力（fast-track/完整模式/存量缺省 full 标签）未生效，4 个验证场景全部失败，属同一系统性缺陷：**详情页构建产物 chunk 未包含模式标记代码**（源码已实现，dist 过期）。列表页模式标记功能正常。需重新构建前端产物（确认 `dist/p__projects__detail.*.async.js` 包含模式标记代码）后重新验证详情页模式标记。

## 本轮场景集变更

当前稳定场景集共 7 个（修复轮复用，无新增、无移除）。

- 修复轮沿用既有 7 场景冻结集，MUST NOT 扩容，全部覆盖
