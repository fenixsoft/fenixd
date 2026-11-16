## Deliverables

```yaml
- path: core/verify_report.py
  kind: modify
- path: core/adjudication_narrative.py
  kind: modify
- path: agents/arbiter.md
  kind: modify
- path: tests/test_baseline_comparability_guard.py
  kind: new
```

## 1. 稳定性快照指纹

- [ ] 1.1 core/verify_report.py：verdict_stability stamp 增记 progress 摘要指纹（组合条数 + 可用几何/管道元数据摘要，缺失记 None），相邻轮指纹不一致时 stamp 与稳定性报告标注 baseline_comparable=false 及漂移明细，旧数据缺字段按未知处理

## 2. 证据包与仲裁守卫

- [ ] 2.1 core/adjudication_narrative.py：证据包引用跨轮数值比较时附「基线元数据 + 可比性结论」段，不可比或元数据缺失时输出「不可比」标注，不作为回归/豁免定性依据
- [ ] 2.2 agents/arbiter.md：判定规范新增「跨轮数值基线比较先核对采集/编码几何与管道版本可比性，不可比或缺失时标注不可比并降级结论确定性」条款

## 3. 测试

- [ ] 3.1 tests/test_baseline_comparability_guard.py：覆盖「相邻轮几何指纹不一致→标注不可比」「旧格式 stamp 兼容读取」「证据包对不可比基线输出不可比标注」「几何一致时不降级」四场景