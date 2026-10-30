## Deliverables

```yaml
- path: core/verify_engine/screenshot_lab.py
  kind: modify
- path: core/verify_engine/visual_diff.py
  kind: modify
- path: tests/test_screenshot_lab.py
  kind: modify
- path: tests/test_visual_baseline_anti_pollution.py
  kind: modify
```

## 1. 场景感知阈值

- [ ] 1.1 core/verify_engine/screenshot_lab.py：新增放宽上限常量与场景名匹配（empty/zero-state/placeholder 子串或场景声明低对比模板），classify_screenshot 按场景传 low_contrast_upper（:39 参数化已存在），普通场景缺省 0.08 行为不变

## 2. 门内收敛复核与证据落盘

- [ ] 2.1 core/verify_engine/visual_diff.py：基线防污染门（:241-262）早返回前复用 _settle（:162-169）做一次延时重截并复测 classify，收敛则按正常流程固化/放行，仍污染才 baseline_rejected，每场景每轮至多一次重截
- [ ] 2.2 core/verify_engine/visual_diff.py：污染门命中分支把当轮截图复制到 .fenix/verify-evidence/<spec>/（命名含场景名与轮次），与分级保留策略共存

## 3. 测试

- [ ] 3.1 tests/test_screenshot_lab.py：声明性场景名阈值放宽生效、普通场景与无标签场景缺省阈值不变的用例
- [ ] 3.2 tests/test_visual_baseline_anti_pollution.py：门内重截收敛后放行、复测仍污染才拒绝、重截至多一次、证据落盘路径与命名断言