## Deliverables

```yaml
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: tests/test_frozen_scenario_schema_migration.py
  kind: modify
```

## 1. 冻结读端拯救接线

- [x] 1.1 `core/pm_engine/verification/pipeline.py` 冻结装载段：顶层非数组时先调 `_salvage_top_level_dict`（传场景文件路径），拯救成功（返回列表）则以解包结果替换 raw 继续既有 `frozen_contract_version` 迁移与装载；拯救失败（None）落回既有 `_escalate_env_blocked` 场景计划争议分支（错误文案与处置选项不变）
- [x] 1.2 单测扩展（`tests/test_frozen_scenario_schema_migration.py`）四场景：①合法 dict 包裹 → 拯救成功装载推进且文件被重写为纯数组、不触发 env_blocked；②dict 包裹但条目非法 → 走 env_blocked；③顶层 dict 无 scenarios 键 → 走 env_blocked；④顶层纯数组 → 行为与接线前一致（不触发拯救、无额外重写）
- [ ] 1.3 回归：该测试文件既有用例（契约迁移、corrupt→env_blocked 既有路径）全绿，确认未破坏既有语义
