# 验证报告：add-verdict-credibility-gate

> ⚠️ 本报告由框架于 2026-09-10T03:21:41Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 19/19 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 19/19 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 19 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.80M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| screenshot-blank-white-label | 纯白截图产出 blank_screenshot 标签并含量化指标（pixel_std<0.012, dominant>99%, 255x255）——screenshot_lab.py (screenshot_lab.py:classify_screenshot) | pass | 0/2 | - |
| screenshot-low-contrast-label | 低对比度截图（像素 std 在 0.012–0.08 区间）产出 low_contrast 标签，不误判为 blank——screenshot_lab.py (screenshot_lab.py:classify_screenshot) | pass | 0/2 | - |
| screenshot-normal-no-label | 正常内容截图不产生 blank_screenshot 或 low_contrast 标签（无标签=正常，向后兼容）——screenshot_lab.py (screenshot_lab.py:classify_screenshot) | pass | 0/2 | - |
| screenshot-classify-failure-nonblocking | 判定失败（不存在文件/损坏文件）不抛异常，返回空 dict，截图主流程不被阻断——screenshot_lab.py (screenshot_lab.py:classify_screenshot) | pass | 0/2 | - |
| attribution-level-no-evidence-speculative | 无截图/无标签/无结构化字段的失败场景，compute_attribution_level 返回 speculative——归因证据分级门 (verdict_check.py:compute_attribution_level) | pass | 0/2 | - |
| attribution-level-evidence-backed | 有失败断言归因（assertion_triage 非空）+截图路径，compute_attribution_level 返回 evidence-backed——归因证据分级门 (verdict_check.py:compute_attribution_level) | pass | 0/2 | - |
| attribution-level-pending-visual | 视觉断言（screenshot_mismatch 类）无截图佐证时 compute_attribution_level 返回 pending-visual——归因证据分级门 (verdict_check.py:compute_attribution_level) | pass | 0/2 | - |
| attribution-level-write-report-json | validate_attribution_levels 为全部非 PASS 场景写入 attribution_level 字段，PASS 场景不写入——report.json 持久化 (verdict_check.py:validate_attribution_levels) | pass | 0/2 | - |
| attribution-suppress-speculative-bug-found | 所有驱动场景（product-bug/test-defect）均为 speculative 时 should_suppress_bug_found 返回 True（抑制打回）；至少一个 evidence-backed 返回 False——推测归因门禁 (verdict_check.py:should_suppress_bug_found) | pass | 0/2 | - |
| attribution-blank-screen-forces-env | 白屏标签约束归因方向：enforce_blank_screenshot_direction 对 product-bug 场景返回 env 强制改写——空白屏幕归因约束 (verdict_check.py:enforce_blank_screenshot_direction) | pass | 0/2 | - |
| attribution-cache-freshness-tag | 指纹命中的 verdict_cache 场景获得 cached_from_previous_round=true+来源轮次；无截图无标签时纯缓存归因降级 speculative——归因新鲜度治理 (verdict_check.py:tag_cached_attributions) | pass | 0/2 | - |
| attribution-batch-dedup-identical | 3 个场景逐字相同归因被 check_batch_attribution_dedup 拒绝（ok=false），2 个相同放行——归因查重阈值边界 (verdict_check.py:check_batch_attribution_dedup) | pass | 0/2 | - |
| attribution-whitespace-normalization-dedup | 归一化空白后 token1   token2 与 token1 token2 等价，3 场景相同即拒绝——归因查重归一化 (verdict_check.py:check_batch_attribution_dedup) | pass | 0/2 | - |
| baseline-blank-rejected | VisualDiffer 首次基线时白屏截图命中 blank_screenshot 标签，返回 baseline_rejected 状态，基线文件不创建——视觉基线防污染 (visual_diff.py:compare) | pass | 0/2 | - |
| inconclusive-under-threshold-no-signal | 第 1-3 轮全批 blocked-env 不写入 inconclusive_loop SIGNAL，_inconclusive_attempts 逐轮累加——循环升级门限内不提前唤起 (verification.py:_handle_env_blocked_inconclusive) | pass | 0/2 | - |
| inconclusive-threshold-writes-signal | 第 4 轮全批 blocked-env 写入 kind=SIGNAL(inconclusive_loop)，记录含 spec 名/连续轮数/末轮 blocked_env 数——循环升级阈值触发 (verification.py:_write_inconclusive_loop_signal) | pass | 0/2 | - |
| inconclusive-threshold-configurable | 配置 inconclusive_escalate_attempts=2，第 2 轮全批 blocked-env 即触发 SIGNAL 写入——阈值可配 (verification.py:_handle_env_blocked_inconclusive) | pass | 0/2 | - |
| inconclusive-manual-reset-restart | 人工清 _inconclusive_attempts=0 后下一轮从 1 重新计数，不因旧残留触发升级——人工处置后计数清零 (verification.py + state_machine) | pass | 0/2 | - |
| admin-monitor-ingests-inconclusive-signal | admin_monitor 检测到 inconclusive_loop SIGNAL 记录后调用 _invoke_administrator，处置建议含验证环境核查清单——admin_monitor 摄取与唤起 (admin_monitor.py:_detect_family_explosion) | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 19 个（第 1 轮）。

- 首轮写入 19 个场景

