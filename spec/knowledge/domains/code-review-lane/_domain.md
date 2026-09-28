# 代码审查

代码审查域：周期性代码审查 agent 车道（注册/调度/scope 两档/分片直写落盘/进度聚合可观测与停滞告警）、审查发现台账与项目页质量分面、审查发现转修复 SPEC 生成、实现期收尾 ocr 审查（异步车道 + testing 出口 join 门）及其配置、调优、写路径授权、运行中心跳与时间轴可见性。

## 能力页

- [code-review-agent](code-review-agent.md) — 周期性代码审查 agent（类型注册/自省同源调度/主产物+分片双轨落盘/禁等待收工/硬门聚合口径/进度取消/scope 两档）
- [code-review-progress-visibility](code-review-progress-visibility.md) — 审查进度聚合读侧与停滞告警（三侧聚合唯一入口/file 去重/零进度 admin 告警）
- [code-review-items](code-review-items.md) — 审查发现台账 items.jsonl（指纹去重与全仓快照核销）
- [code-review-quality-tab](code-review-quality-tab.md) — 项目页审查质量分面（问题表格/手动触发/真实进度/生成修复 SPEC）
- [code-review-spec-generation](code-review-spec-generation.md) — 审查发现转修复 SPEC 生成（复用既有链路/fix-cr 命名消解/幂等）
- [impl-code-review-gate](impl-code-review-gate.md) — 实现期收尾代码审查（总开关/run 级 provider 注入/报告契约/降级）
- [impl-code-review-setting](impl-code-review-setting.md) — 实现期审查开关配置（verify.impl_code_review 语义与设置页读写）
- [impl-code-review-tuning](impl-code-review-tuning.md) — 实现期审查调优参数（单请求超时/并发/力度）
- [impl-code-review-writepath](impl-code-review-writepath.md) — 验证进度写路径纪律与 --add-dir 授权矩阵
- [impl-code-review-gate-readback](impl-code-review-gate-readback.md) — 审查报告读侧判读归属
- [impl-ocr-parallel-lane](impl-ocr-parallel-lane.md) — ocr 异步审查车道 run_impl_ocr（指纹绑定/独立硬超时/增量游标）
- [impl-ocr-join-gate](impl-ocr-join-gate.md) — testing 出口 ocr join 门（双绿放行/gate 档打回上限 1 次/advisory 档）
- [ocr-lane-liveness-heartbeat](ocr-lane-liveness-heartbeat.md) — ocr 车道运行中心跳（≤60s progress/孤儿探针相容）
- [timeline-ocr-lane-visibility](timeline-ocr-lane-visibility.md) — 时间轴 ocr 车道可见性（节点身份/审查区间摘要/停等注记）
