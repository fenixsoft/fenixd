# fix-visual-baseline-settle — verify_engine 视觉校验稳健性

## Why

六轮 judge（1788945507/1788947632/1788959262/1788960304/1788961185/1789000547）中，27 个 web 场景每轮 7-19 个仅截图 SSIM 失败而 DOM/功能断言全过，被迫逐场景归因，终验仍带 19 warning 入库。取证定案分两层：

1. **污染基线型（主因，16/19）**：首轮固化基线时 antd Modal 的 ~300ms fade 动画未完成（Playwright `visible` 判定不看 opacity，DOM 断言通过、截图却拍到动画早段的「弹窗未出现」画面），此后每轮正确截图与污染基线恒比恒低（SSIM 0.68-0.79 恒 `diff_detected`，差异像素 90%+，warning_streaks 最高 5 连）。
2. **时序噪声型（3/19）**：menu 类场景差异像素仅 2.71%（SSIM 0.89-0.93 `warning` 档），属渲染动画未 settle 的真实噪声。

框架缺口落点：`visual_diff.compare()` 截图前无 settle 等待、无重拍；首轮基线无条件固化，健全性判定只挡 blank/low_contrast，不校验「基线画面与断言态一致」。同类时序敏感 SPEC 将持续承受归因 token 与验证时长。

## What Changes

- **settle 等待**：`VisualDiffer.compare()` 截图前等待 `document.getAnimations()` 全部 finished（上限可配置，默认 3s），覆盖 `_wait_stable` 的 CLS 判定检测不到的 opacity 渐变动画。
- **SSIM 低于阈值自动重拍**：对比结果 `pass=False` 时自动重拍，重拍前再 settle，限 2 次，取最高 SSIM 分；仍低于阈值则维持原判定（不掩盖真回归）。
- **基线固化门**：首次固化基线的前置条件 = 该场景 step_results 与 assertion_results 全部通过；不满足则本轮不固化，视觉结果记 `status=baseline_deferred`（非 pass 非 fail，不进打回依据），下轮干净时正常固化。
- **存量污染基线侦测**：连续 ≥3 轮同场景 SSIM 恒 `diff_detected` 且 DOM 断言全过 → 基线标记 `suspicious` 并发人工告警；基线重建交人工确认，不自动覆盖。
- **明确不做**：按弹窗/列表场景类型分类校准 SSIM 阈值（取证显示 0.68-0.79 的污染基线型调阈值要么无效要么放走真回归；0.89-0.93 的噪声型靠 settle+重拍可拉回 0.95+，阈值非瓶颈）。

## Capabilities

### New Capabilities

- `visual-capture-robustness`：视觉对比截图的 settle 等待与失败自动重拍——截图前动画静置、低分限次重拍取最高分、仍低维持原判定。
- `visual-baseline-integrity`：视觉基线的固化门与污染侦测——首轮仅在场景步骤与断言全过时固化基线，否则 `baseline_deferred` 顺延；连续恒 diff_detected 且 DOM 全过时标记 suspicious 并告警。

### Modified Capabilities

（无——检索 `spec/specs/` 与 `spec/archive/` 确认无既有视觉校验能力 spec；现有 flaky 分类/triage/守卫/暂停语义 SPEC 均不涉截图稳健性，零重叠。）

## Impact

- **代码**：`core/verify_engine/visual_diff.py`（settle、重拍、固化门、suspicious 侦测主落点）；`core/verify_engine/web_runner.py`（视觉对比调用点微调：向 compare 传入场景通过性上下文）；`core/verify_engine/browser.py`（新增动画静置等待辅助，或直接内聚于 visual_diff）。
- **持久化**：`.fenix/verify-progress/<spec>/` 下视觉结果新增状态值 `baseline_deferred`；suspicious 标记与连续计数可复用 `warning_streaks.json` 同目录模式。
- **消费方兼容**：`determine_scenario_status` 与 judge 侧对视觉结果 `status` 的枚举需容忍 `baseline_deferred`（归入非打回依据，同 flaky/env 待遇）。
- **验收基线**：同夹具连续 3 轮全场景回放，「DOM 全过但 SSIM 失败」计数 ≤1（现状 19）；污染基线场景在固化门生效后下一轮自动恢复正常对比。
