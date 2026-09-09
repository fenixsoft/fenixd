# verify-contract 起草信号语义拆分（verify-contract-signal-dispatch）

## ADDED Requirements

### Requirement: 覆盖重起草改派 redraft 信号

`POST /api/verify-yaml-autodraft` 在契约可解析（`load_verify_contract` 非 None）且请求携带覆盖确认（overwrite=true）时，MUST 派发 `verify_contract_redraft` 信号类型（severity=major、`source=ui-manual`、overwrite 标记与项目名 evidence 语义与既有 missing 信号一致）；`verify_contract_missing` MUST 仅用于契约文件缺失或解析失败场景。两类型的响应均为 dispatched。

#### Scenario: 有效契约覆盖确认派发 redraft
- **WHEN** 项目存在可解析契约且请求带 overwrite=true
- **THEN** AdminStore 写入 `signal_type=verify_contract_redraft` 的 SIGNAL 记录（含 `source=ui-manual`、`overwrite=true`、`evidence` 含项目名），响应 status=dispatched

#### Scenario: 契约缺失仍派发 missing
- **WHEN** 项目无 `.fenix/verify.yaml` 或解析失败时调用端点
- **THEN** 仍写入 `verify_contract_missing` SIGNAL 记录，响应 dispatched（行为与既有一致）

#### Scenario: 有效契约无覆盖确认仍跳过
- **WHEN** 项目契约可解析且请求未带 overwrite
- **THEN** 响应 skipped，不写任何信号（既有行为不变）

### Requirement: admin_monitor 注册 redraft 信号

`core/admin_monitor.py` MUST 注册 `verify_contract_redraft`：SIGNAL_SEVERITY 映射为 `major`；SIGNAL_RECOMMENDATION 提供区别于 missing 的处置指引（先复核现有契约有效性——有效契约按 D4 权限边界默认不碰，用户已显式授权覆盖时方可重起草，重起草草稿同样须经 bin/fenix_verify_contract.py 三段自证全通后才落位）；STORED_SIGNAL_TYPES 收录该类型；`_detect_family_explosion` 的 spec 空值项目名提取分支 MUST 同时覆盖 redraft 类型。

#### Scenario: redraft 信号被消费唤起
- **WHEN** AdminStore 存在未 escalated 的 `verify_contract_redraft` 信号（spec 为空、evidence 含「项目名=fenixd」）
- **THEN** admin_monitor 巡检拾取该信号，按 evidence 提取项目名唤起 Administrator，处置建议为 redraft 专用指引（非 missing 的起草指引）

#### Scenario: redraft 指引区别于 missing
- **WHEN** 读取 SIGNAL_RECOMMENDATION 中两类型的指引文本
- **THEN** `verify_contract_redraft` 的指引包含「复核现有契约有效性」与「用户已显式授权覆盖」语义，与 `verify_contract_missing` 的纯起草指引可区分
