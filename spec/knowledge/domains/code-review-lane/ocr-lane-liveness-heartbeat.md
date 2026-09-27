# ocr 车道运行中心跳

<!-- knowledge: capability=ocr-lane-liveness-heartbeat rev=1
     sources=spec/archive/2026-09-27-fix-ocr-lane-orphaned-state-misfire -->

ocr 审查车道运行期间的心跳事件：以 run 转录 mtime 的持续刷新表达「车道活着」，使大 diff 长审查不被无驱动探针误报为孤儿，同时不遮蔽真孤儿。

## 规则

- 车道（`run_impl_ocr`）在审查子进程运行期间，框架侧以不超过 60 秒的间隔（实现取 45 秒，留出线程调度与写盘抖动余量）向该车道 run 转录（`.fenix/runs/impl-ocr-<spec>-<ts>.jsonl`）追加 `progress` 心跳事件。
- 心跳事件携带 `spec`、`agent_type: "impl-ocr"`、`timestamp` 与审查进度摘要（review 区间 from/to、已用时秒数）。
- 子进程返回或触发车道硬超时后停止心跳，不再有新 `progress` 事件；停跳先于终态写入，`result` / `error` 终态事件保持为文件最后一行（「终态事件末行后置」不变量不被破坏）。
- 心跳与无驱动探针相容：orphaned_state 判定 `spec_is_undriven`（admin_monitor 与 event_bus 恢复共用）零改动——车道在跑期间心跳持续刷新 run 文件 mtime，其 run 文件 mtime 宽限窗条件自然为假，spec 不被判「无驱动」，orphaned_state 信号不成条，Administrator 不被唤起。
- 不为 STATE 的 `_ocr_join_wait` 增加任何有意等待豁免：daemon 重启后心跳线程随进程消失，run 转录 mtime 停滞，宽限 + 阈值过后 spec 回归既有 orphaned_state 上报与「admin 处置 → testing→verifier 重验入队」自愈链（真孤儿不被遮蔽）。
- `progress` 不被终态分类器判为任何终态：dashboard `classify_run`（`core/dashboard/data/runs.py`）与 `AdminMonitor._run_terminal_status` 对未知/非终态事件类型的缺省 `running` 兜底即满足，以回归测试钉住；心跳末行时 run 判 `running`，时间轴 run 节点显示运行中。
- 运行记录与时间轴渲染层容忍 `progress` 事件：不识别则按既有降级路径忽略或按运行中呈现，不报错、不误判终态。

## 溯源

- 2026-09-27 fix-ocr-lane-orphaned-state-misfire — 新建车道运行中心跳：≤60s progress 事件与停跳先于终态、与 `spec_is_undriven` 的相容语义（大 diff 长审查不再误报孤儿、重启停跳后真孤儿仍上报）、终态分类器与渲染层对 progress 的透明容忍。
