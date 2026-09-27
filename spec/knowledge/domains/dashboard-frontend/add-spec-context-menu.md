<!-- knowledge: capability=add-spec-context-menu rev=1 sources=spec/archive/2026-09-03-add-spec-context-menu -->

# SPEC 行右键菜单

SPEC 列表行内右键唤起自绘上下文菜单，提供呼叫 Admin、调整优先级与删除三个操作入口。

## 现行规则

- SPEC 列表每一行（任意状态）支持右键：拦截浏览器原生菜单，在鼠标位置显示自绘上下文菜单，含「呼叫 Admin 介入」「调整优先级」「删除 SPEC」三项；非 SPEC 行区域（空白处、表头等）右键保持浏览器原生默认行为。
- 菜单关闭：点击菜单外任意位置、滚动列表或按 Esc 键立即关闭；菜单靠近视口底部/右侧边缘时整体翻转（向上/向左），始终完全在视口内。
- 呼叫 Admin 介入：点击后关闭菜单并请求 `POST /api/spec-admin-invoke`；后端接受时提示「Admin 已拉起」并自动刷新 admin 活动区；该 SPEC 已有进行中的 admin run 或未消费的 invoke 请求时，展示服务端返回的拒绝原因，不重复唤起。
- 调整优先级：点击后弹窗预填当前 priority，接受 1-9 整数（P1 最高）；确认后请求 `POST /api/spec-priority`，成功更新行内显示；非法输入由前后端双侧校验拦截（弹窗内联提示、不发请求），取消则无任何变更。
- 删除 SPEC：点击后弹出确认对话框（明确说明软删除与归档路径）；确认后请求 `POST /api/spec-delete`，行及其信息子行从列表消失、无残留；取消或按 Esc 无副作用。

## 溯源

- 史前复原 — SPEC 行右键菜单三项操作（呼叫 Admin、调整优先级、删除）与删除后行/信息子行无残留
- 2026-09-03 add-spec-context-menu — 固化右键菜单交互契约：原生菜单拦截与边缘翻转、Esc/外点关闭、Admin 唤起成功与拒绝反馈、优先级双侧校验与软删除确认流
