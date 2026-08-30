# 验证报告：add-fail-counter-budget

> ⚠️ 本报告由框架于 2026-08-30T06:34:02Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 11/13 场景通过，2 失败，0 错误（1 个真实产品 Bug）**

13 个场景：11 通过、2 失败、0 告警。全部 v1 界面场景（配置输入可见/编辑保存/高低越界拦截/空输入回退/保存回读闭环）、告警横幅（预算耗尽、验证失败升级）、SPEC 列表与详情（计数不归零、阻塞徽标、错误横幅、在线清除）均通过。2 个失败为同一 root cause 的系统性问题：v2 配置页未定义 agents.impl_run_budget 表单项，导致 v2 两个场景在元素查找阶段失败。属真实产品 Bug（v2 界面功能缺失），需修复后重跑 v2 两个场景。

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 2 |
| 错误 | 0 |
| 产品 Bug | 1 |


## 真实产品 Bug

### BUG-01（severity=major）· element_not_found（第1层 element_visible / element_enabled / no_click_interception 全链失败 + 步骤级 element_not_found_or_not_actionable）

- 关联场景：v2-config-budget-input-visible、v2-config-budget-edit-save
- 描述：v2 配置页「并行度设置」页签缺少 agents.impl_run_budget 数值编辑入口：input[name='agents.impl_run_budget'] 不存在，页面也无「实现尝试预算」文案。v1 界面同字段功能完整（可见/可改/可存/回读/越界校验均通过），v2 界面完全未落地该配置键，违反 proposal「What Changes」第 4 条「配置键必须带 Dashboard 界面」（且 v1/v2 双界面为项目既定要求）。
- 根因：core/dashboard/static/v2/pages/config.json 的「并行度设置」页签未添加 agents.impl_run_budget 的 input-number 表单项。源码核实：该文件中 grep 'impl_run_budget' 零命中，而同页签兄弟字段 agents.token_budget_millions 在第 43 行存在且渲染正常（场景中页签点击成功、无 console 错误），排除渲染链路问题，确认是表单项定义缺失。
- 证据：
  - v2-config-budget-input-visible: {"failed_assertions": ["element_visible input[name='agents.impl_run_budget'] → Locator.wait_for: Timeout 3000ms exceeded", "text_contains '实现尝试预算' → 页面无该文案", "element_enabled input[name='agents.impl_run_budget'] → 元素不存在", "no_click_interception input[name='agents.impl_run_budget'] → Locator.click: Timeout 3000ms exceeded"], "passed_controls": "no_console_error 通过（errors=[], filtered_network=[]），排除 JS 报错与网络问题；页签点击步骤成功，排除路由/页签问题", "screenshot": "/root/fenixd/.fenix/verify-progress/add-fail-counter-budget/screenshots/v2-config-budget-input-visible_assert_fail.png"}
  - v2-config-budget-edit-save: {"failed_step": "click input[name='agents.impl_run_budget'] → element_not_found_or_not_actionable（Timeout 5000ms），后续断言全部未执行", "passed_controls": "no_console_error 通过，页签点击成功"}
  - source_check: grep -c impl_run_budget core/dashboard/static/v2/pages/config.json → 0；grep -n token_budget_millions → 第 8 行（adaptor 默认值）、第 43 行（input-number 表单项）
  - v1_counterpart: v1 同字段 5 个场景（input-visible/edit-save/out-of-range-high/out-of-range-low/empty-input-fallback/save-roundtrip）全部通过


## 场景结果

| 场景 | 状态 | 失败断言 |
| --- | --- | --- |
| v1-config-budget-input-visible | pass | 0/6 |
| v2-config-budget-input-visible | fail | 4/5 |
| alert-impl-budget-exhausted-banner | pass | 0/7 |
| alert-verify-fail-escalation-banner | pass | 0/6 |
| spec-list-verify-fail-round-preserved | pass | 0/5 |
| spec-list-blocked-budget-exhausted | pass | 0/5 |
| spec-detail-blocked-budget-error | pass | 0/6 |
| v1-config-budget-edit-save | pass | 0/6 |
| v1-config-budget-out-of-range-high | pass | 0/6 |
| v1-config-budget-out-of-range-low | pass | 0/6 |
| v1-config-budget-empty-input-fallback | pass | 0/6 |
| v2-config-budget-edit-save | fail | - |
| v1-config-budget-save-roundtrip | pass | 0/4 |
