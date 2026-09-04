# human-escalation-alerts Spec（delta）

## MODIFIED Requirements

### Requirement: 孤儿检测升级告警（已知中断不升级）

当 admin 处置 pending 超时（孤儿）时，升级人工告警 SHALL 仅在对应 run 文件（`.fenix/runs/<admin_run_id>.jsonl`）**不含 interrupted 标记**时产生。若 run 文件含 `{"type": "interrupted"}` 标记，SHALL 判定为已知中断（daemon 关闭所致）：终结该 pending disposition（追加非 pending 终结记录）且 SHALL NOT 产生人工升级告警。

#### Scenario: run 含 interrupted 标记 → 终结不升级

- **WHEN** AdminMonitor 巡检发现 pending disposition 超时，且其 admin_run_id 对应的 run 文件含 interrupted 标记
- **THEN** 追加 final disposition 记录（status=interrupted）终结该 run，且不产生人工升级告警；后续巡检因已终结而不再处理

#### Scenario: run 无 interrupted 标记 → 维持升级兜底

- **WHEN** AdminMonitor 巡检发现 pending disposition 超时，且 run 文件不存在或读不到 interrupted 标记
- **THEN** 按现有"疑似 daemon 崩溃"逻辑升级人工，并追加终结记录，防止循环告警

#### Scenario: 兜底语义保守

- **WHEN** pending 超时且 run 文件被清理策略删除（无证据可查）
- **THEN** 按"无 interrupted 标记"处理，升级人工（宁多告警不漏告警）