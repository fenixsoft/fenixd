# 验证报告：add-fast-track-mode

**验证时间**：2026-09-02T04:13:57Z  
**验证结果**：❌ 未通过（bug-found）  
**总结**：共 7 个场景，3 通过，4 失败。发现 1 个系统性产品缺陷（major），阻塞本变更核心交付。

---

## 裁决结论

本变更的 Dashboard 模式标记能力（spec 列表与详情页展示 fast-track/full 执行模式标签）**整体未实现**，属于产品代码缺失。

### 影响范围

以下 SPEC 要求均未落实：

| 要求 | 说明 | 来源 |
|------|------|------|
| 详情页 fast-track 模式标签 | mode=fast-track 时，标题区域应渲染「fast-track」/「快速」/「快速路径」ant-tag | 本变更新增能力 |
| 详情页 full 模式标签 | mode=full 时，标题区域应渲染「完整」/「full」/「完整模式」ant-tag | 本变更新增能力 |
| 存量 spec 缺省 full 展示 | 无 mode 字段时按缺省 full 展示等价标签 | fast-track-mode-selection/spec.md:33-35 |
| 列表页与详情页模式标记统一 | spec 列表与详情页 SHALL 展示模式标记 | fast-track-mode-selection/spec.md:37-39 |

---

## Bug：Dashboard 模式标记 UI 整体缺失

**严重程度**：major  
**分类**：product-bug  
**影响场景**：4 个（detail-fast-track-mode-tag、detail-full-mode-tag、detail-legacy-default-mode、detail-fast-track-distinct-from-full）

### 现象

- 详情页标题区域 `.ant-page-header-heading-title` 正常加载（每个场景第一个断言通过）
- 但在标题区域内断言 `ant-tag` 模式标记标签时，等待 3000ms 后超时——元素从未存在于 DOM
- 页面其余部分（标题文字、状态标签、返回按钮、控制台日志）均正常，无级联影响

### 根因

前端代码**完全缺失**模式标记渲染能力，具体表现为三个层面的缺失：

1. **服务层**：`services/dashboard.ts` 的 SpecEntry 类型无 `mode` 字段定义
2. **视图层**：`pages/projects/detail.tsx` 全文无 mode/fast-track/完整 标签渲染代码；`list.tsx` 中 `mode` 仅出现于 antd Select 组件的无关属性
3. **构建产物**：`dist/p__projects__detail.*.async.js` 中 `完整`/`快速路径`/`fast-track` 字符串搜索结果为零

前置变更（add-v3-spec-quick-switch）在 detail.tsx 中新增了「下拉快速切换」功能，该变更的 Dashboard 模式标记能力未随实现推进。

### 失败断言明细

| 场景 | 断言层 | 选择器 | 期望 | 实际 | 分类 |
|------|--------|--------|------|------|------|
| detail-fast-track-mode-tag | Layer 1 | `.ant-page-header-heading-title .ant-tag:has-text('fast-track')` | 标签可见 | 超时，元素不存在 | product-bug |
| detail-full-mode-tag | Layer 1 | `.ant-page-header-heading-title .ant-tag:has-text('完整')` | 标签可见 | 超时，元素不存在 | product-bug |
| detail-legacy-default-mode | Layer 1 | `.ant-page-header-heading-title .ant-tag:has-text('完整')` | 缺省 full 标记可见 | 超时，元素不存在 | product-bug |
| detail-fast-track-distinct-from-full | Layer 1 | `.ant-page-header-heading-title .ant-tag:has-text('完整')` | 第二页 full 标签可见 | 超时，元素不存在 | product-bug |

**断言证据截图**（4 张，均位于 verify-progress/add-fast-track-mode/screenshots/）：
- `detail-fast-track-mode-tag_assert_fail.png`
- `detail-full-mode-tag_assert_fail.png`
- `detail-legacy-default-mode_assert_fail.png`
- `detail-fast-track-distinct-from-full_assert_fail.png`

### 关联 Spec 要求

- fast-track-mode-selection/spec.md:37-44（Dashboard 模式标记：列表与详情页 SHALL 展示执行模式）
- fast-track-mode-selection/spec.md:33-35（存量 spec 缺省 full）
- 本变更 proposal.md "Dashboard 模式标记"：spec 列表与详情页展示执行模式（fast-track / full）

---

## 通过场景一览

| 场景 | 描述 | 状态 |
|------|------|------|
| `list-mode-column-visible` | 列表页 spec 表格正常渲染，add-fast-track-mode 行可见（真实数据锚点） | ✅ pass |
| `regression-detail-existing-spec` | 真实 spec add-fast-track-mode 详情页标题、状态标签、描述区正常渲染 | ✅ pass |
| `regression-list-page-renders` | fenixd 项目列表页表格、搜索框、标题正常加载，无 console error | ✅ pass |

---

## 结论

本变更验证**未通过**。fast-track 模式的 Dashboard 模式标记能力（spec 列表与详情页渲染 fast-track/full 标签，以及存量 spec 缺省 full 标记展示）未实现，4 个验证场景全部失败，属同一系统性产品缺陷。需在 `pages/projects/detail.tsx` 和 `pages/projects/list.tsx` 中新增 mode 标签渲染逻辑，并在 `services/dashboard.ts` 的 SpecEntry 类型中补充 `mode` 字段，构建 dist 后重新验证。

## 本轮场景集变更

当前稳定场景集共 7 个（第 1 轮）。

- 首轮写入 7 个场景

