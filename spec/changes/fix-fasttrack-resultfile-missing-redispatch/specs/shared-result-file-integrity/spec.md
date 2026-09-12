# shared-result-file-integrity — 共享结果文件完整性

## ADDED Requirements

### Requirement: 主树共享结果文件 stamp 严格匹配

读取主树共享结果文件 `.fenix/.fenix-run-result.json`（`_read_implementer_result` 的 fallback 路径）时，MUST 仅当文件的 `spec` 字段为字符串且严格等于当前 spec 名时才采信；`spec` 缺失、为空、非字符串或与当前 spec 不符时 MUST 一律 ignore（返回 None），MUST NOT 将无 stamp 残留误采信为当前 spec 的结果。

#### Scenario: stamp 不符则 ignore
- **GIVEN** 主树 `.fenix/.fenix-run-result.json` 的 spec=其它 spec（跨 spec 残留）
- **WHEN** daemon 读取当前 spec 的实现结果
- **THEN** 该文件被 ignore，返回 None（与现状行为一致，本次固化为契约）

#### Scenario: 无 stamp 残留同样 ignore（关闭 fail-open 洞）
- **GIVEN** 主树 `.fenix/.fenix-run-result.json` 存在但 `spec` 字段缺失、为空或非字符串（旧格式或异常残留）
- **WHEN** daemon 读取当前 spec 的实现结果
- **THEN** 该文件被 ignore，返回 None（不再 fail-open 采信）

#### Scenario: stamp 匹配则采信
- **GIVEN** 主树 `.fenix/.fenix-run-result.json` 的 spec 严格等于当前 spec
- **WHEN** daemon 读取当前 spec 的实现结果
- **THEN** 采信该文件内容并按现状语义处理

### Requirement: 共享结果文件消费后清理

主树共享结果文件 `.fenix/.fenix-run-result.json` 被某个 spec 采信消费并落盘 per-spec 快照（`.fenix/verify-progress/<spec>/impl-result.json`）后，daemon MUST 即时删除该共享文件，MUST NOT 让已消费的残留跨 spec 存留，消除对后续 spec 死亡判定/读侧的误拦与噪声。删除失败 MUST 仅记 WARNING 不阻塞主流程（fail-open，残留由上述 stamp 严格校验兜底拒绝）。

#### Scenario: 消费并落盘快照后删除共享文件
- **WHEN** daemon 采信读取主树共享结果文件（stamp 匹配）并完成本次消费、落盘 per-spec 快照
- **THEN** 该共享文件被删除
- **AND** 后续 spec 读取不再命中本 spec 的残留

#### Scenario: 删除失败仅记日志不阻塞
- **WHEN** 共享结果文件删除失败（OSError 等）
- **THEN** daemon 记录 WARNING 并继续主流程，残留由 stamp 严格校验在后续读取时拒绝