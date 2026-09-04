# 验证报告：add-verdict-evidence-taxonomy

- **验证时间**：2026-08-30T04:34:32+00:00
- **判定结论**：✅ **验证通过（verified）**
- **结果汇总**：9 个场景 — 8 通过 / 1 警告 / 0 失败 / 0 错误 / 0 环境阻断
- **产品 Bug 数**：0

---

## 一、总体判定

本轮验证覆盖「判定证据分类体系」规格的三大需求域：非 PASS 场景结构化证据、分类与状态映射约束、warning 连续悬置升级告警。全部功能断言（第 1-3 层）无一失败，唯一警告来自视觉比对阈值区间（第 4 层），经上下文分析判为非功能性差异，不构成产品 Bug。

---

## 二、场景结果明细

| 场景 ID | 需求域 | 状态 | 说明 |
|---|---|---|---|
| bug-list-evidence-structured-visible | 结构化证据落盘可见 | ✅ pass | `.bug-card`/`.bug-evidence` 可见；失败断言 type/期望/实际、截图路径、首个失败步骤文案全部命中；SSIM 0.963 |
| scenario-tab-failed-evidence-rendered | 场景页签逐断言证据 | ✅ pass | `.scenario.fail`、`.assertion.bad` 可见；`actual 不存在`、`步骤失败: click` 文案命中（首次运行已建基线） |
| bug-list-product-bug-not-suspended | 产品缺陷不悬置 | ⚠️ warning | **功能断言全通过**（见下文警告分析）；视觉 SSIM 0.918 低于 0.95 通过阈值 |
| bug-list-evidence-missing-empty-state | 证据缺失空状态 | ✅ pass | `.bug-card` 仍渲染、`.bug-evidence` 不存在（count=0），不渲染伪证据；SSIM 1.0 |
| escalation-banner-warning-stale-triage | 升级告警全要素渲染 | ✅ pass | 横幅/告警项/spec 标识/证据摘要可见；`连续 2 轮`、`1 条未处理`、`triage_recheck.json` 文案命中；SSIM 0.953 |
| escalation-banner-mark-handled-flow | 标记已处理处置闭环 | ✅ pass | `tri-002` 按钮移除、`tri-003` 不受影响、未处理计数降为 1；SSIM 0.983 |
| escalation-banner-clear-all-empty-state | 清理所有事件空状态 | ✅ pass | `.alert-item`/`.alert-banner-meta` 均清空（count=0），主内容区正常可交互（首次运行已建基线） |
| escalation-banner-list-toggle-collapse | 告警列表收起/展开 | ✅ pass | 按钮文本 `展开列表`、class `alert-list hidden` 精确匹配，计数与主体保持可见（首次运行已建基线） |
| regression-bug-list-no-classification-still-renders | 旧格式向后兼容回归 | ✅ pass | 旧格式（无 classification/evidence）仍渲染 Bug 卡片，证据块回退为空，无 JS 报错；SSIM 0.999 |

---

## 三、警告分析（不计为 Bug）

### bug-list-product-bug-not-suspended — 视觉比对 SSIM 0.918（第 4 层警告）

- **现象**：视觉比对 SSIM = 0.9179，低于 0.95 通过阈值，高于 0.85 警告阈值，触发 warning。
- **上下文核查**：该场景**所有第 1-3 层断言全部通过**：
  - `element_count` `.bug-card` 期望 2 == 实际 2 ✅
  - `.bug-card` 与 `.bug-evidence`（product-bug 证据未被悬置丢失）可见 ✅
  - `classification=product-bug`、`classification=test-defect`、`suspect-product-bug`（warning 误挂被修正标注）文案均命中 ✅
  - 页签按钮无点击遮挡 ✅
  - 无控制台错误 ✅
- **判定**：按第 4 层规则，SSIM 位于警告区间且无任何功能性失败证据，属次要渲染差异（页面含多张证据卡片，文本换行/高度细微差别可导致像素级差异），**不记为产品 Bug，不阻塞验证结论**。
- **证据文件**：`screenshots/bug-list-product-bug-not-suspended_diff.png`（diff 图可复查）。

---

## 四、需求覆盖结论

1. **非 PASS 场景结构化证据**：证据落盘（失败断言明细/截图/首个失败步骤）在「Bug 列表」渲染为 `.bug-evidence`（bug-list-evidence-structured-visible）；「场景结果」页签渲染逐断言 `.assertion.bad` 与失败步骤块（scenario-tab-failed-evidence-rendered）；证据为空时不渲染伪证据块、场景描述不丢失（bug-list-evidence-missing-empty-state）。✅
2. **分类与状态映射约束**：product-bug 与 test-defect 均映射为 failed 并各渲染证据卡片，未悬置；warning 场景误挂由采纳处重写并标注 `suspect-product-bug`（bug-list-product-bug-not-suspended，功能层全通过）。✅
3. **warning 连续悬置升级**：连续 2 轮 warning 触发 `warning_stale_triage` 升级横幅（全要素渲染）；「标记已处理」单条处置闭环（其余告警不受影响、计数 2→1）；「清理所有事件」批量清理后空状态无残留；列表收起/展开交互正常。✅
4. **向后兼容**：旧格式 report.json（无 classification/evidence 字段）解析不崩、Bug 卡片正常渲染、证据块回退为空、无 JS 报错。✅

---

## 五、豁免与环境说明

- 本轮无 `no_auth_error` 真实云端场景、无 `external_net_errors_ok` 豁免场景命中（各场景 `no_console_error` 的 `errors` 与 `filtered_network` 均为空）。
- 无断言时序问题（无「弹窗关闭后查询弹窗内元素」模式）。
- 3 个场景首次运行自动建立视觉基线（baseline_created），属正常初始化，非失败。
