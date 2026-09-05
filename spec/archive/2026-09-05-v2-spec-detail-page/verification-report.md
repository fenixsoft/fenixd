# 验证报告：v2-spec-detail-page

- **验证时间**：2026-08-29T09:40:38Z
- **验证目标**：SPEC 详情页（验证卡 + 4 页签 + SSE detail 刷新）真实云端端到端渲染
- **总体结论**：🔴 **发现产品 Bug（1 项，major）**；另有 2 项失败属测试侧缺陷，不计入产品 Bug
- **汇总**：9 场景 → 6 通过 / 3 失败 / 0 警告 / 0 错误 / 0 环境阻塞

---

## 一、场景执行情况

| 场景 | 状态 | 关键说明 |
|------|------|----------|
| spec-detail-four-tabs-visible | ✅ pass | 四页签可依次点击，内容区渲染无 console 错误 |
| spec-detail-verdict-card | ❌ fail | 验证卡「验证结论」「验证进度」h3 标题不可见（**产品 Bug**） |
| spec-detail-empty-state | ✅ pass | 不存在的 SPEC 路由优雅降级，无报错 |
| spec-detail-timeline-nodes | ✅ pass | 时间轴节点正常渲染 |
| spec-detail-scenario-table | ✅ pass | 场景表格 + 列标题可见 |
| spec-detail-bug-table | ✅ pass | Bug 表格 + 列标题可见 |
| spec-detail-screenshot-zoom | ✅ pass | 截图缩略图可见、可点击放大 |
| spec-detail-sse-bridge-present | ❌ fail | 断言查 `#v2-bridge-host` 不存在（**测试选择器错误**） |
| spec-detail-timeline-node-dialog | ❌ fail | Dialog 正常弹出，但后续重复点击被拦截（**断言时序问题**） |

---

## 二、产品 Bug（需修复）

### BUG-1（major）：验证卡「验证结论 / 验证进度」标题不可见

- **场景**：`spec-detail-verdict-card`
- **断言**：`element_visible` (layer 1) — `h3:has_text('验证结论')`、`h3:has_text('验证进度')`
- **现象**：两个 `<h3>` 标题的 Locator 在 3000ms 内超时未判定为可见；同卡片「任务清单」h3 正常渲染，`.m-b-sm` 文本含「验证」断言通过，无 console 错误。
- **根因推断**：`core/dashboard/static/v2/pages/spec-detail.json:42-44、67-69` 用 AMIS `tpl` 渲染 `<h3 style='margin:0'>验证结论</h3>` / `<h3 style='margin:0'>验证进度</h3>`，外层 grid 列（md:12）+ `className:'m-b-xs'`，h3 内联 `margin:0` 使行盒塌缩，在真实 AMIS embed 渲染下该节点未被判定为可见（与首列「任务清单」h3 可正常渲染形成对照，疑为网格列布局/首列渲染时序差异）。
- **影响**：验证卡是详情页核心交付物（spec 要求「验证结论卡可见」），标题不可见直接削弱可读性，属功能性渲染缺陷。
- **证据**：
  - 失败 selector：`h3:has_text('验证结论')` / `h3:has_text('验证进度')`
  - error：`Locator.wait_for: Timeout 3000ms exceeded`
  - 同场景通过项：`h3:has_text('任务清单')` pass；`text_contains '验证'` pass；`no_console_error` pass（errors=[]）
  - 源码：`core/dashboard/static/v2/pages/spec-detail.json:42-44, 67-69`

---

## 三、测试侧缺陷（不计入产品 Bug）

### WARN-1（测试选择器错误）：SSE 桥宿主容器断言对象不存在

- **场景**：`spec-detail-sse-bridge-present`
- **断言**：`element_visible` (layer 1) — `#v2-bridge-host`
- **判为测试缺陷的依据**：实现方案为 `app.js:12-23` 用 `amisCore.registerRenderer({type:'sse-bridge', component: SSEBridge})` 注入一个 `render(){return null;}` 的壳级渲染器（不进入 `#v2-content`，`render` 返回 `null` 不产生任何带 id 的 DOM 节点）。`#v2-content` 容器本身可见（同场景该断言 pass），SSE 桥逻辑由 `window.Bridge`（`bridge.js`）在 `componentDidMount` 内挂 `EventSource` 实现，功能就绪。该断言目标容器在设计中根本不存在。
- **建议修正**：改为校验 `window.Bridge` 已定义 / `amisCore.resolveRenderer('sse-bridge')` 已注册 / `window.Bridge._es`（`EventSource`）已建立，而非查 DOM id。
- **证据**：selector `#v2-bridge-host` 超时；实现见 `app.js:12-23`、SSE 桥 `bridge.js:21-60`、`pages/app.json` header `type:'sse-bridge'`。

### WARN-2（断言时序问题）：Dialog 已开启后重复点击底层节点被拦截

- **场景**：`spec-detail-timeline-node-dialog`
- **断言**：`no_click_interception` (layer 2) — `.dark-TimelineItem`
- **判为时序问题的依据**：时间轴节点点击**成功**弹出「运行记录」Dialog（`.amis-dialog-widget` 可见 + 标题断言均 pass），随后同一场景再次断言「时间轴节点点击不被遮挡」——此时 Dialog 已打开（`z-index:1400`，class `amis-dialog-widget dark-Modal--lg`），自然拦截对底层 `.dark-TimelineItem` 的第二次点击。弹窗功能本身正确，属「对话框/弹窗已打开后重复点击其内部/底层元素」的时序设计缺陷。
- **建议修正**：应在交互（首次打开 Dialog）前完成「节点点击不被遮挡」校验，或改为断言 Dialog 外的持久 DOM（`#v2-content` / 页签容器）。
- **证据**：intercepting `DIV.amis-dialog-widget.dark-Modal.dark-Modal--lg.dark-Modal--1th`（z-index 1400）；同场景 `.amis-dialog-widget` 可见 pass、`:has_text('运行记录')` pass。

---

## 四、验证总结

详情页四页签（时间轴 / 场景 / Bug / 截图）、表格列、截图放大预览、空状态降级、SSE detail 定向刷新脚本均按 spec 正常渲染、无 console 错误。验证卡标题可见性存在 1 项产品 Bug（major），需在产品侧修复（`spec-detail.json` 中验证结论/验证进度 h3 的渲染可见性）。另有 2 项失败为测试场景设计缺陷（SSE 桥断言选择器错误、Dialog 点击断言时序问题），不计入产品缺陷，建议在测试代码侧修正断言后复测。
