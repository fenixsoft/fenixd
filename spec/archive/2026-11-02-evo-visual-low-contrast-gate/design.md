# 设计：visual-low-contrast-gate

## 落点

1. core/verify_engine/screenshot_lab.py：新增 LOW_CONTRAST_STD_UPPER_RELAXED 常量与场景名匹配助手（empty/zero-state/placeholder/low-contrast/low_contrast 子串，大小写不敏感）；classify_screenshot 的 low_contrast_upper 参数化已存在（:41），调用侧按场景传值。
2. core/verify_engine/visual_diff.py：:241-262 污染门早返回前插入门内收敛复核（_settle（:162-169）＋一次重截＋classify 复测，复用 :376-419 重拍循环的截图函数与轮次命名纪律）；复测入选 MUST 先回写 current_path 再固化（固化从 current_path 复制，:334，不回写即固化污染首图）；命中分支加证据落盘（.fenix/verify-evidence/<spec>/，spec_name :73 在手；有复测时两份均落）。
3. core/verify_engine/browser.py：screenshot（:1812-1848）标注路径按 name 参数（场景 id）经同一助手计算放宽上限传入 classify_screenshot（:1847），与污染门同源判定——否则 low_contrast 标签继续以 0.08 产出，并经 verdict_check 归因链（:1174-1180/:1780）维持「判 env」误判（R1 的另一半）。
4. 测试：tests/test_screenshot_lab.py（场景感知放宽与普通场景缺省不变、两调用侧传参）；tests/test_visual_baseline_anti_pollution.py（门内重截收敛后放行且固化基线内容=复测件、仍污染才拒绝、重截至多一次、证据落盘断言）。

## 风险与权衡

- 放宽阈值只对声明性场景名生效，普通场景门强度不变，不引入真空白漏检（真空白 std≈0，远低于两档阈值；blank 判定独立于 std，走 dominant_color_pct 通道，screenshot_lab.py:140-144）。
- 标注侧（browser.screenshot）放宽会缩小 low_contrast 强标签的归因佐证覆盖（verdict_check 快速通道 :1179），属预期语义收缩——真空白标签不受影响，缺标签=正常态契约不变。
- 门内复测对确定性渲染（页面内容恒定、重截结果不变）无收敛效果，此类场景依赖 R1 阈值放宽放行（历史实证：zero-state 页恒 0.0773，admin-add-spec-topology-bigscreen run 日志），R1 与 R2 互为补充、缺一不可。
- 门内重截增加最坏一次 settle 时延（visual_retake_max/visual_settle_timeout_ms 既有语义，:92-108），只在污染命中路径发生。
- 证据落盘与分级保留策略共存：写入即受 evo-verify-evidence-tiered-retention 生命周期管理，不新造清理面。