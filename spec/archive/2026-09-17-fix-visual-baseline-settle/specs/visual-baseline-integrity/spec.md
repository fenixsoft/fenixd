# visual-baseline-integrity

## ADDED Requirements

### Requirement: 基线固化前置条件
首次固化视觉基线（`baselines/<name>.png` 不存在）时，SHALL 仅在该场景 step_results 全部 `success=True` 且 assertion_results 全部 `pass=True` 时固化；不满足前置条件时本轮不固化，视觉结果记 `status=baseline_deferred`（非 pass 非 fail），已有健全性判定（blank/low_contrast 拒绝固化）保持不变并继续生效。`baseline_deferred` SHALL 被下游状态判定（`determine_scenario_status`）与 judge 归因视为非打回依据（同 flaky/env 待遇：允许出现在 warning，不构成 bug-found 打回）。

#### Scenario: 弹窗动画未完成时不固化污染基线
- **WHEN** 某场景首拍时 Modal fade 动画未完成（画面无弹窗），DOM 断言全部通过但固化的候选截图与断言态不一致（此处以「该场景存在任一 step 或 assertion 失败」以外的可观测代理判定——即 step+assertion 全过为固化条件）
- **THEN** 若 step+assertion 全过则正常固化；若存在失败则不固化，视觉结果 `status=baseline_deferred`

#### Scenario: 步骤失败场景顺延基线固化
- **WHEN** 首轮执行中某场景步骤失败（断言未执行），且该场景声明了 visual_baseline
- **THEN** 本轮不固化基线，视觉结果 `status=baseline_deferred`；下一轮该场景干净执行时正常固化

#### Scenario: baseline_deferred 不进打回依据
- **WHEN** 某场景本轮视觉结果为 `baseline_deferred`，DOM 断言全部通过
- **THEN** 该场景整体 status 不因视觉项落 failed，judge 侧不将其计入 bug-found 打回依据

### Requirement: 存量污染基线侦测与告警
对已存在基线的场景，SHALL 追踪连续异常：同场景连续 ≥3 轮视觉结果 `status=diff_detected` 且同期 DOM 断言全部通过 → 将该基线标记为 `suspicious` 并发出人工告警（复用既有 admin 告警通道）。连续计数随任一轮该场景 SSIM 恢复非 diff_detected 而清零。基线重建 SHALL 交人工确认，框架 MUST NOT 自动覆盖或删除已固化基线。

#### Scenario: 三连恒失败触发 suspicious 告警
- **WHEN** 场景 A 连续 3 轮 SSIM<0.85（diff_detected）且每轮 DOM 断言全过
- **THEN** 第 3 轮后基线被标记 suspicious、发出人工告警，附场景 ID、各轮 SSIM 值与基线文件路径

#### Scenario: 中途恢复清零计数
- **WHEN** 场景 A 已连续 2 轮 diff_detected，第 3 轮 settle+重拍后 SSIM 恢复 0.96
- **THEN** 连续计数清零，不产生告警，基线保持正常状态

#### Scenario: DOM 有真实失败时不误报
- **WHEN** 场景 B 连续 3 轮 SSIM<0.85，但其中一轮存在 DOM 断言失败
- **THEN** 连续计数重置（该轮不累计），不触发 suspicious 告警——真实产品缺陷不伪装成基线污染

### Requirement: 连续计数持久化
连续异常计数 SHALL 持久化于 `.fenix/verify-progress/<spec>/` 下（与 `warning_streaks.json` 同目录同模式），daemon 重启或跨轮次执行后计数不丢失；`baseline_deferred` 轮不累计也不清零计数（等下次真实对比再判定）。

#### Scenario: 跨轮次计数延续
- **WHEN** 场景 A 第 N 轮 diff_detected（计数 1），daemon 重启后第 N+1 轮仍 diff_detected
- **THEN** 计数延续为 2，第 N+2 轮 diff_detected 达 3 触发 suspicious 告警

#### Scenario: baseline_deferred 不干扰计数
- **WHEN** 场景 A 第 N 轮 diff_detected（计数 1），第 N+1 轮因步骤失败为 `baseline_deferred`
- **THEN** 第 N+1 轮计数保持 1 不变；第 N+2 轮 diff_detected 后计数为 2
