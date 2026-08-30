# 验证报告：add-cost-observability

> ⚠️ 本报告由框架于 2026-08-30T03:10:00Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 0/7 场景通过，7 失败，0 错误（2 个真实产品 Bug）**

7/7 场景全部失败，聚合成 2 个系统性 Bug（均为 Layer 1 元素不可见，产品缺失）。Bug1：SPEC 详情页「Token 消耗（累计）」治理卡未渲染（影响 4 个场景）。Bug2：配置页「Token 预算（百万，0=关闭）」输入框未渲染（影响 3 个场景）。两处均为 SPEC 的 MUST 级核心展示/配置面。页面加载本身正常（所有 no_console_error / no_network_error 通过，errors 为空），无密钥/签名错误、无网络不可达，故判定为产品功能未实现/未挂载，而非环境或网络问题。需实现并挂载 Token 累计卡片与预算输入控件后重新验证。

| 指标 | 数量 |
| --- | --- |
| 通过 | 0 |
| 失败 | 7 |
| 错误 | 0 |
| 产品 Bug | 2 |


## 真实产品 Bug

### BUG-01（severity=major）· element_visible (Layer 1) + 下游 Layer 3 text 断言

- 关联场景：spec-detail-token-card-visible、spec-detail-token-card-empty-state、spec-detail-cost-unavailable-when-gateway-no-cost、spec-detail-token-card-no-console-reflow
- 描述：SPEC 详情页（#spec/:project/:name）治理区「Token 消耗（累计）」卡片完全未渲染。4 个场景均因 h3:has-text('Token 消耗（累计）') 在超时后仍不可见而失败；其后续的文本断言（输入/输出 累计 token、空状态 0.0M、成本不可用（网关未回传）标注）因卡片本身不存在而连带失败。这是本 SPEC「Dashboard 与报告展示」MUST 级要求的核心展示面，目前整块缺失。
- 根因：spec-detail 页面模板（spec-detail.json 的 Token 消耗卡 tpl）未渲染或未被 adaptSpecDetail 注入。页面本身加载正常（无 console / network 错误，导航成功），但预期的令牌累计卡片未出现在治理区 DOM 中，推断为成本观测卡片的渲染逻辑/数据绑定缺失或挂载点错误。
- 证据：
  - selector: h3:has-text('Token 消耗（累计）')
  - representative_error: Locator.wait_for: Timeout 3000ms exceeded. waiting for locator("h3:has-text('Token 消耗（累计）')").first to be visible
  - console_errors: []
  - network_errors: []

### BUG-02（severity=major）· element_visible (Layer 1) / element_enabled (Layer 1) / element_not_found (step)

- 关联场景：config-budget-input-rendered、config-budget-input-zero-disables、config-budget-input-out-of-range-rejected
- 描述：配置页（#config）并行度设置 Tab 内「Token 预算（百万，0=关闭）」数值输入框完全缺失。3 个场景均失败：标签不可见、输入框不存在（input-number 控件未渲染），点击步骤报 element_not_found_or_not_actionable。该控件是 agents.token_budget_millions 配置键的带界面铁律控件，min=0/max=1000 的边界与 0=关闭 语义均无法验证。
- 根因：config.json 中编号为 43 的 input-number 控件（Token 预算（百万，0=关闭））未在配置页正常渲染，或配置页对应 Tab 未挂载该控件。页面加载无报错（no_console_error 通过，errors:[]），推断为配置控件定义缺失、未正确挂载到并行度 Tab，或控件 key/tpl 绑定错误。
- 证据：
  - selector: label:has-text('Token 预算（百万，0=关闭）')
  - representative_error: Locator.wait_for: Timeout 3000ms exceeded. waiting for locator("label:has-text('Token 预算（百万，0=关闭）')").first to be visible
  - click_step_error: Locator.wait_for: Timeout 5000ms exceeded. waiting for locator("label:has-text('Token 预算（百万，0=关闭）')").locator("../following-sibling::div//input").first to be visible
  - console_errors: []


## 场景结果

| 场景 | 状态 | 失败断言 |
| --- | --- | --- |
| spec-detail-token-card-visible | fail | 3/5 |
| config-budget-input-rendered | fail | 3/4 |
| spec-detail-token-card-empty-state | fail | 2/3 |
| spec-detail-cost-unavailable-when-gateway-no-cost | fail | 2/4 |
| spec-detail-token-card-no-console-reflow | fail | 1/2 |
| config-budget-input-zero-disables | fail | - |
| config-budget-input-out-of-range-rejected | fail | - |
