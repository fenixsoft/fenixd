# 视觉校验基线完整性
<!-- knowledge: capability=visual-baseline-integrity rev=1 sources=spec/archive/2026-09-17-fix-visual-baseline-settle -->

视觉基线的固化门与污染侦测：基线只在场景干净通过时固化，恒失败且 DOM 全过的基线标记 suspicious 转人工。

## 现行规则

- 固化前置条件：首次固化视觉基线（`baselines/<name>.png` 不存在）仅在该场景 step_results 全部 `success=True` 且 assertion_results 全部 `pass=True` 时进行；不满足则本轮不固化，视觉结果记 `status=baseline_deferred`（非 pass 非 fail），下一轮该场景干净执行时正常固化。既有健全性判定（blank/low_contrast 拒绝固化）继续生效。
- baseline_deferred 不进打回依据：`baseline_deferred` 被下游状态判定（`determine_scenario_status`）与 judge 归因视为非打回依据（同 flaky/env 待遇——允许出现在 warning，不构成 bug-found 打回）。
- 存量污染基线侦测：同场景连续 ≥3 轮视觉结果 `status=diff_detected` 且同期 DOM 断言全部通过 → 该基线标记 `suspicious` 并发出人工告警（附场景 ID、各轮 SSIM 值与基线文件路径）；任一轮该场景 SSIM 恢复非 diff_detected 时连续计数清零；该轮存在 DOM 断言失败时计数重置不累计——真实产品缺陷不伪装成基线污染。
- 基线重建交人工：框架不自动覆盖或删除已固化基线，suspicious 基线的重建由人工确认。
- 连续计数持久化：连续异常计数持久化于 `.fenix/verify-progress/<spec>/` 下（与 `warning_streaks.json` 同目录同模式），daemon 重启或跨轮次执行后不丢失；`baseline_deferred` 轮不累计也不清零计数（等下次真实对比再判定）。

## 溯源

- 2026-09-17 fix-visual-baseline-settle（spec/archive/2026-09-17-fix-visual-baseline-settle） — 新增基线固化门与污染基线三连侦测（首轮固化曾无条件放行，Modal fade 动画未完成的「弹窗未出现」画面被固化为基线，此后每轮正确截图与污染基线恒比恒低，六轮 judge 被迫逐场景归因）
