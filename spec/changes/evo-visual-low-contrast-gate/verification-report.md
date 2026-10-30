# 验证报告：evo-visual-low-contrast-gate

> ⚠️ 本报告由框架于 2026-10-30T15:39:21Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T15:39:20.442403+00:00+run-result@mtime1793374760481620717

## 结论：✅ 通过（verified）

**状态：verified — 15/15 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 15/15 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.15M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| lab-constants-and-helper-contract | R1 阈值常量与场景名匹配助手契约：LOW_CONTRAST_STD_UPPER=0.08、LOW_CONTRAST_STD_UPPER_RELAXED=0.095（放宽档>缺省档）；声明性子串（empty/zero-state/placeholder/low-contrast/low_contrast）大小写不敏感命中、连字符与下划线两形态均覆盖；未声明名与非字符串上下文（None/int）回退缺省 0.08。出处 core/verify_engine/screenshot_lab.py:32-76 | pass | 0/9 | - |
| classify-relaxed-band-mechanism | R1 判定带机制：同一贴阈值合成画面（pixel_std∈[0.08,0.095)，确定性种子生成）在缺省 0.08 上限下无标签、在放宽 0.095 上限下判 low_contrast（带扩宽生效）；深度低对比（std≈0.011）两档均判；真空白（纯白）在放宽上限下仍判 blank_screenshot（放宽不影响 blank 通道）；正常高方差画面两档均无标签（缺标签=正常态契约不变）。出处 core/verify_engine/screenshot_lab.py:184-192（判定分支）、:39（放宽常量） | pass | 0/10 | - |
| pytest-screenshot-lab-suite-green | 交付测试套件 tests/test_screenshot_lab.py 全绿（19 用例，-v 逐用例 PASSED）：场景感知放宽（TestScenarioAwareLowContrastUpper）、匹配助手（TestScenarioAwareHelper）、两调用侧传参（TestScenarioAwareCallSites）、异常安全（TestClassifyScreenshotExceptionSafety）。出处 tests/test_screenshot_lab.py:148-349、tasks.md 3.1 | pass | 0/12 | - |
| pytest-anti-pollution-suite-green | 交付测试套件 tests/test_visual_baseline_anti_pollution.py 全绿（12 用例，-v 逐用例 PASSED）：白屏拒绝/正常固化/拒绝后重建（TestVisualBaselineAntiPollution）、门内收敛复核与证据落盘（TestGateConvergenceRecheck：收敛放行、仍污染拒绝、复测失败 fail-closed、证据落盘非阻塞、干净首截不重截）、baseline_rejected 状态映射。出处 tests/test_visual_baseline_anti_pollution.py:69-258、tasks.md 3.2 | pass | 0/10 | - |
| gate-declared-scenario-relaxed-upper-rejects-near-band | R1×污染门调用侧：声明性场景 id（bigscreen-empty-state）对贴阈值画面（std≈0.087）按场景传放宽上限判 low_contrast → 防污染门命中（R3 证据落盘恰 2 份：首截+复测件 r1）→ 门内重截恰一次（R2，确定性画面复测不变）→ baseline_rejected，基线文件不落地，note 含「拒绝固化」。出处 core/verify_engine/visual_diff.py:254-263（按场景传参）、:266-356（证据+复测+拒绝） | pass | 0/8 | - |
| gate-undeclared-scenario-default-upper-unchanged | R1 回归点（普通场景门强度不变）：同一贴阈值画面、未声明场景 id（bigscreen-view）维持缺省 0.08 上限 → 无标签 → 照常固化 baseline_created，单次截图（不触发门内重截）、无污染证据落盘、无健全性标签（缺标签=正常态契约不变）。出处 core/verify_engine/visual_diff.py:254-263、tasks.md 1.1「普通场景缺省 0.08 行为不变」 | pass | 0/7 | - |
| gate-recheck-converged-fixes-baseline-from-retake | R2 门内收敛复核正向：首截深度低对比、复测正常画面 → 收敛放行 baseline_created；固化基线内容=复测件（回写断言：基线文件与 current_path 均为复测帧，非污染首图），轮次命名工作副本 r1 不留盘；截图恰 2 次（首截+一次复测）；R3 证据目录恰 2 份（首截无后缀+复测件 r1，均以场景名 polluted 前缀命名）。出处 core/verify_engine/visual_diff.py:271-325（复测与回写）、:413-458（固化自 current_path 复制） | pass | 0/10 | - |
| gate-recheck-still-polluted-rejects-with-single-retake | R2 负向（每场景每轮至多一次重截防死循环）：首截与复测均白屏 → 复测仍污染才 baseline_rejected，note 留复测痕迹且含「拒绝固化」；截图恰 2 次无第 3 次；未收敛不回写——current_path 保持首截内容；基线不落地；R3 证据 2 份（复测件 r1）、工作副本不留盘。出处 core/verify_engine/visual_diff.py:275-356（POLLUTION_RECHECK_MAX=1 与早返回） | pass | 0/10 | - |
| gate-recheck-crash-fails-closed-to-first-frame | R2 异常路径（fail-closed）：复测自身失败（截图抛 RuntimeError 模拟页面崩溃）不掩盖污染判定——按首截污染 baseline_rejected，blank_screenshot 标签保留，基线不固化，note 含「拒绝固化」，截图恰 2 次（首截+失败复测尝试）。出处 core/verify_engine/visual_diff.py:308-314（复测异常按首截污染拒绝） | pass | 0/6 | - |
| gate-clean-first-frame-skips-recheck-and-evidence | R2/R3 回归点（干净首截不触发门内重截与证据落盘）：正常画面首截 → 单次截图直接 baseline_created，污染证据目录零落盘——门内重截与证据复制仅在污染命中分支发生，正常路径零开销。出处 core/verify_engine/visual_diff.py:246-263、tests/test_visual_baseline_anti_pollution.py:249-258 | pass | 0/6 | - |
| evidence-dump-spec-scoped-naming-and-nonblocking | R3 证据自动落盘：污染命中轮截图复制到 .fenix/verify-evidence/<spec>/，命名含场景名+polluted+时间戳，复测件带 r1 后缀、首截无后缀；不同 spec（spec-alpha/spec-beta）证据目录互相隔离互不串扰（各恰 2 份）；证据落盘失败（shutil.copy 抛 OSError）只记 warning 不阻断门判定（仍 baseline_rejected）。出处 core/verify_engine/visual_diff.py:748-782（_evidence_dir/_copy_pollution_evidence）、spec R3 与 evo-verify-evidence-tiered-retention 落位共存 | pass | 0/9 | - |
| labeling-path-browser-screenshot-scenario-aware | R1×标注路径调用侧：BrowserManager.screenshot 对同一贴阈值画面（std≈0.087），声明性场景名（sc-empty-state）产 low_contrast 标签、普通场景名（sc-view）无标签（缺标签=正常态契约不变）；纯白画面在声明性名下仍产 blank_screenshot（真空白标签不受放宽影响）；两次截图落盘路径不同名（实例内单调序号防覆盖）。出处 core/verify_engine/browser.py:1812-1858（screenshot 标注路径按 name 传参） | pass | 0/5 | - |
| gate-blank-and-saturated-color-not-admitted-by-relaxation | 设计风险守卫（放宽不引入真空白漏检；blank 判定独立于 std 通道）：声明性场景 id 下纯白（std≈0）与饱和纯色（整屏 (0,128,0)，跨通道 std>0.2 但主色占比 100%）均经 blank_screenshot 通道判污染 → 门内复测仍污染 → baseline_rejected，两类基线均不落地——放宽上限不放过纯色渲染失败/伪造证据形态。出处 core/verify_engine/screenshot_lab.py:26（BLANK_DOMINANT_COLOR_PCT）、:184-188（blank 判定分支）、design.md 风险条款 | pass | 0/5 | - |
| gate-classify-failure-defers-baseline | 判定失败防护回归（classify 异常 fail-open 与防污染门衔接）：截图写入非图像垃圾字节 → classify_screenshot 捕获异常返回空 dict（缺 pixel_std/dominant_color_pct 量化键）→ baseline_deferred 顺延下轮，基线不固化、无污染证据落盘（判定失败防护非污染命中分支，不误触 R2/R3）。出处 core/verify_engine/visual_diff.py:358-387（判定失败防护）、core/verify_engine/screenshot_lab.py:109-120（异常返回空 dict） | pass | 0/5 | - |
| visual-compare-flow-intact-after-gate-changes | 视觉对比主流程回归（R1-R3 改动不破坏既有门序）：正常画面首截 baseline_created → 同帧复比 pass（SSIM/像素降级任一标尺）→ 换帧复比 diff_detected——基线固化、对比与判定全链路不回归，污染门改动对已固化基线的常规对比路径零影响。出处 core/verify_engine/visual_diff.py:413-523（固化与对比主流程） | pass | 0/8 | - |

## 本轮场景集变更

当前稳定场景集共 15 个（第 1 轮）。

- 首轮写入 15 个场景

