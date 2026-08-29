# 验证报告：v2-run-stream-modal

> ⚠️ 本报告由框架于 2026-08-29T14:04:15Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 4/20 场景通过，16 失败，0 错误（5 个真实产品 Bug）**

验证未通过：共 20 个场景，4 个通过，16 个失败。核心问题为 run 模式弹窗内事件流容器 .rs-event/.rs-status/.rs-stream 始终保持 hidden 状态，导致事件渲染、滚动、内容校验等 12 个场景无法执行；admin 模式存在 custom action this.reload 方法缺失导致轮询功能断裂（3 个场景）及关闭按钮缺失（1 个场景）。建议优先排查 rs-stream 组件初始化逻辑和 dialog-content-container 的数据绑定。

| 指标 | 数量 |
| --- | --- |
| 通过 | 4 |
| 失败 | 16 |
| 错误 | 0 |
| 产品 Bug | 5 |


## 真实产品 Bug

### BUG-01（severity=critical）· element_visible

- 关联场景：run-stream-run-mode-open-dialog、run-stream-run-mode-event-content、run-stream-run-mode-reset-frame、run-stream-run-mode-thinking-tokens-merge、run-stream-status-bar-live-indicator、run-stream-md-rendering-headers、run-stream-md-rendering-code-blocks、run-stream-html-escape-prevention、run-stream-open-close-reopen-cycle
- 描述：事件流核心容器 .rs-event 和 .rs-status 始终保持 hidden 状态，弹窗内无法渲染任何运行事件
- 根因：dialog-content-container 内的 .rs-event / .rs-status 元素存在但 CSS visibility/display 隐藏，可能是 rs-stream 组件未正确初始化或数据流未建立导致容器不渲染子元素
- 证据：
  - error_pattern: locator resolved to hidden <div class="rs-event"></div>
  - affected_scenarios_count: 9
  - scope: run 模式下所有依赖事件流渲染的场景均受影响

### BUG-02（severity=critical）· element_visible

- 关联场景：run-stream-run-mode-sticky-scroll、run-stream-event-total-count、run-stream-scroll-down-auto-stick
- 描述：事件流滚动容器 .rs-stream 始终保持 hidden，无法执行滚动操作和粘性滚动功能
- 根因：rs-stream 容器未渲染或 display:none，导致所有依赖滚动的测试场景在操作阶段就失败
- 证据：
  - error_pattern: locator resolved to hidden <div class="rs-stream"></div>
  - affected_scenarios_count: 3
  - scope: 所有涉及滚动操作的场景均被阻断

### BUG-03（severity=major）· no_console_error

- 关联场景：run-stream-admin-mode-409-conflict、run-stream-admin-mode-waiting-state、run-stream-admin-mode-resolved-switch
- 描述：admin 模式下 custom 动作执行报错 'this.reload is not a function'，轮询/刷新逻辑断裂
- 根因：custom action 中调用的 this.reload 方法不存在，可能是 amis custom action 上下文绑定错误或组件实例未正确挂载
- 证据：
  - console_errors: ["[error] custom 动作执行失败，原因：this.reload is not a function"]
  - affected_scenarios_count: 3
  - scope: 所有 admin 模式场景均受影响，轮询和状态切换功能不可用

### BUG-04（severity=major）· element_not_found_or_not_actionable

- 关联场景：run-stream-admin-mode-close-cleanup
- 描述：admin 模式下无法找到关闭按钮 .dark-Modal-close，弹窗无法关闭
- 根因：admin 模式弹窗未渲染关闭按钮，或弹窗结构与 run 模式不同导致选择器失效
- 证据：
  - error: Locator.wait_for: Timeout 5000ms exceeded. waiting for locator('.dark-Modal-close').first to be visible
  - affected_scenarios_count: 1

### BUG-05（severity=minor）· no_click_interception

- 关联场景：run-stream-run-mode-open-dialog
- 描述：弹窗打开后遮挡底层时间轴项的点击，属于弹窗层叠顺序正常行为（z-index:1400 vs auto）
- 根因：弹窗 modal overlay 的 z-index 高于 TimelineItem，点击被拦截是预期行为；测试场景设计时应在弹窗关闭后校验或改用 force:true
- 证据：
  - intercepting_element: amis-dialog-widget dark-Modal dark-Modal--lg dark-Modal--1th
  - intercepting_z_index: 1400
  - note: 断言时序问题：弹窗已打开后再点击被遮挡元素属于测试设计缺陷


## 场景结果

| 场景 | 状态 | 失败断言 |
| --- | --- | --- |
| run-stream-run-mode-open-dialog | fail | 2/4 |
| run-stream-run-mode-event-content | fail | 3/3 |
| run-stream-run-mode-close-cleanup | pass | 0/2 |
| run-stream-run-mode-sticky-scroll | fail | - |
| run-stream-run-mode-reset-frame | fail | 2/3 |
| run-stream-run-mode-thinking-tokens-merge | fail | 1/2 |
| run-stream-admin-mode-409-conflict | fail | 1/2 |
| run-stream-admin-mode-waiting-state | fail | 1/2 |
| run-stream-admin-mode-resolved-switch | fail | 1/2 |
| run-stream-admin-mode-close-cleanup | fail | - |
| run-stream-dialog-close-escape | pass | 0/2 |
| run-stream-dialog-title-run-id | pass | 0/3 |
| run-stream-status-bar-live-indicator | fail | 2/3 |
| run-stream-event-total-count | fail | - |
| run-stream-md-rendering-headers | fail | 1/2 |
| run-stream-md-rendering-code-blocks | fail | 1/2 |
| run-stream-html-escape-prevention | fail | 1/2 |
| run-stream-multiple-dialogs-prevent | pass | 0/3 |
| run-stream-scroll-down-auto-stick | fail | - |
| run-stream-open-close-reopen-cycle | fail | 1/4 |
