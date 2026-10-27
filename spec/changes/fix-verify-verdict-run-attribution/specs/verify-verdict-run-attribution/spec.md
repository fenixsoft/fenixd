## ADDED Requirements

### Requirement: verdict 文件派发侧归属戳

verify 派发时 MUST 在 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 原子预写归属戳 `{"run_id": <本次verify run_id>, "role": "verifier", "spec": <spec名>, "status": "dispatched"}`，使既有跨 run 残留在派发时刻即被覆盖。预写失败 MUST 仅落 WARNING、MUST NOT 阻断派发。

#### Scenario: 派发预写覆盖旧残留
- **WHEN** 共享 verdict 文件存在前一轮残留（如 `{"status": "plan-ready"}`）且 verify 被派发
- **THEN** 派发后文件内容为含本次 run_id 的归属戳，旧残留不再存在

#### Scenario: 预写失败不阻断
- **WHEN** 归属戳写入失败（目录缺失/权限等 OSError）
- **THEN** 派发流程照常继续，日志含 WARNING 留痕

### Requirement: verdict 消费侧归属校验

verdict 消费守卫 MUST 只采信「role 等于 verifier 且 run_id 等于当前被消费 verify run」的裁决。读取到其余形态（无归属戳、role 非 verifier——含 in-chain planner 的 plan-ready、run_id 不符、status 仍为 dispatched）时，MUST 将现文件归档为 `.fenix-run-result.json.stale-<ISO时间戳>` 备份，并按「本轮无裁决」既有 fail-closed 通道处置；MUST NOT 触发 stale/foreign 重放语义（MUST NOT 将当轮 verify 的完成判定为「他人结果重放」）。

#### Scenario: 归属一致且裁决合法
- **WHEN** verify 完成时共享文件为该 run 自己写出的合法 verdict（role=verifier、run_id 一致、status 在白名单内）
- **THEN** 裁决被正常采信，验证结论（bug-found/verified 等）按既有路径推进

#### Scenario: 跨 run 残留不再作废当轮成果
- **WHEN** verify 完成时共享文件为无归属戳或 run_id 不符的残留（如 planner 的 plan-ready）
- **THEN** 残留被归档为 `.stale-<ts>` 备份，本轮按「无裁决」fail-closed 处置（blocked + 告警），告警文案指明「本轮未产出机器可读裁决」，MUST NOT 出现「stale/foreign verifier result replayed」对当轮结果的归因

#### Scenario: 归属一致但 agent 未落裁决
- **WHEN** verify 完成时共享文件仍为派发时的归属戳（status=dispatched、run_id 一致）
- **THEN** 判「本轮未产出裁决」，走既有 fail-closed 通道，不引用任何残留内容作为裁决

### Requirement: 重派丢弃前验证成果保全

stale/foreign 重派收敛点（`_redispatch_fresh_verify`）在丢弃 verifier 结果重派前，MUST 检查 `.fenix/verify-progress/<spec>/report.json` 是否存在且 mtime 不早于本轮 verify 派发时刻；满足时 MUST 将其重命名保全为 `report-<run_id>.json` 并落 WARNING + 升级告警文案附保全路径，MUST NOT 静默丢弃。

#### Scenario: 新鲜 report 强制保全
- **WHEN** 重派触发时 verify-progress 下存在本轮派发之后写入的 report.json
- **THEN** report 被重命名保全（`report-<run_id>.json`），WARNING 与升级告警文案均含保全后路径，重派照常进行

#### Scenario: 无新鲜 report 不保全
- **WHEN** 重派触发时 report.json 不存在或 mtime 早于本轮派发时刻
- **THEN** 不产生保全文件，重派按既有路径进行
