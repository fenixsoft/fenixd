## Deliverables

```yaml
- path: core/verify_engine/scenarios.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_frozen_scenario_schema_migration.py
  kind: new
```

## 1. 读侧 schema 迁移

- [x] 1.1 core/verify_engine/scenarios.py 的 load_scenarios / validate_scenario_dicts 前置迁移步骤：识别旧 `value` 字段并映射到 `command`（run 步骤）与 `expected`（output_match 断言），仅当目标字段缺失时迁移
- [x] 1.2 迁移后仍失败的条目报字段级差异（场景 id/下标/缺失字段清单），不吞为笼统 corrupt
- [x] 1.3 新 schema 路径行为零变化（回归断言）

## 2. 版本标记

- [x] 2.1 写入端（save_scenarios / 场景补齐写回等路径）恒定写入 `schema_version` 结构化标记
- [x] 2.2 读侧按版本路由：无版本=旧 schema 走迁移；当前版本直通；未知版本走迁移尝试+字段差异报错

## 3. blocked_stuck 处置后自动复位

- [x] 3.1 core/admin_monitor.py 处置后自动复位集合扩展 blocked_stuck：result=resolved 且根因已修复时自动复位（复用 resolve_env_blocked_reset_path：合并→testing，未合并→ready）
- [x] 3.2 处置未完成（无 result=resolved）时保持既有阻塞行为（幂等）

## 4. 测试

- [x] 4.1 tests/test_frozen_scenario_schema_migration.py：旧 schema 自动迁移通过；新 schema 零变化；真损坏报字段清单
- [x] 4.2 blocked_stuck 处置后自动复位断言（合并/未合并两分支 + 未完成不动状态）
