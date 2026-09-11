# visual-capture-robustness

## ADDED Requirements

### Requirement: 视觉对比截图前的动画静置等待
`VisualDiffer.compare()` 在截取当前页面截图前，SHALL 等待页面动画静置（settle）：通过 `document.getAnimations()` 检查所有进行中动画，等待其全部到达 finished 状态；等待上限 MUST 可配置（配置键 `verify_engine.visual_settle_timeout_ms`，默认 3000ms）。达到上限仍有未完成动画时 SHALL 继续截图（退化为现行为，不放大失败）。

#### Scenario: 渐变动画完成后才截图
- **WHEN** 页面存在进行中的 opacity 渐变动画（如 antd Modal fade-in），调用 `compare()`
- **THEN** 截图发生在所有动画 finished 之后，截图画面为最终稳定态

#### Scenario: 动画超时退化为直接截图
- **WHEN** 页面存在持续超过 `visual_settle_timeout_ms` 的动画（如 SSE 驱动的循环动画）
- **THEN** 达到上限后仍执行截图，`compare()` 不因此失败或抛出异常

#### Scenario: 配置为零或禁用时不等待
- **WHEN** `visual_settle_timeout_ms` 配置为 0
- **THEN** 跳过 settle 等待，行为与现状（无 settle）完全一致

### Requirement: SSIM 低于阈值时自动重拍
`compare()` 在对比结果 `pass=False`（SSIM 低于 pass 阈值）时，SHALL 自动重拍并重比：每次重拍前重新执行动画静置等待，限重拍 2 次（可配置，配置键 `verify_engine.visual_retake_max`），多次结果取最高 SSIM 分作为最终结果。重拍后仍低于阈值则维持该判定（status 按既有阈值分档落 warning/diff_detected），MUST NOT 为通过而放宽阈值或篡改分数。

#### Scenario: 首拍时序噪声、重拍恢复
- **WHEN** 首拍因动画残留 SSIM=0.89（低于 0.95 pass 阈值），settle 后重拍 SSIM=0.97
- **THEN** 最终视觉结果 `status=pass`、`ssim=0.97`，结果中记录重拍次数

#### Scenario: 重拍耗尽仍低分则维持原判定
- **WHEN** 首拍与 2 次重拍 SSIM 均为 0.75（产品画面确与基线不一致）
- **THEN** 最终视觉结果为 `status=diff_detected`、`ssim=0.75`，不重拍第 3 次

#### Scenario: 首拍即通过不触发重拍
- **WHEN** 首拍 SSIM=0.98（≥ pass 阈值）
- **THEN** 不执行任何重拍，零附加开销

### Requirement: 重拍证据留痕
视觉结果 dict SHALL 记录 `retake_count`（实际重拍次数）与 `settle_waited_ms`（settle 实际等待时长，未等待为 0），供 judge 与事后取证区分「一次干净通过」与「重拍后通过」。

#### Scenario: judge 可见重拍轨迹
- **WHEN** 某场景经 1 次重拍后通过
- **THEN** 该场景 visual_results 中 `retake_count=1`、`settle_waited_ms>0`
