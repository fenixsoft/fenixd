<!-- knowledge: capability=admin-choices-contract rev=1 sources=spec/archive/2026-09-27-add-human-adjudication-choices -->

# Administrator 处置与裁决注册表共用契约

Administrator agent 的自动处置与人工下拉选择收敛为同一裁决空间的契约（`agents/administrator.md` 处置输出段）。

## 现行规则

- Administrator 处置桶 2 信号时，先读取该 signal_type 在裁决选项注册表中的选项集；处置结论优先表达为 `choice_id` + 依据，写入处置记录的结构化字段。
- 仅当注册表无对应选项（处置超出既有裁决空间）时才允许自由处置，且必须在处置记录中回填「建议注册表新增选项」字段（含建议 id/label/action 语义），供自省通道消费。
- 框架消费处置记录时，`choice_id` 与人工下拉选择走同一执行路径：同一动作映射、同一留痕格式。
- `kind=SIGNAL` 类携带 choices 的记录（如 `build_artifact_paths_missing`，不进前端告警区）由本契约消费：Administrator 处置时按注册表选项表达结论。

## 溯源

- [2026-09-27 add-human-adjudication-choices](spec/archive/2026-09-27-add-human-adjudication-choices/) — 建立 Administrator 处置优先消费注册表、choice_id 结构化表达、超出裁决空间回填建议的契约
