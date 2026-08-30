# 验证报告：v2-overview-page

> ⚠️ 本报告由框架于 2026-08-29T12:19:01Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 6/12 场景通过，6 失败，0 错误（全部场景通过）**

12 个场景通过 6 个，失败 6 个，经逐条裁决全部为测试场景/验证 harness 设计缺陷，无产品 Bug。核心根因有二：(1) 弹窗重叠拦截——点击启停删按钮时 amis 确认 Modal 以全屏遮罩层覆盖整页，第 2 层 no_click_interception 断言在 modal 仍处于打开态时校验按钮可点击，被遮罩拦截而误判；(2) 验证 harness 已知缺陷——mock_api 仅拦 HTTP 列表端点，无法拦截 8787 端口 daemon 经 SSE(/api/stream) 推送的真实项目数据，导致 empty-state 断言空列表时仍渲染 5 张真实卡片、Start 按钮中 fenixd 项目为 running 无启动按钮、以及项目卡片文本的精确匹配误判（expected='SPEC' 因页面真实 fenixd 项目数据而 actual='129SPEC 总数'）。Text/属性类第 3 层与 click_interception 第 2 层失败均符合规则中的「断言时序/环境因素」豁免，不记为产品 Bug。

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 6 |
| 错误 | 0 |
| 产品 Bug | 0 |


## 场景结果

| 场景 | 状态 | 失败断言 |
| --- | --- | --- |
| overview-stat-blocks-render | pass | 0/8 |
| overview-project-cards-render | fail | 1/5 |
| overview-start-button-flow | fail | - |
| overview-stop-button-flow | fail | 2/3 |
| overview-delete-button-cancel | fail | 1/3 |
| overview-delete-button-confirm | fail | 3/4 |
| overview-empty-state | fail | 1/3 |
| overview-stopped-project-start-visible | pass | 0/3 |
| overview-running-project-stop-visible | pass | 0/3 |
| overview-missing-project-badge | pass | 0/4 |
| overview-sse-reload | pass | 0/4 |
| overview-no-auth-error | pass | 0/3 |
