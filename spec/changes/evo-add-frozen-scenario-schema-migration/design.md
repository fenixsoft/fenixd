# 设计：冻结场景 schema 迁移与 blocked_stuck 处置复位

## Context

冻结场景机制（跨轮一致、不自动重出题）按设计触发时，把 schema 字段演进缺口交给人工：load_scenarios（core/verify_engine/scenarios.py:630）对旧 schema 直接 raise ValueError → _load_frozen_scenarios（core/pm_engine/verification.py:3187）返回 corrupt → 场景计划争议升级；admin 修复后因 blocked_stuck 不在 ENV_BLOCK_SIGNAL_TYPES（core/admin_monitor.py:1068）而不触发自动复位，二次空转。fix-root-init-import-shadow 事件链（admin_alerts 15:00:04Z→15:13:12Z→15:33:09Z）实证两层缺口。

## Goals / Non-Goals

- **Goals**：旧 schema 冻结文件读侧自动迁移验收；真损坏报字段差异而非笼统 corrupt；admin 处置成功后 blocked_stuck 自动复位。
- **Non-Goals**：不做冻结文件的重出题策略变更（不自动重出题是本机制特性）；不 gated reload；不改写场景文件（迁移仅作用于读入的内存对象，保持读无副作用，与 fix-frozen-scenario-orphan-reservoir D4 净化语义一致）。

## Decisions

### D1：迁移只针对已知的两处字段重命名

**选择**：仅处理 `value→command`（run 步骤）与 `value→expected`（output_match 断言）两对已验证的迁移；不引入通用 schema 转换框架。

**理由**：实证中迁移面唯一且封闭（27 处全为这两对）；通用框架成本高、风险大，与『低成本修复』定位不符。

### D2：版本标记数据驱动，迁移函数按版本路由

**选择**：写入端恒定写入 `schema_version`；读侧若无版本字段视为旧 schema 走迁移，否则按版本路由（当前版本直通）。

**理由**：下轮字段演进时只需追加一个迁移分支，报错信息可带版本上下文。

### D3：blocked_stuck 复用 env 复位范式

**选择**：将 blocked_stuck 加入处置后自动复位集合，走 resolve_env_blocked_reset_path 既有路径（合并→testing，未合并→ready）。

**理由**：处置根因修复后状态悬置是纯闭环缺口，无独立语义；复用既有路径保持复位语义一致，MUST NOT 恢复任何错误业务判定（只复位阻塞态）。