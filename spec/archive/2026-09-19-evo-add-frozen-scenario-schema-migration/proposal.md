## Why

冻结场景文件 test_scenarios.json 以旧 schema 生成后（run 步骤 `value`→`command`、output_match 断言 `value`→`expected` 字段重命名），读侧 load_scenarios 直接抛异常判 corrupt，验收失败且冻结场景不自动重出题，须 admin 裁决。fenixd 实证（admin_alerts 15:00:04Z / 15:13:12Z / 15:33:09Z，fix-root-init-import-shadow）：单次 2 个 admin run $7.28 + blocked_stuck 再卡 17min，且暴露『admin 处置成功后 spec 状态未复位』第二缺陷（blocked_stuck 非 env 阻塞族不触发自动复位）。任何真实项目在场景字段演进后重验旧冻结文件都会命中同一卡壳。

## What Changes

- 读侧旧 schema 兼容迁移：load_scenarios 识别旧字段（run 步骤 `value`→`command`、output_match 断言 `value`→`expected`），迁移后校验；无法迁移（字段既无新名也无旧名）时报具体字段差异清单而不是笼统 `corrupt`。
- 写入时打 schema 版本标记：scenario 写入端恒定写入 `schema_version`，读侧优先按版本路由迁移。
- admin 处置后统一复位：`blocked_stuck` 加入处置成功后自动复位集合（与 ENV_BLOCK_SIGNAL_TYPES 同语义，MUST NOT 恢复错误业务判定），消除 blocked_stuck 二次空转。
- 无 dashboard UI、无新配置键。

## Capabilities

### New Capabilities
- `frozen-scenario-schema-migration`: 冻结场景读侧旧 schema 兼容迁移 + 版本标记 + 字段差异级报错
- `blocked-stuck-disposition-reset`: admin 处置成功后 blocked_stuck 自动复位

### Modified Capabilities
`verify_scenarios` 读端行为兼容增强（不改变新 schema 路径语义）。

## Impact

- **core/verify_engine/scenarios.py**：load_scenarios / validate_scenario_dicts 增加迁移与版本路由。
- **core/admin_monitor.py**：处置后自动复位集合扩展 blocked_stuck（复用 _reset_env_blocked_after_disposition 范式）。
- **tests/**：旧 schema 迁移单测 + blocked_stuck 复位断言。