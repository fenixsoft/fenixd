# add-done-duration-persist

## Why

SPEC 的列表页耗时（`total_duration`）当前由 run 产物（`.fenix/runs/*.jsonl`）的 `duration_seconds` 实时求和得出，run 产物受 `RUNS_KEEP` 保留上限清理。2026-09-02 事故中，一个残留的旧代码 dashboard 实例把 runs/ 删到只剩最新 20 个，所有 pushed spec 的 run 产物丢失、耗时永久归零且不可恢复。耗时数据需要在它完整存在的最后时刻（done 落定）固化到持久的 STATE.md 中，使其不再依赖易失的 run 产物。

## What Changes

- SPEC 状态转换为 `done` 时（`core/pm_engine/engine.py` 唯一 done 入口），立即把该 spec 的总耗时（全部 run 产物 `duration_seconds` 求和，含归档）作为新字段 `total_duration` 写入 STATE.md 条目。
- `StateParser.serialize` 的固定字段白名单加入 `total_duration`，保证字段在 STATE.md 往返重写中不丢失。
- Dashboard `spec_summary`（`core/dashboard/data.py`）对 `done`/`pushed` 状态的 spec：STATE.md 中有 `total_duration` 字段时直接返回该值（int）；无字段时回退现有 run 求和逻辑（存量 spec 兼容，数据已丢的显示 0 属实）。
- `done → pushed` 后字段保持 done 时刻的值，不重算。

## Capabilities

### New Capabilities
- `spec-duration-persistence`: SPEC 完成时把总耗时固化到 STATE.md，dashboard 对已完成 spec 优先读取该持久值

### Modified Capabilities

## Impact

- `core/pm_engine/engine.py`：verified→done 转换处计算并写入耗时（复用 `core.dashboard.data.get_runs`，pm_engine 已有该模块依赖先例）。
- `core/state_machine.py`：`StateParser.serialize` 字段白名单加 `total_duration`。
- `core/dashboard/data.py`：`spec_summary` 读取优先级调整（STATE.md 字段优先，run 求和回退）。
- `core/dashboard/data.py` `parse_state`：新字段被现有 `- key: value` 正则自动解析为字符串，读取侧需 int 转换（value 为 "null" 时 parse_state 已转为 None）。
- 无 UI 组件改动（v3 前端 `fmtDuration` 直接消费 `total_duration`，数值来源变化对前端透明）；无数据迁移（缺字段回退逻辑兜底）。
