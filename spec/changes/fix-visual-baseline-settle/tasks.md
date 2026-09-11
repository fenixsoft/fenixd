## Deliverables

```yaml
- path: core/verify_engine/visual_diff.py
  kind: modify
- path: core/verify_engine/web_runner.py
  kind: modify
- path: core/verify_engine/browser.py
  kind: modify
- path: core/verify_engine/runner.py
  kind: modify
- path: core/verdict_check.py
  kind: modify
- path: tests/test_visual_capture_robustness.py
  kind: new
- path: tests/test_visual_baseline_integrity.py
  kind: new
```

## 1. settle 等待（visual-capture-robustness）

- [x] 1.1 `browser.py` 新增 `wait_animations_settled(page, timeout_ms)` 辅助：页面注入 JS 检查 `document.getAnimations()`，全部 finished 即返回 True，达上限返回 False；注入异常按超时退化返回 False，不抛出
- [x] 1.2 `visual_diff.py` `compare()` 截图前调用 settle：读配置 `verify_engine.visual_settle_timeout_ms`（默认 3000，0=禁用），记录实际等待时长
- [x] 1.3 TDD：动画进行中→settle 后才截图；超时动画→达上限继续截图不抛异常；timeout_ms=0→跳过等待行为与现状一致（对应 spec「动画静置等待」三场景）

## 2. SSIM 低分自动重拍（visual-capture-robustness）

- [x] 2.1 `visual_diff.py` `compare()` 对比结果 `pass=False` 时重拍限次：每次重拍前再 settle，读配置 `verify_engine.visual_retake_max`（默认 2），取最高 SSIM 分；仍低于阈值维持原判定，不放宽阈值不篡改分数
- [x] 2.2 视觉结果 dict 记录 `retake_count` 与 `settle_waited_ms`（未等待为 0）
- [x] 2.3 TDD：首拍噪声重拍恢复→pass 且 retake_count=1；三拍均 0.75→diff_detected 且恰重拍 2 次；首拍 0.98 通过→零重拍零附加开销（对应 spec「自动重拍」三场景）

## 3. 基线固化门（visual-baseline-integrity）

- [x] 3.1 `web_runner.py` `_execute_scenario` 向 `differ.compare()` 传入场景通过性上下文（steps_failed + 断言失败信息）
- [x] 3.2 `visual_diff.py` `compare()` 基线不存在分支：先走既有 blank/low_contrast 健全性判定（保持不变），通过后再查通过性上下文——步骤或断言存在失败则不固化，返回 `status=baseline_deferred`
- [x] 3.3 `runner.py` `determine_scenario_status`：`baseline_deferred` 不计为视觉失败（不落 warning/failed，场景按 DOM 断言正常判档）
- [x] 3.4 `verdict_check.py`：`baseline_deferred` 归入非驱动场景（与 env/flaky 同不参与打回判定），确认既有豁免通道对其放行
- [x] 3.5 TDD：步骤失败场景首轮→baseline_deferred 且不固化；下轮干净→正常固化；DOM 全过+baseline_deferred→场景非 failed 且 judge 不计打回（对应 spec「固化前置条件」三场景）

## 4. 存量污染基线侦测（visual-baseline-integrity）

- [x] 4.1 `visual_diff.py` 新增连续异常计数：持久化 `.fenix/verify-progress/<spec>/baseline_streaks.json`（同 warning_streaks.json 模式）；同场景连续 `diff_detected` 且 DOM 全过累计，任一轮恢复非 diff_detected 清零并撤 suspicious，`baseline_deferred` 不累计不清零
- [x] 4.2 连续 ≥3 达阈值：基线旁写 `<name>.suspicious` 标记文件 + 复用 admin 人工告警通道（正文含场景 ID、各轮 SSIM、基线路径）；不自动覆盖或删除基线
- [x] 4.3 TDD：三连 diff_detected+DOM 全过→第 3 轮告警+标记；中途恢复→清零无告警；一轮 DOM 真失败→该轮不累计不告警；跨重启计数延续；baseline_deferred 轮计数保持（对应 spec「污染侦测」「计数持久化」全部场景）

## 5. 集成验证与收尾

- [x] 5.1 既有视觉相关测试回归全绿（`tests/` 中涉及 visual_diff/web_runner/verdict_check 的存量用例）
- [x] 5.2 真实夹具回放验证：同夹具连续 3 轮全场景执行，「DOM 全过但 SSIM 失败」计数 ≤1（现状 19）；固化门生效后下轮基线画面与断言态一致（settle 后重截自证）
- [x] 5.3 配置键文档化：`visual_settle_timeout_ms` / `visual_retake_max` 写入 help 文档 config 章节，标注 Dashboard 设置页暂不纳入（YAML-only，后续按需补 UI）
