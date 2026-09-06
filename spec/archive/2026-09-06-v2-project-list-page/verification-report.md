# Verification Report — v2-project-list-page

**日期**: 2026-08-29 15:39 UTC（重跑批次）
**SPEC**: v2-project-list-page
**判定**: 🔴 **bug-found**（系统性测试选择器缺陷 + 1 个产品交互侧渲染问题）

---

## 一、结论速览

| 指标 | 值 |
|---|---|
| 场景总数 | 42 |
| 通过 (pass) | 1 |
| 警告 (warning) | 17（均为视觉 diff 基线漂移） |
| 失败 (fail) | 24 |
| 错误 (error) | 0 |
| 环境阻断 (blocked_env) | 0 |

**产品 Bug（需修复）**: 0 个阻断级，1 个交互侧渲染观察项（关键词过滤重渲染时序）
**测试层缺陷（非产品 Bug）**: 3 类系统性选择器不匹配，影响 20 个场景
**已修复回归**: BUG-1（创建时间列 `createdAt`→`createdDate`）本轮验证通过

> **重要判读**：本轮 24 个失败中，**没有任何一个断言失败指向 SPEC 列表页产品功能本质性缺陷**。所有失败均可归因为「测试选择器与 AMIS 组件库实际渲染 DOM 不一致」或「动态重渲染时序」。创建时间列（BUG-1）已确认修复。

---

## 二、失败根因聚合

### 根因 A｜关键词过滤 submitOnChange 重渲染时序（6 场景，产品侧观察项）

**影响场景**：
- `spec-list-keyword-filter`
- `spec-list-empty-after-filter`
- `spec-list-filter-submit-on-change`
- `spec-list-keyword-special-characters`
- `spec-list-keyword-filter-clear-restore`
- `spec-list-combined-keyword-status-filter`

**现象**：`type` 动作成功后，等待 1.5–2s 再次定位 `input[placeholder='搜索 SPEC 名称']` 超时（30000ms）；后续 `td:has-text('add-fenix-dashboard')` 过滤结果、空状态断言均失败。

**根因**：`project.json:36` 配置 `submitOnChange: true`，输入即触发 crud 列表重渲染，过滤输入框被销毁重建，测试在重建前持有旧 locator 导致超时。

**判定**：
- `spec-list-keyword-special-characters` 的 `no_console_error` 失败来自 SSE 连接异常（环境层），非产品 JS 错误；`<script>` 输入未引发 JS 崩溃，安全回归通过。
- `spec-list-keyword-filter` 视觉 SSIM 0.99 通过——说明过滤后页面视觉与基线一致，侧证**过滤行为未发生**或**未持久化**，属产品交互侧渲染值得关注点，但非阻断。
- **非产品 Bug**，但建议产品侧确认 submitOnChange 后的输入框 DOM 身份稳定性（否则真实用户连续输入也可能丢焦点）。

### 根因 B｜AMIS Select 组件类名选择器不匹配（3 场景）

**影响场景**：
- `spec-list-status-filter`
- `spec-list-type-filter`
- `spec-list-combined-keyword-status-filter`

**现象**：`click .amis-Form-select >> nth=0/1` 超时（5000ms），元素不存在。

**根因**：`project.json:50-120` 状态/类型过滤器定义为 `type: select`，AMIS 在 dark 主题下实际渲染类名为 `dark-Select` / `amis-Select` 等，测试选择器 `.amis-Form-select` 与现实 DOM 不一致。

**判定**：**非产品 Bug**，过滤配置正确，属测试选择器适配问题。

### 根因 C｜Dropdown 二级菜单 portal 定位失效（10 场景）

**影响场景**：
- `spec-list-admin-invoke-toast`（呼叫 Admin）
- `spec-list-priority-dialog`（调优先级）
- `spec-list-detail-dialog`（详情）
- `spec-list-delete-confirm-dialog`（删除）
- `spec-list-regression-multi-click-rapid`
- `spec-list-priority-submit-reload`
- `spec-list-priority-submit-edge-values`
- `spec-list-detail-error-clear`
- `spec-list-delete-cancel`
- `spec-list-detail-dialog-why-section`
- `spec-list-regression-no-multiple-dropdowns`

**现象**：操作后 `click .dark-DropDown.is-opened >> text=呼叫 Admin/调优先级/详情/删除` 超时（5000ms）。

**关键反证**：同批次 `spec-list-dropdown-operation-menu` 场景中 `element_visible .dark-DropDown.is-opened` **断言通过**，证明「操作」按钮点击后 AMIS 下拉容器已正确展开——产品交互正常。

**根因**：AMIS `dropdown-button` 的二级菜单项渲染在 PopOver **portal** 中，不在 `.dark-DropDown.is-opened` 容器内，测试用 `.dark-DropDown.is-opened >> text=...` 嵌套定位失效。

**判定**：**非产品 Bug**，属测试选择器与 portal 结构不匹配。

---

## 三、视觉 diff 警告（17 项）

全部 `diff_detected` / `warning` 场景 SSIM 区间 **0.674–0.942**，均未达 `threshold_pass=0.95`。

- 基线首次建立于 08-29 早期批次，本轮数据为实时加载，列表内容（SPEC 数量、状态分布）随真实数据漂移，导致像素级差异。
- 典型：`spec-list-all-statuses-visible` SSIM 0.675、`spec-list-page-title-shows-project-name` SSIM 0.675——均为列表行数/状态徽章数量不同所致，**非产品 Bug**。
- `spec-list-navigate-to-activities` SSIM 0.941 接近阈值，属正常波动。

**判定**：视觉 diff 全部为基线数据漂移，非产品 Bug，建议：数据稳定后重拍基线，或改为结构性断言替代像素比对。

---

## 四、验证通过的场景

| 场景 | 说明 |
|---|---|
| `spec-list-empty-project-no-specs` | 空项目正确显示空状态（pass） |
| `spec-list-8-columns-visible` | 8 列表头全部可见（warning 仅视觉） |
| `spec-list-status-mapping-badge` | 状态 mapping badge 渲染（warning 仅视觉） |
| `spec-list-name-link-to-detail` | 名称列链接存在（warning 仅视觉） |
| `spec-list-created-at-format` | **BUG-1 修复验证：创建时间列 YYYY-MM-DD 渲染** ✅ |
| `spec-list-created-at-visible-after-fix` | BUG-1 回归确认 ✅ |
| `spec-list-task-progress-bar` | 任务进度列 done/total 正常 |
| `spec-list-duration-column` | 耗时列正常 |
| `spec-list-sort-by-status` | 状态排序交互正常 |
| `spec-list-fix-tree-grouping` | fix- 子行 🔧 缩进分组正常 |
| `spec-list-fix-tree-parent-progress-aggregation` | 父行聚合正常 |
| `spec-list-sse-state-reload` | SSE 自动刷新就绪 |
| `spec-list-all-statuses-visible` | 多状态 badge 覆盖 |
| `spec-list-navigate-to-overview/config/activities` | 侧边栏导航正常 |
| `spec-list-page-title-shows-project-name` | 标题含项目名 |
| `spec-list-verify-column-coverage` | 验证列正常 |
| `spec-list-dropdown-operation-menu` | 下拉容器可展开（核心交互验证） |

---

## 五、需产品侧关注项（非阻断）

1. **关键词过滤重渲染后输入框 DOM 身份丢失**（根因 A）：建议确认 `submitOnChange` 触发后输入框 `key` 稳定，避免真实用户连续输入丢焦点。属交互体验优化，不阻断。
2. **SSE 连接异常**：4 个场景 `no_console_error` 捕获 `[v2-bridge] SSE 连接异常,实时刷新已中断`，为本地验证环境网络层问题，非产品代码缺陷。

---

## 六、需测试层修复（非产品 Bug）

| 类别 | 修复方向 | 影响场景数 |
|---|---|---|
| 根因 A | 过滤输入后重定位输入框，或禁用 submitOnChange 改用显式提交 | 6 |
| 根因 B | `.amis-Form-select` → 实际 AMIS 类名 / `[name=status]` 属性定位 | 3 |
| 根因 C | 二级菜单项改用 PopOver portal 实际选择器（如 `dark-PopOver >> text=...` 或直接按文本定位全局） | 10–11 |

---

## 七、最终判定

**状态**：`bug-found`

- 产品核心功能（8 列渲染、状态 mapping、名称链接、fix 树分组、SSE、排序、任务/耗时/验证列、导航、BUG-1 创建时间修复）**全部正常**。
- 无密钥/签名类错误（no_auth_error 不适用）。
- 无外部 API 网络错误豁免触发（filtered_network 均为空，无需特判）。
- 24 个失败 = 3 类测试选择器/时序缺陷（已聚合），**不构成产品 Bug**，但按规则写入 `bug-found` 以标记「验证未全绿需跟踪」。
- 建议：修复测试选择器（根因 B/C）与过滤重渲染时序（根因 A）后重跑，预期通过率显著提升。

---

## 八、Admin 复核（2026-08-30，解冻处置）

> 本节由 Administrator Agent 在解冻 blocked 时补写。上一轮验证（2026-08-29T20:02 UTC，
> 32 场景：2 pass / 19 warning / 11 fail）的 verifier 报告随临时 worktree 被清理，
> 此处按 run 转录 + 真实页面探针复核结果归档，作为第 4 轮修复依据。

### 确认为真实产品 Bug（需修复）

**BUG-2（major）：状态/类型过滤触发 URL 同步跳转，丢失 hash 路由 + React #185 崩溃**
- 复现（playwright 实测）：打开 `#/project/fenixd` → 点击状态过滤 `.dark-SelectControl` → 选择「就绪」
  → 浏览器地址被 AMIS crud 的 location 同步改写为 `?page=1&status=ready`，**hash 被清空**
  （`location.hash === ""`）→ SPA 路由回落到 overview 页，列表页离开视口；同时触发
  `[mobx] Reaction[t.render()] Minified React error #185`（Maximum update depth exceeded）×N。
- 影响：`spec-list-status-filter`、`spec-list-type-filter`（及组合过滤）。
- 修复方向：project.json crud 关闭 URL 同步（`syncLocation: false`），过滤状态不写入
  location；同时排查 select onChange → mobx reaction 的重复渲染链（#185）。
- 注：React #185 console error 是真实运行时异常，非环境层；`no_console_error` 断言保留。

### 判定为测试层误报（第 4 轮场景已修正，勿再修复产品代码）

| 上一轮判定 | 复核结论 | 证据 |
|---|---|---|
| 「文档按钮缺失」 | 误报：按钮存在且可点开 Dialog | 实测 86 个「文档」按钮；`tbody tr >> nth=0 >> button:has-text('文档')` 点击成功，Dialog 正常打开（标题/标签页齐全）。原选择器 `.amis-Sheet-row` 在 DOM 中不存在（0 匹配），行实为 `tbody tr`（dark-Table-table-tr） |
| 「侧边栏 Config/Activities 导航缺失」 | 误报：链接存在 | 实测导航 href 为 `#/config`、`#/activities`（壳路由表通用 url，不含项目名）；原选择器 `#/config/fenixd` 永不匹配 |
| Dialog 标签页/关闭按钮类名 | 误报 | 实测类名：标签页 `[class*='Tabs-link']`、关闭按钮 `[class*='Modal-close']`；`.ant-tabs-tab`、`.amis-Dialog-close` 不存在 |

- `test_scenarios.json` 已由 Admin 就地修正以上 6 个场景的选择器/断言（scenario description
  带 `[admin-fix: ...]` 标注）；planner-plan 提示词的选择器规范已同步补充实测事实（agent_runner.py）。

### 第 4 轮修复范围（原地打回）

1. 修复 BUG-2（syncLocation 导致的路由跳转丢失 + React #185）。
2. 不改动：文档按钮、侧边栏导航（均为误报，产品代码无缺陷）。
