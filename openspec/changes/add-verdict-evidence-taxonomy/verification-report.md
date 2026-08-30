# 验证报告：add-verdict-evidence-taxonomy

> ⚠️ 本报告由框架于 2026-08-30T03:31:03Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 2/6 场景通过，4 失败，0 错误（2 个真实产品 Bug）**

共 6 个场景：2 通过、4 失败。其中 bug-list 两个场景的失败为环境因素（404 控制台错误源于 mock 证据引用的截图资产缺失，前端结构化证据渲染全部通过），不计为产品缺陷；另 2 个失败为真实产品 Bug：escalation-banner-mark-handled-flow（升级告警「标记已处理」处置闭环未乐观移除告警项）与 escalation-banner-warning-stale-triage（告警项未渲染 spec 标识）。判定为 bug-found。

| 指标 | 数量 |
| --- | --- |
| 通过 | 2 |
| 失败 | 4 |
| 错误 | 0 |
| 产品 Bug | 2 |


## 真实产品 Bug

### BUG-01（severity=major）· element_not_exist

- 关联场景：escalation-banner-mark-handled-flow
- 描述：点击升级告警项的「标记已处理」按钮后，该告警项未被乐观移除：断言 .alert-handled-btn[data-id='tri-002'] 仍存在（actual_count=1，期望 0），warning 连续悬置升级告警的处置闭环未生效。
- 根因：标记已处理点击事件未触发乐观移除：#alert-banner 事件委托在横幅重渲染后可能丢失监听，或移除逻辑依赖服务端 POST /api/alerts/<id>/handled 响应成功而非乐观更新，导致点击后告警项仍驻留 DOM（与本 change 旨在修复的 fix-add-verify-report-gate Bug 3/4 根因同型）。
- 证据：
  - selector: .alert-handled-btn[data-id='tri-002']
  - expected_count: 0
  - actual_count: 1
  - scenario: escalation-banner-mark-handled-flow
  - related_code: core/dashboard/static/app.js:372-403 (事件委托) / 353 (handled POST)

### BUG-02（severity=major）· text_contains

- 关联场景：escalation-banner-warning-stale-triage
- 描述：升级告警横幅的告警项未渲染 spec 标识：断言文本 'add-verdict-evidence-taxonomy' 未出现。尽管横幅、告警项、证据摘要块、'连续 2 轮'、'首败步骤' 均正常渲染，但违背 Requirement「内容含 spec/场景/连续轮次/证据摘要」。
- 根因：alerts 响应结构未携带 spec 字段映射到告警项，或 alertItemHtml 未将 a.spec 渲染到告警项可见区域（.alert-item-spec），导致告警无法关联到具体 spec，削弱人工分诊的路由定位。
- 证据：
  - text: add-verdict-evidence-taxonomy
  - assertion_type: text_contains
  - layer: 3
  - scenario: escalation-banner-warning-stale-triage
  - related_code: core/dashboard/static/app.js:311-334 (alertItemHtml .alert-item-spec)


## 场景结果

| 场景 | 状态 | 失败断言 |
| --- | --- | --- |
| bug-list-evidence-structured-visible | fail | 1/8 |
| bug-list-product-bug-not-suspended | fail | 1/6 |
| bug-list-evidence-missing-empty-state | pass | 0/4 |
| escalation-banner-warning-stale-triage | fail | 1/8 |
| escalation-banner-mark-handled-flow | fail | 1/3 |
| regression-bug-list-no-classification-still-renders | pass | 0/4 |
