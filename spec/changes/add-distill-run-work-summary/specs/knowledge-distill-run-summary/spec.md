# knowledge-distill-run-summary 规格

## ADDED Requirements

### Requirement: 蒸馏批时间轴工作总结

蒸馏批 run 产物终态 `result` 行 SHALL 携带主蒸馏 agent 的工作总结文本（`result` 字符串字段），使 SPEC 详情运行时间轴的 run 节点总结盒无需读侧/前端改动即可渲染蒸馏产出摘要。

#### Scenario: 主蒸馏成功且 agent 输出总结

- **WHEN** 主蒸馏 spawn 成功且 stdout 含工作总结文本与尾部 `KNOWLEDGE_DISTILL_DONE` 标记行，批次校验通过并提交
- **THEN** 批次终态 `result` 行携带 `result` 字段，值为 stdout 剥离标记行后的文本（超上限时截断加「…（截断）」后缀）
- **AND** 时间轴 run 节点总结盒渲染该文本（既有 `_run_tail_insights` → `item.summary` 管道，零改动生效）

#### Scenario: stdout 为空或缺总结（fail-open）

- **WHEN** 主蒸馏成功但 stdout 为空、仅含标记行或缺总结文本
- **THEN** 终态 `result` 行不写 `result` 字段，蒸馏结果与台账行为与现状完全一致
- **AND** 时间轴 run 节点总结盒不渲染（字段缺失同 origin_request 口径）

#### Scenario: 标记缺失不判失败

- **WHEN** 主蒸馏成功（退出码 0 且 validate_knowledge 通过）但 stdout 无 `KNOWLEDGE_DISTILL_DONE` 标记行
- **THEN** 蒸馏成功判定不受影响（成功判据仍是退出码 + 校验脚本），stdout 全文（剥除逻辑空转）作为总结装配

#### Scenario: 失败路径不携带总结

- **WHEN** 主蒸馏 spawn 失败（非零退出/超时/校验违规放弃）
- **THEN** 终态 `error` 行不含总结文本，失败诊断形态与现状一致（stderr 尾部进 todo 台账 reason、stdout 摘要进日志照旧）

#### Scenario: 折叠子 run 不进总结

- **WHEN** 批次折叠前置段消化 `_inbox/` 条目（每条独立 spawn）
- **THEN** 折叠子 run 的 stdout 不进终态行，产物仍只有 `folded`/`fold_failed` 计数（语义不变）
