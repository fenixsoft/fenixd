# 代码审查
> 最后更新：2026-10-28 00:13 UTC+8

代码审查域：周期性代码审查 agent 车道（注册/调度/scope 两档/出题面 vendored 目录排除/分片直写落盘/进度聚合可观测与停滞告警/停滞看门狗自动收走）、审查发现台账与项目页质量分面（含手动触发受理回链与三态分派反馈）、审查发现转修复 SPEC 生成、全仓审查并发约束、全仓审查 429 限流终局自动续跑（剃余续跑/核销覆盖门/触发防叠加）、实现期收尾 ocr 审查（异步车道 + testing 出口 join 门）及其配置、调优、写路径授权、运行中心跳与时间轴可见性。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [code-review-agent](code-review-agent.md) | 周期性代码审查 agent（类型注册/独立触发时点缺省回退自省/窗口水位自承载/主产物+分片双轨落盘/禁等待收工/硬门聚合口径/进度取消/scope 两档） | 2026-10-28 00:13 |
| [vendored-review-scope](vendored-review-scope.md) | 出题面 vendored 目录排除（thirdparty/third_party/vendor 目录段精确匹配/单表派生两档自动生效/提示词如实化/fenix-ignore 上游同步标注第二道防线） | 2026-10-28 00:13 |
| [code-review-progress-visibility](code-review-progress-visibility.md) | 审查进度聚合读侧与停滞告警（三侧聚合唯一入口/file 去重/零进度 admin 告警） | 2026-10-03 04:59 |
| [review-run-stall-watchdog](review-run-stall-watchdog.md) | 审查 run 停滞看门狗（双判据停滞判定/自动取消/急救落账/单 run 去重告警） | 2026-10-03 05:58 |
| [code-review-items](code-review-items.md) | 审查发现台账 items.jsonl（指纹去重与全仓快照核销） | 2026-10-06 07:14 |
| [code-review-quality-tab](code-review-quality-tab.md) | 项目页审查质量分面（问题表格/手动触发/真实进度/生成修复 SPEC） | 2026-10-03 04:59 |
| [code-review-trigger-ack](code-review-trigger-ack.md) | 手动触发受理回链（daemon 三态落盘/GET run-result/POST 受理窗口守卫/前端受理等待态分派反馈） | 2026-10-06 07:14 |
| [code-review-spec-generation](code-review-spec-generation.md) | 审查发现转修复 SPEC 生成（复用既有链路/fix-cr 命名消解/幂等） | 2026-10-03 04:59 |
| [repo-review-concurrency](repo-review-concurrency.md) | 全仓审查并发单键双通道约束（子代理扇出上限 + ocr scan 并行度，缺省 4，与 SPEC 审查并发独立） | 2026-10-03 04:59 |
| [repo-review-ratelimit-resume](repo-review-ratelimit-resume.md) | 全仓审查限流终局续跑（429 归因双源/双车道共享重派消费/剃余续跑/核销覆盖门/open 阈值防叠加） | 2026-10-06 07:14 |
| [impl-code-review-gate](impl-code-review-gate.md) | 实现期收尾代码审查（总开关/run 级 provider 注入/报告契约/降级） | 2026-10-03 04:59 |
| [impl-code-review-setting](impl-code-review-setting.md) | 实现期审查开关配置（verify.impl_code_review 语义与设置页读写） | 2026-10-03 04:59 |
| [impl-code-review-tuning](impl-code-review-tuning.md) | 实现期审查调优参数（单请求超时/并发/力度） | 2026-10-03 04:59 |
| [impl-code-review-writepath](impl-code-review-writepath.md) | 验证进度写路径纪律与 --add-dir 授权矩阵 | 2026-10-03 04:59 |
| [impl-code-review-gate-readback](impl-code-review-gate-readback.md) | 审查报告读侧判读归属 | 2026-10-03 04:59 |
| [impl-ocr-parallel-lane](impl-ocr-parallel-lane.md) | ocr 异步审查车道 run_impl_ocr（指纹绑定/独立硬超时/增量游标） | 2026-10-03 04:59 |
| [impl-ocr-join-gate](impl-ocr-join-gate.md) | testing 出口 ocr join 门（双绿放行/gate 档打回上限 1 次/advisory 档） | 2026-10-03 04:59 |
| [ocr-lane-liveness-heartbeat](ocr-lane-liveness-heartbeat.md) | ocr 车道运行中心跳（≤60s progress/孤儿探针相容） | 2026-10-03 04:59 |
| [timeline-ocr-lane-visibility](timeline-ocr-lane-visibility.md) | 时间轴 ocr 车道可见性（节点身份/审查区间摘要/停等注记） | 2026-10-03 04:59 |
