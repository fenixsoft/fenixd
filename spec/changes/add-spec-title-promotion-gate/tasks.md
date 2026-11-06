## Deliverables

```yaml
- path: core/pm_engine/promotion.py
  kind: modify
- path: tests/test_title_promotion_gate.py
  kind: new
```

## 1. 晋升硬门

- [x] 1.1 `core/pm_engine/promotion.py` 既有 lint 链追加 title 存在性检查（`_lint` 族同形态）：活跃 `.spec.yaml` yaml.safe_load 后 `title` 为非空 str 即通过；缺失/文件缺失/解析失败/空白值 → 违规；`fix-cr-` 前缀豁免先判；不做长度/形态校验。
- [x] 1.2 违规消息处方化：含最小写入示例（`title: <5-25字中文标题>` 追加 `.spec.yaml` 末行）与规范出处（add-spec-chinese-title 生成纪律）。
- [x] 1.3 新增 `tests/test_title_promotion_gate.py`：钉死四场景（缺 title 违规+处方文案、空白 title 同判、fix-cr-* 豁免、有 title 零变化）与「补写后重晋升通过」自愈路径。
