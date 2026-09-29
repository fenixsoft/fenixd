# 视觉采集稳健性
<!-- knowledge: capability=visual-capture-robustness rev=1 sources=spec/archive/2026-09-17-fix-visual-baseline-settle -->

视觉对比截图的采集纪律：截图前动画静置、低分限次重拍取最高分，时序噪声不落为假差异。

## 现行规则

- 截图前动画静置（settle）：`VisualDiffer.compare()` 在截取当前页面截图前，通过 `document.getAnimations()` 检查所有进行中动画并等待其全部到达 finished 状态；等待上限可配置（配置键 `verify_engine.visual_settle_timeout_ms`，默认 3000ms）；达到上限仍有未完成动画时继续截图（退化为直接截图，不放大失败）；配置为 0 时跳过 settle 等待。
- SSIM 低于阈值自动重拍：对比结果 `pass=False`（SSIM 低于 pass 阈值）时自动重拍并重比，每次重拍前重新执行 settle 等待；限重拍 2 次（配置键 `verify_engine.visual_retake_max`），多次结果取最高 SSIM 分作为最终结果。
- 不掩盖真回归：重拍耗尽仍低于阈值则维持该判定（status 按既有阈值分档落 warning / diff_detected），不为通过而放宽阈值或篡改分数；首拍即通过时不执行任何重拍（零附加开销）。
- 重拍证据留痕：视觉结果 dict 记录 `retake_count`（实际重拍次数）与 `settle_waited_ms`（settle 实际等待时长，未等待为 0），供 judge 与事后取证区分「一次干净通过」与「重拍后通过」。

## 溯源

- 史前复原（存量基线） — 视觉校验以截图采集与基线 diff 判定，采集路径须稳健可重放，基线缺失不误判通过
- [2026-09-17 fix-visual-baseline-settle](spec/archive/2026-09-17-fix-visual-baseline-settle/) — 新增截图前动画静置等待与低分限次重拍取最高分（渲染动画未 settle 的时序噪声曾逐轮制造 SSIM 假差异，menu 类场景 2.71% 差异像素逐轮进归因）
