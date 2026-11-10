# 运行守护与失败韧性
> 最后更新：2026-11-10 11:24 UTC+8

运行守护与失败韧性。本域能力页清单如下。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [agent-run-timeout-supervision](agent-run-timeout-supervision.md) | agent run 超时监督 | 2026-10-15 01:55 |
| [timeout-supervision](timeout-supervision.md) | 超时监督配置一致性 | 2026-10-03 04:59 |
| [hang-discrimination](hang-discrimination.md) | 挂起与慢速判别 | 2026-10-03 04:59 |
| [run-failure-classification](run-failure-classification.md) | run 失败三级分类与熔断 | 2026-10-03 04:59 |
| [arbiter-lane-infra-failure-reset](arbiter-lane-infra-failure-reset.md) | arbiter 车道故障分级与 infra 复位（0 rounds/环境指纹秒挂不烧死人开关资格、两级前置自检 TTL 闸拦截零状态变更、探针 healthy 三触发点复位、链 infra-failed deferred 留痕） | 2026-11-10 11:24 |
| [run-failure-judgment](run-failure-judgment.md) | run 失败判定（产物优先） | 2026-10-03 04:59 |
| [error-attribution-denoise](error-attribution-denoise.md) | 错误归因降噪与取证判读（死因误标防护：exit 143 判读、自杀排除、日志归属层、复发三轴、在飞识别与转录前缀盲区、悬空 run 判读、kill 来源 ftrace 插桩） | 2026-11-04 16:30 |
| [fail-counter-budget](fail-counter-budget.md) | 失败计数预算 | 2026-10-03 04:59 |
| [per-spec-impl-budget](per-spec-impl-budget.md) | 单 SPEC 实现预算 | 2026-10-03 04:59 |
| [run-budget-continuity](run-budget-continuity.md) | run 预算连续性 | 2026-10-03 04:59 |
| [verify-recovery-budget](verify-recovery-budget.md) | 重启重验预算与超限冻结 | 2026-10-03 04:59 |
| [run-cancel](run-cancel.md) | run 取消（原语、全链路取消语义与取消前现场保全） | 2026-10-30 18:20 |
| [run-superseded-terminal](run-superseded-terminal.md) | 被取代 run 的终态标记 | 2026-10-03 04:59 |
| [runtime-run-sweep](runtime-run-sweep.md) | 运行时 run 清扫 | 2026-10-03 04:59 |
| [redispatch-loop-governance](redispatch-loop-governance.md) | 重派循环治理（同因重派熔断、成果继承、人工停靠失控重派=预算闸门落点） | 2026-11-04 16:30 |
| [redispatch-artifact-succession](redispatch-artifact-succession.md) | 重派产物接续 | 2026-10-03 04:59 |
| [honest-exit-convergence](honest-exit-convergence.md) | 诚实退出收敛 | 2026-10-03 04:59 |
| [shared-result-file-integrity](shared-result-file-integrity.md) | 共享结果文件完整性 | 2026-10-03 04:59 |
| [stale-verdict-race-guard](stale-verdict-race-guard.md) | 陈旧裁决竞态守卫 | 2026-10-03 04:59 |
| [done-push-dedup](done-push-dedup.md) | done 推送去重 | 2026-10-03 04:59 |
| [state-transition-idempotency](state-transition-idempotency.md) | 状态迁移幂等 | 2026-10-03 04:59 |
| [state-write-atomicity](state-write-atomicity.md) | 状态写入原子性 | 2026-10-03 04:59 |
| [stuck-timeout-single-source](stuck-timeout-single-source.md) | stuck 阈值单源 | 2026-10-03 04:59 |
| [orphaned-state-signal](orphaned-state-signal.md) | 孤儿状态信号 | 2026-10-08 02:52 |
| [baseline-blocked-gate](baseline-blocked-gate.md) | 回归基线失败挂起门 | 2026-10-03 04:59 |
| [lifecycle-hygiene](lifecycle-hygiene.md) | run 生命周期卫生 | 2026-10-03 04:59 |
| [cli-retry-backoff](cli-retry-backoff.md) | CLI 退避重试 | 2026-10-03 04:59 |
| [run-stop-loss](run-stop-loss.md) | run 级止损（attempt 间隙取消/重试让位/停滞预算） | 2026-10-04 03:36 |
| [cli-stderr-noise-filtering](cli-stderr-noise-filtering.md) | CLI stderr 诊断噪声统一判别与降噪（判别单源、深扫摘要与回填归因消费端、admin 证据豁免、unrecognized_model 双形态判读） | 2026-11-04 15:55 |
| [impl-env-blocker-stop-loss](impl-env-blocker-stop-loss.md) | impl 环境阻塞止损与任务停滞预警 | 2026-10-14 14:06 |
| [killpg-self-guard](killpg-self-guard.md) | 进程清场击杀自保护守卫（禁命中调用者自身进程组）与人工杀回归进程组止血配方 | 2026-11-04 16:30 |
