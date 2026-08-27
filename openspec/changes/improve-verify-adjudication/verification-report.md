# 验证报告：improve-verify-adjudication

## 结论

**验证未通过（bug-found）**

- 总场景数：17
- 通过：11
- 失败：6
- 警告：0
- 错误：0

所有 6 个失败场景均为**前端渲染 / 交互缺陷**，不存在鉴权签名错误、网络层故障或 console 异常。判定为产品 Bug，已派生 fix 流程。

---

## 通过场景（11）

| 场景 ID | 关键信号 |
|---|---|
| smoke-dashboard-serves-8787 | Dashboard 在 8787 正常提供新代码，概览页标题/卡片网格可见 |
| gate-all-pass-releases | 全过路径不被误拦：无错误横幅、状态「完成」、进度 17/17 |
| gate-progress-only-blocks | fail-closed 生效：进度满但存在 11 失败，滞留「已验证」并拦截 |
| result-file-missing-blocked | 结果文件缺失 → fail-closed 不放行，横幅含「verifier 结果缺失」 |
| result-unknown-status-blocked | 未知 status（success）→ fail-closed，不误读残留 |
| fix-add-xxx 正向（fix-tree-single-inherits / fix-tree-multi-level-inherits / fix-regression-gap-blocked / fix-regression-all-pass-releases） | fix 树渲染、回归闭环缺口拦截、全部通过放行均正常 |
| result-verified-clean-close | verified 正常闭环推进到 done |
| report-special-chars-escaped | 特殊字符 HTML 安全转义，无 XSS 注入 |

---

## 失败 Bug（按根因聚合，4 项）

### Bug #1 〔major〕详情页「场景结果 / Bug 列表」卡片未渲染（系统性）
**影响场景：** gate-tool-noise-stays-verified、gate-product-defect-bug-found、fix-admin-exempt-closes（3 个场景同一根因 → 系统性问题）

**现象：**
- `.scenario.fail`、`.scenario.fail .assertions .assertion.bad`、`.bug-card` 均 `Locator.wait_for: Timeout` 不可见 / `evaluate` 找不到节点。
- 对照：上述场景的状态徽章（已验证 / 有Bug / 完成）、错误横幅、进度区均**正常渲染**，且 `no_console_error` 全部为空。

**根因推断：**
详情页场景结果渲染管线在「存在失败场景」的分支下未挂载卡片节点。空数据分支正常（scenarios-tab-empty-state 的 `.empty-state` 可见），说明渲染管线本身可用，但 populated/failed 分支未输出 `.scenario.fail` / `.bug-card`。这直接破坏了验证裁决的可观察面——失败场景明细、断言 ✗ 徽标、派生 Bug 卡片在 UI 上失联。

**证据：**
- gate-tool-noise-stays-verified: `Timeout 3000ms — .scenario.fail .assertions .assertion.bad`；`Timeout 30000ms — .scenario.fail 找不到节点`
- gate-product-defect-bug-found: `Timeout — .bug-card`；`Timeout — .bug-card .bug-evidence`；`Timeout — .scenario.fail .assertions .assertion.bad`
- fix-admin-exempt-closes: `Timeout — .scenario.fail`（豁免后仍应可见的场景 Z 未渲染）

---

### Bug #2 〔major〕人工升级告警项 / 处理按钮被 CSS 隐藏
**影响场景：** alert-banner-escalation-shows

**现象：**
- `.alert-item` 与 `.alert-handled-btn` 在 DOM 中**已存在但被隐藏**（`10 × locator resolved to hidden`），管理员无法在界面上定位并处置；`.alert-item` 文本断言实际能拿到 noise-spec 内容，仅不可见。
- 横幅标题（⚠ 需人工介入）与计数（1 条未处理）正常渲染。

**根因推断：**
告警项列表 / 处理按钮渲染后被 CSS 隐藏（疑似默认折叠或 `display/visibility` 样式错误），使 human-escalation-alerts 的「可被管理员定位处置」目标失效。

---

### Bug #3 〔major〕规格 error 信息子行「清除」动作失效
**影响场景：** spec-error-clear-removes-row

**现象：**
- 点击 `.info-clear-btn` 无遮挡（`no_click_interception` 通过）、无网络错误（`no_network_error` 通过）；
- 但操作后 `.spec-info-row` 仍残留 `actual_count: 5`，信息子行未消失。

**根因推断：**
清除 POST 成功后前端状态未刷新或重载数据未反映清除结果（mock 仍返回含 error 的数据或局部刷新未触发），error 子行持续存在。

---

### Bug #4 〔minor〕场景结果空状态文案与 SPEC 不符
**影响场景：** scenarios-tab-empty-state

**现象：**
- `.empty-state` 可见、`.scenario` 不存在（结构正确）；
- 但文案为「暂无运行时间轴」，而非 SPEC 要求的「report.json 损坏或不可读」/「暂无场景结果」。

**根因推断：**
空状态文案硬编码或取错字段，与「场景结论质量闸门缺失/损坏」的语义不匹配。

---

## 判定规则适用说明

- 第 1 层（element_visible / element_not_exist 失败）与第 3 层（text_match 失败）断言失败，按规则直接记为 Bug，无反例（SPEC 未声明动态内容豁免）。
- 无 `no_auth_error` 签名/密钥关键词、无 `filtered_network` 网络层错误、无 console 错误，故不存在环境/网络免责情形。
- 无「弹窗关闭后断言弹窗内元素」的时序模式。

---

## 修复优先级建议

1. **P0 — Bug #1（系统性）**：修复详情页场景结果渲染管线，确保 populated/failed 分支正确挂载 `.scenario.fail` / `.bug-card` 及其断言 ✗ 徽标。影响 3 个场景，是验证裁决可观察面的核心缺口。
2. **P1 — Bug #2 / #3**：解除告警项 CSS 隐藏、修复 error 清除动作的状态刷新。
3. **P2 — Bug #4**：对齐空状态文案与 SPEC 语义。
