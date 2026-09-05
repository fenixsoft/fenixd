# verifier-selector-evidence 增量规格

## ADDED Requirements

### Requirement: 断言选择器必须来自实测 DOM

verifier 出题（生成 test_scenarios.json 的 assertion selector）MUST 遵守：
断言用 CSS 选择器 MUST 以被测应用实测 DOM 为准（通过 playwright 实查确认
元素存在且类名/属性与当前运行时一致），MUST NOT 凭训练知识直接引用框架
类名。该规则 MUST 写入 verifier 提示词（agents/verifier.md）的出题/断言
约束段，并以 antd v6 类名改名为反例说明（Collapse 内容类实测为
.ant-collapse-body/.ant-collapse-panel，训练知识中的 .ant-collapse-content
在 antd v6 已不存在）。

#### Scenario: verifier 提示词包含实测规则
- **WHEN** 读取 agents/verifier.md
- **THEN** 文件包含「断言选择器必须来自实测 DOM / playwright 实查」语义的
  强制规则（MUST 级措辞），且包含「不得凭训练知识引用框架类名」约束与
  antd v6 反例说明

#### Scenario: 出题阶段选择器先实查后落盘
- **WHEN** verifier 为场景编写 element_visible 等选择器断言
- **THEN** 提示词约束其先用 playwright 在被测应用中确认选择器命中目标
  元素，再写入 test_scenarios.json；未实查的框架类名选择器不得直接落盘
