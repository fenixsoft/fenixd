# 设计：visual-low-contrast-gate

## 落点

1. core/verify_engine/screenshot_lab.py：新增 LOW_CONTRAST_STD_UPPER_RELAXED 常量与场景名匹配助手；classify_screenshot 的 low_contrast_upper 参数化已存在（:39），调用侧按场景传值。
2. core/verify_engine/visual_diff.py：:241-262 污染门早返回前插入门内收敛复核（_settle（:162-169）＋一次重截＋classify 复测，复用 :376-419 重拍循环的截图函数）；命中分支加证据落盘（.fenix/verify-evidence/<spec>/，spec_name :73 在手）。
3. 测试：tests/test_screenshot_lab.py（场景感知放宽与普通场景缺省不变）；tests/test_visual_baseline_anti_pollution.py（门内重截收敛后放行、仍污染才拒绝、重截至多一次、证据落盘断言）。

## 风险与权衡

- 放宽阈值只对声明性场景名生效，普通场景门强度不变，不引入真空白漏检（真空白 std≈0，远低于两档阈值）。
- 门内重截增加最坏一次 settle 时延（visual_retake_max/visual_settle_timeout_ms 既有语义，:92-108），只在污染命中路径发生。
- 证据落盘与分级保留策略共存：写入即受 evo-verify-evidence-tiered-retention 生命周期管理，不新造清理面。