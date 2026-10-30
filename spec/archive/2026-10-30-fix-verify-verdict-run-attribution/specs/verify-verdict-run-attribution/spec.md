## ADDED Requirements

### Requirement: verdict 文件派发侧归属戳

verifier 派发单点（`core/pm_engine/dispatch/queue.py` verifier 出队分支，worker 线程启动前）MUST 在 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 原子预写归属戳 `{"role": "verifier", "spec": <spec名>, "status": "dispatched"}`（不含 run_id：run/attempt id 在 runner attempt 环内才生成，派发点不可得），使既有跨 run 残留在派发时刻即被覆盖。预写失败 MUST 仅落 WARNING、MUST NOT 阻断派发。

#### Scenario: 派发预写覆盖旧残留
- **WHEN** 共享 verdict 文件存在前一轮残留（如 `{"status": "plan-ready"}`）且 verify 被派发
- **THEN** 派发后文件内容为三键归属戳（role=verifier、spec 匹配、status=dispatched），旧残留不再存在

#### Scenario: 预写失败不阻断
- **WHEN** 归属戳写入失败（目录缺失/权限等 OSError）
- **THEN** 派发流程照常继续，日志含 WARNING 留痕

### Requirement: verdict 消费侧归属校验

verdict 消费守卫（report_gate.py `_read_verdict` 单点）MUST 按三分支处置：①文件为 status 白名单内的正常裁决（含既有无 role 戳的新鲜 primary 直写形态）→ 照既有口径采信，MUST NOT 将 role 门套到 primary（防误杀当轮 agent/judge 现写裁决）；②文件仍为本次派发预写戳（role=verifier 且 status=dispatched）→ 判「本轮未产出裁决」，走既有 fail-closed 通道（blocked + critical 告警）；③陈旧 mtime / 异 spec 戳 / 异归属残留 → MUST 先归档为 `.fenix-run-result.json.stale-<ISO时间戳>` 备份，再按「本轮无裁决」fail-closed 通道处置；MUST NOT 触发 stale/foreign 重放语义（MUST NOT 将当轮 verify 的完成判定为「他人结果重放」），MUST NOT 保留自动整轮重派处置。丢弃当轮成果进入 fail-closed 前，MUST 按「重派丢弃前验证成果保全」要求保全 report.json。新鲜 plan-ready（本轮派发后 in-chain planner 写出）不属残留，MUST 照既有「验证未完成」通道处置（保持 testing 待重验），MUST NOT 判 fail-closed。

#### Scenario: agent 正常写出的新鲜裁决被采信
- **WHEN** verify 完成时共享文件为该 run 自己写出的合法 verdict（status 在白名单内、mtime 新鲜，含既有无 role 戳的 primary 直写形态）
- **THEN** 裁决被正常采信，验证结论（bug-found/verified 等）按既有路径推进，不因无 role/run_id 戳被判「本轮无裁决」

#### Scenario: 跨 run 残留不再作废当轮成果
- **WHEN** verify 完成时共享文件为陈旧残留（mtime 早于本轮派发时刻或异 spec 戳，如上一轮 planner 的 plan-ready）
- **THEN** 残留被归档为 `.stale-<ts>` 备份，本轮按「无裁决」fail-closed 处置（blocked + 告警），告警文案指明「本轮未产出机器可读裁决」，MUST NOT 出现「stale/foreign verifier result replayed」对当轮结果的归因，且不触发自动整轮重派

#### Scenario: agent 未落裁决（预写戳原样）
- **WHEN** verify 完成时共享文件仍为派发预写戳原样（role=verifier、status=dispatched）
- **THEN** 判「本轮未产出裁决」，走既有 fail-closed 通道，不引用任何残留内容作为裁决

#### Scenario: 新鲜 plan-ready 照既有通道
- **WHEN** verify 派发后 in-chain planner 在本轮窗口内写出新鲜 plan-ready 且 verifier 未落裁决
- **THEN** 按既有「验证未完成」通道处置（保持 testing 待重验），MUST NOT 判 fail-closed blocked，MUST NOT 归档覆盖 planner 当轮产物

### Requirement: fail-closed 丢弃前验证成果保全

verdict 消费守卫判「残留 / 本轮未产出裁决」、丢弃当轮成果进入 fail-closed 前，MUST 检查 `.fenix/verify-progress/<spec>/report.json` 是否存在且 mtime 不早于本轮 verify 派发时刻；满足时 MUST 将其重命名保全为 `report-<run_id>.json` 并落 WARNING + 升级告警文案附保全路径，MUST NOT 静默丢弃。保全 MUST NOT 挂在 stale/foreign 重派收敛点（`_redispatch_fresh_verify`）——本 SPEC 改向后该点在 verdict 消费链不可达。

#### Scenario: 新鲜 report 强制保全
- **WHEN** 守卫判「残留 / 本轮未产出裁决」时 verify-progress 下存在本轮派发之后写入的 report.json
- **THEN** report 被重命名保全（`report-<run_id>.json`），WARNING 与升级告警文案均含保全后路径，fail-closed 处置照常进行

#### Scenario: 无新鲜 report 不保全
- **WHEN** 守卫判「残留 / 本轮未产出裁决」时 report.json 不存在或 mtime 早于本轮派发时刻
- **THEN** 不产生保全文件，fail-closed 处置照既有路径进行
