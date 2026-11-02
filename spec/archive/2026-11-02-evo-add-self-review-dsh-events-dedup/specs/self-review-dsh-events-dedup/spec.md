## ADDED Requirements

### Requirement: 伴随事件流不计入 run 统计
自省聚合的 run 文件收集 MUST 排除 .dsh-events 后缀文件，dsh run 在 runs 统计中计 1 次，伴随流不得进入 stale（无终态残留）桶。

#### Scenario: 主文件与伴随流并存
- **WHEN** 归档目录同时存在某 run 的 .jsonl 与 .dsh-events.jsonl
- **THEN** runs 统计计 1 次，stale 桶不出现 .dsh-events 伪 run_id

#### Scenario: 合法 run 不受影响
- **WHEN** 收集面扫描含正常命名 run 文件的目录
- **THEN** 统计行为与既有用例完全一致（过滤不误伤）