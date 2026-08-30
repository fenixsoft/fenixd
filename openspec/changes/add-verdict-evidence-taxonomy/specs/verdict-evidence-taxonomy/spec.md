# verdict-evidence-taxonomy 增量规格

## ADDED Requirements

### Requirement: 非 PASS 场景强制分类
验证裁决对每个非 PASS 场景 MUST 输出 `classification` 字段，取值限 `{product-bug, test-defect, flaky, env}`；缺分类或取值非法时裁决输出校验失败，系统以持久化场景集重试一次裁决，仍失败则本轮验证按 blocked-env 处理并告警。

#### Scenario: 分类缺失被拦截
- **WHEN** 裁决输出含 failed 场景但无 classification
- **THEN** 输出校验失败，重试裁决；二次仍缺 → 本轮 blocked-env + 告警，不产生 bug-found 推进

### Requirement: 分类与状态的映射约束
`product-bug` 与 `test-defect` 分类 MUST 映射为场景状态 failed；`flaky` 与 `env` MAY 映射为 warning。禁止 product-bug 映射为 warning。

#### Scenario: 产品缺陷不得悬置
- **GIVEN** 裁决判定某场景根因是产品缺陷
- **WHEN** 输出场景状态
- **THEN** 该场景 status=failed 且 classification=product-bug

### Requirement: 非 PASS 场景结构化证据
每个非 PASS 场景 MUST 在 report.json 条目中附 `evidence`：至少含失败断言列表（type/selector/期望/实际）、截图相对路径、首个失败步骤；证据字段为空时按分类缺失同样处理（校验失败重试）。

#### Scenario: 证据完整落盘
- **WHEN** 场景 config-llm-provider-full-flow 判定 failed(product-bug)
- **THEN** report.json 该条目 evidence 含失败断言明细与截图路径
- **AND** 合成验证报告的「真实产品 Bug」小节引用该证据（不重复渲染）

### Requirement: warning 连续悬置升级
同一场景连续 2 轮判定为 warning 时，系统 MUST 在第 2 轮裁决采纳处发送 human-escalation-alerts 告警（内容含 spec、场景、连续轮次与最近证据摘要），并将该场景计入下一轮验证的优先复核清单。

#### Scenario: 两轮 warning 升级
- **GIVEN** 场景 X 第 N 轮与第 N+1 轮均为 warning
- **THEN** 第 N+1 轮裁决采纳时发送 triage 告警
- **AND** 第 N+2 轮验证的场景清单中 X 标记优先复核
