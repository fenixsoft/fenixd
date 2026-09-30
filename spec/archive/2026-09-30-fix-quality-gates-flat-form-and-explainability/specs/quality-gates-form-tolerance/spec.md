## ADDED Requirements

### Requirement: 读侧采信顶层平铺形态的 quality-gates.json

落盘契约的合法形态仍是嵌套形态 `{"gates": {<gate-id>: {...}}, "updated_at": ...}`；
读侧 `parse_quality_gates` 在文件为合法 JSON dict 但**缺 `gates` 键（或 `gates` 值非 dict）**时，
MUST 按以下规则尝试平铺形态容错：

- 候选门集 = 顶层所有「值为 dict 且其 `status` 字段 ∈ `GATE_STATUSES` 枚举」的键；
- 候选门集非空，且顶层**不存在**「值为 dict 但 `status` 枚举外（或缺 status）」的键
  → 按平铺形态采信，候选门集即 `file_gates`；
- 存在任一「值为 dict 但 status 枚举外」的顶层键，或候选门集为空
  → 不采信平铺，`file_gates` 视为空（维持既有 pending/unknown 语义，不误读）。

平铺采信后的一切下游处理（契约外 gate-id 忽略、`_run_gate_status` 单门判定、
full-suite 双源优先级）MUST 与嵌套路径逐字节一致。

#### Scenario: 嵌套形态优先零回归

- **WHEN** 文件顶层含合法 dict 形态的 `gates` 键（含空 dict）
- **THEN** 读侧行为与本变更前逐字节一致，平铺判定不参与

#### Scenario: 纯平铺形态被采信

- **WHEN** 文件顶层为 `{"frontend-build": {"status": "passed", ...},
  "interaction-contract": {"status": "passed", ...}}`（无 `gates` 键，可有字符串型
  `updated_at` 等元数据键）
- **THEN** 两项 run 自查门按落盘值合成 passed，detail 透传原文，done 计数随之正确

#### Scenario: 平铺中的契约外 gate-id 被忽略

- **WHEN** 平铺形态文件中含 `code-review` 等契约外键（值为合法 gate 条目形态）
- **THEN** 该键被忽略（与嵌套路径的契约外键处理一致），不污染六道门合成

#### Scenario: 平铺含枚举外 status 整体不采信

- **WHEN** 平铺形态文件中任一 dict 值的 `status` 不在枚举（如 `"status": "ok"`）或缺 status
- **THEN** 不采信平铺，`file_gates` 视为空——宁可渲染 pending/unknown 也不误读半个文件

#### Scenario: 空顶层 dict 不采信

- **WHEN** 文件为合法 JSON 但顶层是空 dict `{}`
- **THEN** 候选门集为空，不采信平铺，维持既有「文件可读但键未写 → pending」语义

#### Scenario: 损坏文件语义不变

- **WHEN** 文件无法解析（非法 JSON / 编码错误）
- **THEN** 维持既有 `(None, exists=True)` → unknown「门禁记录缺失或损坏」语义，
  平铺判定不参与
