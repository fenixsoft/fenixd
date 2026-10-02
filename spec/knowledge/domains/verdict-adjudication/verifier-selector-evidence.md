<!-- knowledge: capability=verifier-selector-evidence rev=1 sources=spec/archive/2026-09-11-fix-verify-verdict-visibility -->

# verifier 选择器证据

verifier 出题断言选择器的实测来源约束：CSS 选择器必须来自被测应用实测 DOM，防止框架类名知识过期导致 test-defect 复发。

## 现行规则

- verifier 出题（生成 test_scenarios.json 的 assertion selector）MUST 以被测应用实测 DOM 为准：先通过 playwright 实查确认元素存在且类名/属性与当前运行时一致，再写入 test_scenarios.json；MUST NOT 凭训练知识直接引用框架类名；未实查的框架类名选择器不得直接落盘。
- 该规则以 MUST 级措辞写入 agents/verifier.md 的出题/断言约束段，并附反例说明：antd v6 的 Collapse 内容类实测为 `.ant-collapse-body`/`.ant-collapse-panel`，训练知识中的 `.ant-collapse-content` 在 antd v6 已不存在。

## 溯源

- 2026-09-11 fix-verify-verdict-visibility（spec/archive/2026-09-11-fix-verify-verdict-visibility） — 确立断言选择器「先 playwright 实查后落盘」的强制约束，写入 verifier 提示词出题/断言约束段并附 antd v6 类名改名反例
