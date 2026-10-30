## Deliverables

```yaml
- path: core/verify_engine/screenshot_lab.py
  kind: modify
- path: core/verify_engine/visual_diff.py
  kind: modify
- path: core/verify_engine/browser.py
  kind: modify
- path: tests/test_screenshot_lab.py
  kind: modify
- path: tests/test_visual_baseline_anti_pollution.py
  kind: modify
```

## 1. 场景感知阈值

- [x] 1.1 core/verify_engine/screenshot_lab.py：新增放宽上限常量（缺省 0.095）与场景名匹配助手（empty/zero-state/placeholder/low-contrast/low_contrast 子串，大小写不敏感；「声明低对比」以 id 含 low-contrast 保留标记实现，不新增场景 schema 字段）；两处调用侧按场景传 low_contrast_upper——visual_diff 污染门（:243）与 browser.screenshot 标注路径（core/verify_engine/browser.py:1847，name 即场景名），普通场景缺省 0.08 行为不变

## 2. 门内收敛复核与证据落盘

- [x] 2.1 core/verify_engine/visual_diff.py：基线防污染门（:241-262）早返回前复用 _settle（:162-169）做一次延时重截（轮次命名文件）并复测 classify，收敛则先把复测件回写 current_path 再按正常流程固化/放行（固化自 current_path 复制，:334；不回写即固化污染首图），仍污染才 baseline_rejected，每场景每轮至多一次重截
- [x] 2.2 core/verify_engine/visual_diff.py：污染门命中分支把当轮截图复制到 .fenix/verify-evidence/<spec>/（命名含场景名与轮次；有复测时首截与复测件均落盘，复测件带 r{n} 后缀），与分级保留策略共存

## 3. 测试

- [x] 3.1 tests/test_screenshot_lab.py：声明性场景名（含 low-contrast 保留标记）阈值放宽生效、普通场景与无标签场景缺省阈值不变、两调用侧（污染门/标注路径）按场景传参的用例
- [x] 3.2 tests/test_visual_baseline_anti_pollution.py：门内重截收敛后放行且固化基线内容=复测件（回写断言）、复测仍污染才拒绝、重截至多一次、证据落盘路径与命名（含复测件 r{n}）断言