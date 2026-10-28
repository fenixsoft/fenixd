## ADDED Requirements

### Requirement: 裁决选项可声明 requires_payload

注册表选项条目 MUST 支持可选布尔键 `requires_payload`：置 `true` 表示该选项的动作执行 MUST 以 JSON 载荷为输入（载荷经处置记录 `choice_payload` 或人工裁决 note 传入）。未声明该键的选项 MUST 按 `false` 处理（缺省无需载荷）。`requires_payload` MUST 为纯静态声明，与 id/label/desc/action 同级同源维护；载荷要求的判定 MUST 收敛注册表单源——消费侧（处置产物硬门、自动执行通道）MUST 从注册表解析结果读取该位，MUST NOT 各自硬编码选项名单。初始仅 `revise_scenario_reverify` 置 `true`。

#### Scenario: 载荷必需选项解析携带声明位
- **WHEN** 经注册表解析 `revise_scenario_reverify`（任意 signal_type 上下文）
- **THEN** 解析结果携带 `requires_payload=true`，与该选项在注册表中的声明一致

#### Scenario: 未声明选项缺省无需载荷
- **WHEN** 经注册表解析未声明 `requires_payload` 的选项（如 `manual_fixed_reverify`）
- **THEN** 解析结果该位为 `false`，消费侧按无需载荷处理，处置无 `choice_payload` 时硬门放行

#### Scenario: 注册表保持纯静态
- **WHEN** 审阅 `core/dashboard/data/adjudication_choices.py` 中 `requires_payload` 的维护形态
- **THEN** 为模块常量内的静态声明，无 LLM 生成、无运行时写入
