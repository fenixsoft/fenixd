# 验证报告：add-alert-auto-resolve

> ⚠️ 本报告由框架于 2026-08-30T07:05:41Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

验证通过：add-alert-auto-resolve 共 11 个场景全部通过，0 失败、0 告警、0 阻断。v1（app.js renderAlertBanner/toggleText）与 v2（v2/app.js 横幅 strip + Dialog + Collapse）双界面均落实视图告警分组：待处理置顶展开、已解决折叠收起且计数不含历史噪音；展开后按 handled_by 区分「🤖 自动解决 / 👤 人工处理」徽标并显示 resolve_note（含存量回填前缀）与 handled_at；空状态（无已解决、全部闭环）下已解决区/横幅正确移除，零噪音回归点成立。所有断言（元素可见/存在性、点击未遮挡、文本精确/包含匹配、属性 class 匹配、no_console_error）逐条通过，无断言时序问题、无网络环境问题（filtered_network 均为空）。视觉断言均为首次运行自动建立基线（baseline_created, ssim=null），无像素回归可比对，后续轮次可作回归基线。

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |


## 场景结果

| 场景 | 状态 | 失败断言 |
| --- | --- | --- |
| v1-group-pending-top-resolved-collapsed | pass | 0/9 |
| v1-resolved-expand-auto-badge-note-time | pass | 0/11 |
| v1-resolved-collapse-back-regression | pass | 0/5 |
| v1-no-resolved-no-resolved-section | pass | 0/6 |
| v1-all-resolved-banner-hidden | pass | 0/5 |
| v1-pending-not-flooded-3-vs-20 | pass | 0/6 |
| v1-backfill-resolve-note | pass | 0/6 |
| v2-banner-strip-count-dialog-open | pass | 0/9 |
| v2-resolved-expand-badge-note-time | pass | 0/9 |
| v2-no-resolved-no-collapse-section | pass | 0/7 |
| v2-all-resolved-strip-hidden | pass | 0/3 |
