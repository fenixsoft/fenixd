# 运行守护与失败韧性

运行守护与失败韧性。本域能力页清单如下（个别条目由后续回填批次产出，落盘后升级为链接）。

## 能力页

- [agent-run-timeout-supervision](agent-run-timeout-supervision.md) — agent run 超时监督
- `timeout-supervision` — 超时监督配置一致性
- [hang-discrimination](hang-discrimination.md) — 挂起与慢速判别
- [run-failure-classification](run-failure-classification.md) — run 失败三级分类与熔断
- [run-failure-judgment](run-failure-judgment.md) — run 失败判定（产物优先）
- [error-attribution-denoise](error-attribution-denoise.md) — 错误归因降噪
- [fail-counter-budget](fail-counter-budget.md) — 失败计数预算
- [per-spec-impl-budget](per-spec-impl-budget.md) — 单 SPEC 实现预算
- [run-budget-continuity](run-budget-continuity.md) — run 预算连续性
- `verify-recovery-budget` — 验证恢复预算豁免
- [run-cancel](run-cancel.md) — run 取消
- [run-superseded-terminal](run-superseded-terminal.md) — 被取代 run 的终态标记
- [runtime-run-sweep](runtime-run-sweep.md) — 运行时 run 清扫
- [redispatch-loop-governance](redispatch-loop-governance.md) — 重派循环治理
- [redispatch-artifact-succession](redispatch-artifact-succession.md) — 重派产物接续
- [honest-exit-convergence](honest-exit-convergence.md) — 诚实退出收敛
- [shared-result-file-integrity](shared-result-file-integrity.md) — 共享结果文件完整性
- `stale-verdict-race-guard` — 陈旧裁决竞态守卫
- [done-push-dedup](done-push-dedup.md) — done 推送去重
- `state-transition-idempotency` — 状态迁移幂等
- `state-write-atomicity` — 状态写入原子性
- `stuck-timeout-single-source` — stuck 阈值单源
- [orphaned-state-signal](orphaned-state-signal.md) — 孤儿状态信号
- [baseline-blocked-gate](baseline-blocked-gate.md) — 回归基线失败挂起门
- [lifecycle-hygiene](lifecycle-hygiene.md) — run 生命周期卫生
- [cli-retry-backoff](cli-retry-backoff.md) — CLI 退避重试
