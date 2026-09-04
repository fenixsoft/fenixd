# interaction-contract 增量规格

## ADDED Requirements

### Requirement: 可交互元素的行为契约
页面类 SPEC 的场景生成 MUST 保证：每个渲染为可交互形态的元素（按钮、链接样式卡片、可点击行、表单控件）至少对应一个交互场景（断言点击/操作后的可观察结果）；或在该元素定义处含「纯展示」声明。两者皆无的场景集 MUST 被判定为覆盖不完整并要求 planner 补齐。

#### Scenario: 卡片类元素必须声明或覆盖
- **GIVEN** 某页面渲染了带链接样式的项目卡片（dark-Card--link 类外观）
- **WHEN** 场景集生成
- **THEN** 存在覆盖「点击卡片后跳转/行为结果」的场景，或元素定义处含纯展示声明
- **AND** 二者皆无时 planner 输出校验失败并要求补齐

#### Scenario: 契约声明进场景集元数据
- **WHEN** planner 产出场景集
- **THEN** 每个可交互元素与场景的映射关系（或纯展示声明）记录在 scenarios.json 元数据中，可审计

### Requirement: 裁决逐断言归因
验证裁决对 failed 场景 MUST 逐条归类其全部失败断言（沿用 add-verdict-evidence-taxonomy 的四分类）；场景级豁免（不记产品 Bug）MUST 仅当该场景全部失败断言均被单独归类为非 product-bug 时成立。

#### Scenario: 单断言 product-bug 阻止场景豁免
- **GIVEN** 场景 X 有 3 条失败断言，其中 1 条归类 product-bug、2 条归类 env
- **WHEN** 裁决输出
- **THEN** 场景 X 判定 failed（product-bug），不得整体豁免

#### Scenario: 全断言非产品缺陷才可豁免
- **GIVEN** 场景 Y 全部失败断言归类 test-defect/flaky/env 且各附证据
- **WHEN** 裁决输出
- **THEN** 场景 Y 可整体豁免（warning），断言级清单入报告

### Requirement: 断言级豁免清单
验证报告 MUST 含「断言级豁免清单」小节：逐条列出被豁免的失败断言（场景、断言内容、归类、证据、豁免理由），供人工快速复核豁免是否掩盖真实缺陷。

#### Scenario: 报告可复核
- **WHEN** 存在被豁免的 failed 场景
- **THEN** 报告的豁免清单逐条可见（含 evidence 引用），而非仅场景级一句话归因

### Requirement: 实现任务书的契约呼应
实现 agent 任务书 MUST 要求：凡实现为可交互形态的元素，其行为在对应 SPEC 中有定义或在任务书中声明纯展示；无法两者满足时 agent MUST 在产出说明中列为「待裁决交互」而非静默保留可交互外观。

#### Scenario: 未定义行为的可交互元素被上报
- **GIVEN** 实现中发现某元素自然渲染为可交互形态但 SPEC 未定义行为
- **WHEN** 实现 run 收工
- **THEN** 产出说明含「待裁决交互」条目（元素、现状、建议行为），不静默
