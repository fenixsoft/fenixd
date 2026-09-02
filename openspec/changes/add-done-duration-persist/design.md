# design — add-done-duration-persist

## Context

列表页耗时 = `core/dashboard/data.py` `spec_summary` 对 run 产物 `duration_seconds` 的实时求和（`get_runs(..., include_archive=True)`）。run 产物受 `RUNS_KEEP`（默认 50）清理，2026-09-02 事故中残留旧代码 dashboard 实例把 runs/ 删到只剩 20 个，pushed spec 的耗时永久归零。STATE.md 是 spec 元数据的持久载体（`implementer_run`/`tester_run` 等已在此持久化），但 `StateParser.serialize` 只序列化固定字段白名单，新增字段必须进白名单才能跨重写存活。

关键代码事实（实现前必读）：

- done 的唯一合法入口：`core/pm_engine/engine.py:280` `self.state_machine.transition(spec_name, "done")`（VALID_TRANSITIONS 中仅 verified→done）。
- `pm_engine.engine` 已依赖 `core.dashboard.data`（engine.py:21 `from core.dashboard.data import find_impl_run_file, ...`），复用 `get_runs` 不引入新的依赖方向。
- `StateParser.serialize`（core/state_machine.py:156-195）：固定字段列表 `["status", "priority", "created", "updated", "implementer_run", "tester_run", "branch", "error", "depends_on"]` + `_` 前缀内部字段。**不在白名单的字段在下次 STATE.md 重写时被静默丢弃。**
- dashboard 侧 `parse_state`（core/dashboard/data.py:484）按 `- key: value` 正则解析任意字段，值保持字符串；`null/none/空` 转为 None。

## Goals / Non-Goals

**Goals**
- done 落定时刻把总耗时快照进 STATE.md，使耗时不再依赖易失的 run 产物。
- dashboard 对 done/pushed 优先返回持久值，缺字段回退现有逻辑，存量 spec 零迁移。

**Non-Goals**
- 不回填存量 spec（run 产物已丢，无从恢复）。
- 不改 v3 前端（`fmtDuration` 消费 `total_duration`，来源变化对前端透明）。
- 不改 RUNS_KEEP/归档策略（add-run-archive 已落地归档语义）。
- 不在 pushed 时重算（done 之后可能有 merge/admin 类 run，用户语义是冻结 done 时刻值）。

## Decisions

### D1 写入点：engine.py done 转换处，紧随 transition 之后

在 `engine.py:280` `transition(spec_name, "done")` 成功后，调用 `self.state_machine.update_spec(spec_name, {"total_duration": <int>})`。不放进 `StateMachine.transition()` 内部——状态机保持对 run 文件无耦合，求和逻辑依赖 `get_runs`（dashboard data 层）。

### D2 求和实现：复用 get_runs，含归档

`sum(int(r.get("duration_seconds") or 0) for r in get_runs(project_root, spec_name, include_archive=True))`。project_root 从 engine 可得（与 engine.py 现有 data 层调用一致）。与 `spec_summary` 的求和口径完全一致，保证 done 时刻写入值 = 当时列表页显示值。

### D3 serialize 白名单加入 total_duration

`StateParser.serialize` 固定字段列表追加 `"total_duration"`（置于 `"depends_on"` 之后）。存量条目序列化为 `- total_duration: null`，与 `branch`/`error` 等可空字段表现一致；`parse_state` 读回 None，读取侧据此判"缺字段"。

### D4 读取侧：status ∈ {done, pushed} 且值可解析时采用

`spec_summary` 中：

```python
total_duration = None
if entry.get("status") in ("done", "pushed"):
    raw = entry.get("total_duration")
    if raw is not None:
        try:
            total_duration = int(raw)
        except (TypeError, ValueError):
            total_duration = None
if total_duration is None:
    total_duration = sum(...)  # 现有 run 求和回退
```

注意 parse_state 返回的是字符串（非 priority 那类 int 字段），必须 int() 容错；解析失败（脏值）回退实时求和，不让单字段脏数据打挂接口。

### D5 非完成状态忽略字段

`implementing`/`testing` 等状态的 spec 即使条目残留 `total_duration`（如人工改坏后回退），仍走实时求和——运行中的 spec 耗时应持续增长，冻结值仅对终态有意义。

## Risks / Trade-offs

- **done 时刻与清理竞态**：求和时 run 产物可能正被并发清理，快照值偏小。接受：尽力快照语义，远优于归零；且 run-archive 落地后归档产物不丢，竞态窗口极小。
- **STATE.md 体积**：每条目多一行（~30 字节），量级可忽略。
- **字段语义漂移**：`total_duration` 在 STATE.md 中冻结后，若未来 run 产物修复/回填，显示值不再自动更新。接受：用户明确要求 done 冻结语义。

## Migration Plan

无迁移。存量 done/pushed 条目无 `total_duration`（或为 null），读取侧回退实时求和；老 spec 数据已丢，显示 0 属实。

## Open Questions

无。
