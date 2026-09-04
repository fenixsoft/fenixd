# add-spec-context-menu — Spec 行右键菜单 UI

## ADDED Requirements

### Requirement: spec 行右键弹出上下文菜单
spec 列表每一行（任意状态）支持右键点击；右键时拦截浏览器原生菜单，在鼠标位置显示自绘上下文菜单，含三项：呼叫 Admin 介入、调整优先级、删除 Spec。

#### Scenario: 右键弹出菜单
- WHEN 用户在某个 spec 行上点击鼠标右键
- THEN 浏览器原生菜单不出现，自绘菜单在光标位置可见，三个菜单项均渲染

#### Scenario: 非目标区域不弹菜单
- WHEN 用户在页面空白处或表头等非 spec 行区域右键
- THEN 出现浏览器原生默认行为，不自绘菜单

#### Scenario: 点击他处或按 Esc 关闭
- GIVEN 自绘菜单已打开
- WHEN 用户点击菜单外任意位置、滚动列表或按下 Esc 键
- THEN 菜单立即消失

#### Scenario: 菜单靠近视口边缘时不溢出
- WHEN 在窗口底部/右侧边缘附近的 spec 行右键
- THEN 菜单整体仍完全在视口内（向上/向左翻转）

### Requirement: 呼叫 Admin 介入菜单项
点击「呼叫 Admin 介入」后关闭菜单并向 `POST /api/spec-admin-invoke` 发起请求；后端接受时前端提示「Admin 已拉起」并自动刷新 admin 活动区，拒绝时展示返回的拒绝原因。

#### Scenario: 触发唤起成功反馈
- GIVEN 该 spec 当前无进行中的 admin run
- WHEN 用户点击「呼叫 Admin 介入」
- THEN 菜单关闭，出现非阻塞 toast「已呼叫 Admin 介入检查」，数秒内 admin 活动时间线出现该 run 记录

#### Scenario: 已有进行中 admin run 时拒绝
- GIVEN 该 spec 存在进行中的 admin run 或未消费的 invoke 请求
- WHEN 用户点击「呼叫 Admin 介入」
- THEN toast 显示服务端返回的拒绝原因（如「已有进行中的 Admin 处置」），不重复唤起

### Requirement: 调整优先级弹窗
点击「调整优先级」后关闭菜单，弹出输入框（预填当前 priority），接受 1-9 整数（P1 最高）；确认后 POST `/api/spec-priority` 成功则更新行内显示，非法输入由前后端双侧校验拦截。

#### Scenario: 修改优先级生效
- GIVEN 某 spec 当前 priority=5
- WHEN 用户在该行右键 → 调整优先级 → 输入 2 → 确认
- THEN STATE.md 中该 spec 的 priority 变为 2，页面显示更新且调度顺序变化可在概览排序中观察

#### Scenario: 非法输入被拒
- WHEN 用户输入 0、10 或非数字并确认
- THEN 弹窗内联提示「请输入 1-9 的整数」，不发请求；取消则无任何变更

### Requirement: 删除 Spec 软删除流程
点击「删除 Spec」后弹出确认对话框（明确说明软删除与归档路径）；确认后 POST `/api/spec-delete`：STATE.md 移除该条目且 `spec/changes/<name>/` 移入 `spec/archive/<name>-<Unix秒>/`。删除后行从列表消失。

#### Scenario: 确认后软删除完成
- GIVEN 某 spec 处于 drafting/testing 等任意状态
- WHEN 用户右键 → 删除 Spec → 在确认弹窗点「删除」
- THEN STATE.md 无该条目、行从列表移除、原目录出现在 spec/archive/<name>-<ts>/

#### Scenario: 取消删除无副作用
- WHEN 用户在确认弹窗点「取消」或按 Esc
- THEN STATE.md 与目录均不变

#### Scenario: 归档后不在监控范围
- THEN 被 archive 的 spec 不再被 daemon 扫描/调度，也不出现在 Dashboard 各视图
