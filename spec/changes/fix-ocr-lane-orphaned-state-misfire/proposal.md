## Why

ocr 并行审查车道（add-impl-ocr-parallel-lane）在框架侧 daemon 线程跑 `bin/ocr_review.py`，大 diff 审查常超 20 分钟；而 orphaned_state 无驱动探针（`spec_is_undriven`，admin_monitor 与 event_bus 恢复共用口径）对车道**全盲**——车道 run 转录只在启动/终态写事件（运行中 mtime 停滞，超 120s 宽限即判「无活动 run」），ocr 子进程 argv（`python3 bin/ocr_review.py review --from… --to…`）不含 spec 名，pgrep 模式 `impl-<spec>-` 匹配不到。四条件全真 → 车道在跑超过 `orphaned_state_threshold_minutes`（15 分钟）**必误报**成条，唤起 Administrator 烧一轮处置预算。

实证（2026-09-22 add-code-fix-manual-trigger）：11:58:00 全绿快道 17/17 后进入 ocr join 停等、车道启动审查 63 文件 +6694 行；12:13 即被误报，admin run 只读诊断确认为探针误报（partially-resolved）。每个大 diff spec 的长审查都会系统性复发。

## What Changes

- **车道运行中心跳**：`run_impl_ocr` 在审查子进程运行期间，由框架侧定时器线程按 ≤60s 间隔（小于 `ORPHANED_RUN_GRACE_SECONDS`=120s run 宽限）向车道 run 转录（`impl-ocr-<spec>-<ts>.jsonl`）追加 `progress` 心跳事件（含审查区间、已用时）；子进程返回/超时后停跳，终态事件仍末行后置（「终态后置」不变量不破坏）。
- **探针自然愈合，判定函数零改动**：`spec_is_undriven` 条件①（run 文件 mtime 宽限窗）因心跳持续为假 → 车道在跑不再被判「无驱动」；`spec_is_undriven` 本体、`_pgrep_live_worktree`、admin_monitor 与 event_bus 共用口径**一行不改**。
- **重启自愈链不遮蔽（显式约束）**：daemon 重启后心跳自然停止 → 宽限+阈值过后真孤儿仍被正常上报，既有「orphaned_state → admin 处置 → testing→verifier 重验入队」自愈链完整保留。**禁止**把 STATE 的 `_ocr_join_wait` 做成无期限有意等待豁免——该字段无 boot 恢复，重启场景恰恰依赖 orphaned_state 兜底。
- **终态分类零改动（回归钉住）**：`progress` 不在 `_RUN_TERMINAL_STATUS_MAP`，dashboard `classify_run` 与 `AdminMonitor._run_terminal_status` 的未知类型缺省 `running` 兜底即兼容；以回归测试钉住，防未来加终态类型时把心跳误判终态。

## Capabilities

### New Capabilities

- `ocr-lane-liveness-heartbeat`: ocr 车道运行中心跳观测契约——心跳事件的类型/间隔/内容、启停时机（子进程运行期唯一）、与终态后置不变量的相容、对无驱动探针与终态分类器的相容语义（心跳活=有驱动；心跳停=回归既有上报，不产生任何豁免）。

### Modified Capabilities

（无——探针判定行为零改动，车道既有 spec 未钉死转录事件集，心跳为纯新增观测面。）

## Impact

- `core/agent_runner/maintenance_runs.py`：`run_impl_ocr` 增加心跳定时线程与停跳收尾（含线程安全：与终态事件写同一 jsonl 的顺序约束）。
- `core/dashboard/data/runs.py` / `core/admin_monitor.py`：不改行为，仅以回归测试钉住 `progress` 事件的 running 兼容。
- 测试：`tests/` 下探针回归（心跳活 → `spec_is_undriven=False`；心跳停 + 超阈值 → 仍 True）与终态分类回归。
- 不涉前端、不涉配置键、无迁移；车道产物（code-review.json）与 join 门禁语义不变。
