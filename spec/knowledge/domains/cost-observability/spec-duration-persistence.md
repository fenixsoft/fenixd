# SPEC 完成耗时持久化
<!-- knowledge: capability=spec-duration-persistence rev=1
     sources=spec/archive/2026-09-09-add-done-duration-persist -->

SPEC 落定 done 的时刻把总耗时固化进 STATE.md，使已完成 SPEC 的耗时不再依赖易失的 run 产物。

## 规则

- **done 固化总耗时**：SPEC 状态从 verified 转换为 done 时，立即计算该 SPEC 总耗时并作为 `total_duration` 字段写入 STATE.md 条目。总耗时 = 该 SPEC 全部 run 产物（implementer/verifier/planner/tester/admin 等，含 `runs/archive/` 归档产物）的 `duration_seconds` 之和（秒，整数）；无任何 run 产物时写入 0。
- **跨 STATE.md 重写持久**：`StateParser.serialize` 的固定字段白名单包含 `total_duration`，字段在 daemon 多次条目更新、状态转换与重启往返后不丢失。
- **done 转 pushed 不重算**：已写入 `total_duration` 的 SPEC 后续转换为 pushed 时，字段保持 done 时刻的值。
- **Dashboard 优先读持久值**：`spec_summary` 对状态为 done 或 pushed 的 SPEC，STATE.md 条目含非空 `total_duration` 时直接返回该值（int，秒，即使 run 产物已被清理）；字段缺失时回退现有 run 产物求和逻辑（存量 SPEC 兼容，数据已丢失时显示 0 属实，接口不报错）。非完成状态（implementing/testing 等）不受影响，`total_duration` 仍由 run 产物实时求和。

## 溯源

- [2026-09-09 2026-09-09-add-done-duration-persist](spec/archive/2026-09-09-add-done-duration-persist/) — 新增 verified→done 时刻固化 `total_duration` 到 STATE.md、序列化白名单持久化与 dashboard 对已完成 SPEC 的持久值优先读取。
