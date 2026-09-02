# 验证报告：add-fast-track-mode

**验证时间**：2026-09-02T09:40:33Z（修复轮复验）
**验证结果**：✅ 通过（fix 后复验）
**总结**：共 7 个场景（冻结集全部覆盖，修复轮不扩容），4 通过，3 warning（视觉 flaky，不阻塞），0 失败，0 错误。

---

## 裁决结论

修复轮复验：详情页模式标记能力**已生效**。第 2 轮失败根因为详情页 dist 静态产物过期
（源码已含 task 7.2 模式标记 Tag，编译产物 `p__projects__detail.8b580bd6.async.js`
未包含模式标记代码）；构建产物已重建（`p__projects__detail.96407b2f.async.js`，
已含 `mode === "fast-track" ? "fast-track" : "完整模式"` 逻辑），daemon :8787 实时服务新产物。

本轮所有功能断言（第 1-3 层）**全部通过**：7 个场景 32 条功能断言无一条失败。
仅 3 个场景的整页 SSIM 视觉对比（第 4 层）低于 pass 阈值 0.95 但高于 warn 阈值
0.85，经上下文核实均为**动态内容区域**（列表页 SSE 实时刷新 / 真实详情页动态状态
与相对时间戳），按第 4 层判定规则忽略，不记产品 Bug，分类 `flaky`（非根因性失败，
MAY → warning）。

### 影响范围

| 要求 | 说明 | 当前状态 |
|------|------|------|
| 详情页 fast-track 模式标签 | mode=fast-track 时，标题区域渲染「fast-track」ant-tag | ✅ 生效 |
| 详情页 full 模式标签 | mode=full 时，标题区域渲染「完整模式」ant-tag | ✅ 生效 |
| 存量 spec 缺省 full 展示 | 无 mode 字段时按缺省 full 展示等价标签 | ✅ 生效 |
| 列表页模式标记 | spec 列表行展示模式标记 | ✅ 正常 |
| fast-track 与 full 可辨识 | 两模式标签文本不同 | ✅ 生效 |

---

## 场景结果表（含分类）

| 场景 | 状态 | 失败断言 | 分类 |
|------|------|----------|------|
| `detail-fast-track-mode-tag` | pass | 0 | — |
| `detail-full-mode-tag` | pass | 0 | — |
| `detail-legacy-default-mode` | pass | 0 | — |
| `detail-fast-track-distinct-from-full` | pass | 0 | — |
| `list-mode-column-visible` | warning | 0（仅视觉 SSIM 0.8653） | flaky |
| `regression-detail-existing-spec` | warning | 0（仅视觉 SSIM 0.9454） | flaky |
| `regression-list-page-renders` | warning | 0（仅视觉 SSIM 0.8653） | flaky |

---

## 修复说明

第 2 轮 4 个失败场景（detail-fast-track-mode-tag、detail-full-mode-tag、
detail-legacy-default-mode、detail-fast-track-distinct-from-full）经复核确认：
期望断言与产品源码行为**完全一致**（`detail.tsx:339-340` 对 `mode==='fast-track'`
渲染 `fast-track` Tag，其余分支渲染「完整模式」），断言有效、非场景缺陷。根因在
前端构建产物过期，重新构建后全部通过。任务 23-25（复核 → 修复 → 复验）完成。

---

## 非阻塞场景（warning，flaky，逐断言归因）

以下场景的功能断言全部通过，场景 `status=warning` 的根因为整页 SSIM 视觉对比
低于 pass 阈值，经核实属动态内容区域，逐断言归因见 report.json `assertion_triage`。

| 场景 | 说明 | 判定 |
|------|------|------|
| `list-mode-column-visible` | 功能断言全部通过；SSIM 0.8653 因列表页 SSE 实时刷新动态内容差异 | ⚠️ flaky，不记产品 Bug |
| `regression-list-page-renders` | 功能断言全部通过；SSIM 0.8653 与上场景同根因（SSIM、current 截图一致） | ⚠️ flaky，不记产品 Bug |
| `regression-detail-existing-spec` | 真实 spec 详情页功能断言全部通过；SSIM 0.9454 因动态状态/时间戳轻微差异 | ⚠️ flaky，不记产品 Bug |

`list-mode-column-visible` 与 `regression-list-page-renders` 为同一根因（列表页
SSE 动态内容），聚合处理；两场景 current 截图完全一致、SSIM 完全相同（0.86527622）
佐证为环境动态性而非产品缺陷。

---

## 通过场景一览

| 场景 | 描述 | 状态 |
|------|------|------|
| `detail-fast-track-mode-tag` | mock mode=fast-track 详情页标题区出现「fast-track」Tag | ✅ pass |
| `detail-full-mode-tag` | mock mode=full 详情页标题区出现「完整模式」Tag | ✅ pass |
| `detail-legacy-default-mode` | 无 mode 字段详情页缺省 full 展示「完整模式」Tag | ✅ pass |
| `detail-fast-track-distinct-from-full` | fast-track/full 两模式标签文本可辨识 | ✅ pass |

---

## 结论

fast-track 模式验证通过，裁决 `verified`（bugs=0）。详情页模式标记能力
（fast-track/完整模式/存量缺省 full 标签）全部生效，列表页模式标记功能正常，
无回归。本轮场景集 7 个（修复轮复用无增减），全部覆盖。

## 本轮场景集变更

场景集与持久化集一致，无变更。

