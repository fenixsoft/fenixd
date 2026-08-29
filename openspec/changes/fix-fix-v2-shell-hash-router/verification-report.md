# 验证报告：fix-fix-v2-shell-hash-router

- **验证时间**：2026-08-29T07:13:06Z
- **验证结论**：✅ **验证通过（verified）**
- **场景总数**：2
- **通过**：2 ｜ **失败**：0 ｜ **错误**：0 ｜ **警告**：0 ｜ **环境阻塞**：0

## 判定规则应用说明

- 所有断言均为第 1 层（元素可见）与第 3 层（属性匹配 / 无网络 / 无控制台错误）断言，且全部 `pass: true`。
- `no_console_error` 断言 `errors` 为空、`filtered_network` 为空，无外部 API 网络层错误需要豁免处理。
- `no_network_error` 断言 `errors` 为空，无 404 等网络错误。
- 视觉结果（visual_results）在首次运行时自动建立基线（`baseline_created`），`ssim` 为 `null`，属正常基线采集，不需回归对比。

## 场景明细

### Scenario1：`legacy-dashboard-stay-visible`（通过）
**验证点**：直接访问 `GET /` 时老版 dashboard 与 v2 壳并存不受影响。

| 断言类型 | 选择器 | 层级 | 结果 |
|---|---|---|---|
| element_visible | `#main` | 1 | ✅ 通过 |
| element_visible | `#btn-overview` | 1 | ✅ 通过 |
| no_console_error | — | 3 | ✅ 通过（errors=[]，filtered_network=[]） |

基线：首次运行，已自动建立基线。

### Scenario2：`legacy-switch-to-v2-coexist`（通过）
**验证点**：在老版停留后切到 `/v2/index.html#/overview`，v2 壳与老版各自独立、侧边导航为 hash 形态。

| 断言类型 | 选择器 | 层级 | 结果 |
|---|---|---|---|
| element_visible | `#root` | 1 | ✅ 通过 |
| element_visible | `a[href='#/overview']` | 1 | ✅ 通过 |
| attribute_match | `a[href='#/overview']`（href=#/overview） | 3 | ✅ 通过（expected=#/overview，actual=#/overview） |
| no_network_error | — | 3 | ✅ 通过（errors=[]） |
| no_console_error | — | 3 | ✅ 通过（errors=[]，filtered_network=[]） |

基线：首次运行，已自动建立基线。

## 结论

本次验证覆盖「老版 dashboard 与 v2 壳并存不受影响」的两条核心路径，全部断言通过，无产品 Bug、无环境阻塞、无控制台/网络错误。`fixNavHrefs` 对 `a[href^='/']` 改写为 `#/x` 的 hash 路由修复生效，老版入口页在 `GET /` 下正常渲染且未整页跳离。验证状态：**verified**。
