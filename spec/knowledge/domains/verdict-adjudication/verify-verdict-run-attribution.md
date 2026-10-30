# verdict 文件 run 级归属戳与采信判据

<!-- knowledge: capability=verify-verdict-run-attribution rev=1
     sources=spec/archive/2026-10-30-fix-verify-verdict-run-attribution -->

共享 verdict 文件（`.fenix/verify-progress/<spec>/.fenix-run-result.json`）的 run 级归属治理：跨 run 残留永不作为本轮 verdict 输入，当轮验证成果丢弃前强制保全留痕（ADR-123 role 戳单读口的深化）。

## 规则

- **派发侧归属戳**：verifier 派发单点（dispatch queue verifier 出队分支，worker 线程启动前）在共享 verdict 文件原子预写归属戳 `{"role": "verifier", "spec": <spec名>, "status": "dispatched"}`——既有跨 run 残留在派发时刻即被覆盖；戳不含 run_id（run/attempt id 在 runner attempt 环内才生成且逐 attempt 变化，派发点不可得，「agent 未写裁决」由「预写戳仍原样」二值判定）；预写失败仅落 WARNING、MUST NOT 阻断派发。
- **消费侧三分支**（verdict 读取守卫 `_read_verdict` 单点，legacy 与三阶段 judge 车道共用）：① status 白名单内的正常裁决——含既有无 role 戳的新鲜 primary 直写形态——照既有口径采信，MUST NOT 将 role 门套到 primary（防误杀当轮 agent/judge 现写裁决）；② 文件仍为本次派发预写戳原样（role=verifier 且 status=dispatched）→ 判「本轮未产出裁决」，走既有 fail-closed 通道（blocked + critical 告警，文案「本轮未产出机器可读裁决」），不引用任何残留内容作为裁决；③ 陈旧 mtime / 异 spec 戳 / 异归属残留 → 先归档为 `.fenix-run-result.json.stale-<ISO时间戳>` 备份（保留法证现场），再走同一 fail-closed 通道。残留处置 MUST NOT 触发 stale/foreign 重放语义（MUST NOT 将当轮 verify 的完成判定为「他人结果重放」）、MUST NOT 保留自动整轮重派处置。
- **新鲜 plan-ready 隔离**：in-chain planner 在本轮派发窗口内写出的 plan-ready 不属残留——照既有「验证未完成」通道处置（保持 testing 待重验），MUST NOT 判 fail-closed、MUST NOT 归档覆盖 planner 当轮产物；陈旧 plan-ready 残留走③分支。
- **fail-closed 丢弃前验证成果保全**：守卫判「残留 / 本轮未产出裁决」、丢弃当轮成果进入 fail-closed 前，检查 `.fenix/verify-progress/<spec>/report.json` 存在且 mtime 不早于本轮 verify 派发时刻——满足时 MUST 将其重命名保全为 `report-<run_id>.json` 并落 WARNING + 升级告警文案附保全路径，MUST NOT 静默丢弃。mtime 比较统一 UTC 口径（派发时刻优先从 result.run_id 内嵌 epoch 解析，解析失败回退本轮 run 流文件启动时刻）；保全 MUST 挂在 fail-closed 丢弃点，MUST NOT 挂 stale/foreign 重派收敛点（该点在此语义下不可达，保全将永不触发）。

## 关键行为

治理前后的最坏情况对比：跨 run 残留 + 真实验证完成 → 旧语义误判「重放」作废整轮验证（多轮各数十分钟、发现 major 缺陷的成果整体丢弃且无保全）；新语义残留归档留痕、当轮 report.json 保全、诚实 blocked 转人工。

## 溯源

- 2026-10-30 fix-verify-verdict-run-attribution（spec/archive/2026-10-30-fix-verify-verdict-run-attribution） — 新增本能力：派发侧三键归属戳预写、消费侧三分支采信判据（残留/未产出裁决/正常裁决）、残留语义从「stale/foreign 重放」改为「本轮无裁决 fail-closed + 成果保全」、新鲜 plan-ready 既有通道隔离（动因实测：plan-ready 残留致两轮各 39 分钟真实验证被当作重放整体作废且丢弃时无成果保全）
