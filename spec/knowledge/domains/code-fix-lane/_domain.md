# 缺陷修复
> 最后更新：2026-10-30 21:11 UTC+8

缺陷修复。本域能力页清单如下。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [code-fix-lane](code-fix-lane.md) | 自动修复车道编排（两路激活/批循环/回归门合回与失败明细映射喂侧归一/合回冲突定向救回/回归异常熔断与零失败面收口及证据留存/失败批重派预算分档/与审查车道调度解耦） | 2026-10-30 21:11 |
| [codefix-affinity-batching](codefix-affinity-batching.md) | 选批文件亲和性装箱、波次上限自适应、批收尾回归两段式（中间批定向/末批全量兜底） | 2026-10-06 07:29 |
| [code-review-fix-pacing](code-review-fix-pacing.md) | 审查发现分级修复节奏（severity 门限与周批：总开关缺省旁路/达门限当日批/低于门限挂起整组周批放行/regression- 豁免/双入口同门/链收敛挂起对账） | 2026-10-30 21:01 |
| [codefix-test-targets-sanitization](codefix-test-targets-sanitization.md) | 回归占位符回退消毒（四条回退/重试路径占位符替换缺省 tests/、判别读原件、周期回归通道豁免） | 2026-10-06 07:29 |
| [codefix-digest-cost-metrics](codefix-digest-cost-metrics.md) | 消化链成本度量（run 工具构成指标 tool_uses/text_turns、链级 rollup 覆盖全部 run 不漏样本） | 2026-10-06 07:40 |
| [code-fix-batch-parallel](code-fix-batch-parallel.md) | 批内并行处置（orchestrator 派子代理、单写者落盘、三级兜底、边修复边提交收尾一次验证） | 2026-10-04 05:11 |
| [code-fix-api-timeout-salvage](code-fix-api-timeout-salvage.md) | 批 run API 超时签名判别与失败现场抢救（salvage 提交保全、legacy 复用接续、非超时行为保形） | 2026-10-06 02:53 |
| [code-fix-batch-selfheal](code-fix-batch-selfheal.md) | 修复批失败自愈（现场即弃〔API 超时例外走抢救〕、三态收尾、两层跳过与按回归终局形态分档的重试预算〔含 timeout 零失败面异常形态〕、登记闭环核销与解除核销终点对齐） | 2026-10-30 20:06 |
| [codefix-night-quiet-window](codefix-night-quiet-window.md) | 夜间静默窗投递守卫（落窗与预计跨窗双形态拦截、窗末自动放行、窗次幂等武装/解除留痕、与冷却取更晚共存、手动触发同受守卫） | 2026-10-26 01:16 |
| [code-fix-wipgate-defer](code-fix-wipgate-defer.md) | 修复批合回 WIP 阻断延迟合回（暂态零预算、现场保留+放锁、自动重试） | 2026-10-03 04:59 |
| [code-fix-agent](code-fix-agent.md) | code-fix 修复 agent | 2026-10-03 05:23 |
| [code-fix-config](code-fix-config.md) | code-fix 车道配置 | 2026-10-04 05:11 |
| [code-fix-progress](code-fix-progress.md) | 修复进度聚合与呈现 | 2026-10-03 04:59 |
| [code-fix-item-level-progress](code-fix-item-level-progress.md) | 修复批内条级进度（读侧实时合成与呈现） | 2026-10-03 04:59 |
| [code-fix-manual-trigger](code-fix-manual-trigger.md) | 手工触发修复的 checkpoint 授权 | 2026-10-03 04:59 |
| [regression-auto-fix](regression-auto-fix.md) | 回归问题一键自动修复（快照→code-fix 台账转换 + 触发回链） | 2026-10-03 04:59 |
| [correctness](correctness.md) | 代码审查正确性缺陷修复批（CR 台账机械生成） | 2026-09-27 18:05 |
| [robustness](robustness.md) | 代码审查健壮性缺陷修复批（CR 台账机械生成） | 2026-09-27 18:05 |
| [robustness-edge-cases](robustness-edge-cases.md) | 边界场景健壮性修复批 | 2026-10-03 04:59 |
| [deferred-findings-fixes](deferred-findings-fixes.md) | 审查遗留缺陷修复消化 | 2026-10-03 04:59 |
| [minor-defect-fastlane](minor-defect-fastlane.md) | 轻微缺陷快车道 | 2026-10-03 04:59 |
| [inplace-bug-repair](inplace-bug-repair.md) | 验证发现缺陷的原位修复 | 2026-10-03 04:59 |
| [bug-repair-mode-config](bug-repair-mode-config.md) | 缺陷修复模式配置 | 2026-10-03 04:59 |
| [repair-commit-enforcement](repair-commit-enforcement.md) | 修复必须落提交的强制门 | 2026-10-03 04:59 |
| [repair-lane-dedup](repair-lane-dedup.md) | 修复车道去重 | 2026-10-03 04:59 |
| [fix-chain-regression-inheritance](fix-chain-regression-inheritance.md) | 修复链回归继承 | 2026-10-03 04:59 |
| [fix-family-convergence-governor](fix-family-convergence-governor.md) | 修复族收敛治理 | 2026-10-03 04:59 |
