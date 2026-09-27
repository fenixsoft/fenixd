# SPEC 内容完整性门（空 spec 拦截）
<!-- knowledge: capability=spec-content-integrity-gate rev=1
     sources=spec/archive/2026-09-17-add-spec-content-integrity-gate -->

派发前校验 SPEC 目录含实质内容，空 spec 不进实现车道，冻结转人工处置。

## 规则

- 派发 implementer 或 fast-track 之前，校验 `spec/changes/<spec_name>/` 是否含实质内容：目录不存在、目录为空、或其中不存在 `proposal.md` / `design.md` / `tasks.md` / `specs/**/*.md` 任一文件时，判定为空 spec，中止派发。
- 目录内只有非 spec 内容文件（如 `.DS_Store`、日志）时同判为空 spec。
- 校验通过（四类文件任一存在）时按既有逻辑正常派发。
- 命中闸门的处置复用预算闸门冻结范式：状态置 `blocked`，`error` 记录「SPEC 内容缺失」原因，回滚队列占用，并经 `_send_human_escalation_alert` 发一条 `signal_type=spec_content_missing`、`severity=major` 的人工裁决告警。
- 处置幂等：已是 blocked 的空 spec 再次被派发逻辑评估时不重复发告警，但仍拒绝重派，不回落下一次派发。
- 告警生命周期闭环：`spec_content_missing` 接入 `alert_lifecycle._SIGNAL_CONDITIONS`，映射到 `spec_terminal_or_unblocked` 条件——SPEC 补上内容、解冻并离开 blocked（或到达终态）后告警自动标记 resolve，无需人工清理；SPEC 保持 blocked 期间告警保持未 handled 等待人工处置。
- 读取目录时 IO 异常（权限、临时不可达）保守放行派发并记 WARNING，不因校验自身故障误伤正常 SPEC。

## 溯源

- 2026-09-17 2026-09-17-add-spec-content-integrity-gate — 新增内容完整性门：派发前空 spec 判定、冻结处置与 spec_content_missing 告警、告警自动闭环、IO 异常保守放行
