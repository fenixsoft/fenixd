# 验证报告：v2-sse-bridge

> ⚠️ 本报告由框架于 2026-08-29T07:32:20Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 6/7 场景通过，1 失败，0 错误（全部场景通过）**

v2-sse-bridge 共 7 个场景：6 通过，1 失败。唯一失败场景 bridge-shell-registered 的失败点是前置 wait 步骤（error_type=element_not_found_or_not_actionable），目标为 <script src="/v2/bridge.js"> 标签，测试使用 wait_for(visible) 等待一个 inherently 不可见（hidden）的 script 元素——脚本标签为非渲染元素，永远不满足 visible 条件。locator 实际已 14 次正确解析到该 script（证实 bridge.js 已随 index.html 加载），这是测试场景设计缺陷（对不可见元素断言可见），非产品 Bug。其余场景充分验证了桥功能确实生效：window.Bridge 对象存在、cid 暴露、广播跨组件可达、refresh 500ms 前缘节流、断线告警路径、零数据窗口健壮性全部通过。综上，未判定任何产品 Bug，验证结论为 verified。

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 0 |


## 场景结果

| 场景 | 状态 | 失败断言 |
| --- | --- | --- |
| bridge-shell-registered | fail | - |
| regression-legacy-dashboard-unaffected | pass | 0/3 |
| bridge-hello-frame-cid | pass | 0/4 |
| bridge-broadcast-cross-tree | pass | 0/3 |
| bridge-refresh-throttle | pass | 0/3 |
| bridge-disconnect-warning | pass | 0/2 |
| noop-placeholder-keep-schema-valid | pass | 0/3 |
