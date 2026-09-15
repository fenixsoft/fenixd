# Proposal: fix-dashboard-read-path-performance

## Why

Dashboard 读路径随数据量呈**二次方衰减**，是数据量放大时最先塌方的组件（实测于本仓 220 specs / 644 run 文件）：

- `SummaryIndex` 每次 STATE.md 变化即**丢弃全部 spec 缓存**（`data.py` 的 `SummaryIndex.get`：`state_changed → idx = {}`），每个 spec 重算时 `get_runs` 重新 glob 整个 runs+archive 目录再按名过滤 → O(specs × runs)。冷重建实测 **4.2 秒 CPU**；活跃开发期 STATE.md 每分钟多次写入，watcher（每 1s）与 HTTP 线程争同一把锁，抢到的做全量重建、另一个阻塞。
- `/api/overview` 与 `/api/projects` 每次请求冷算 `project_summary`，其中 `_read_run_lines` **为取末 3 行把整个 run 文件逐行读完并 json.loads 每一行**（实测单次 74,023 次 json.loads，1.5s/请求）。
- `runs.keep` 配置项是**死键**，无任何消费点执行按数量清理 → runs 目录无界增长（实测活跃 301 文件 + 归档 343 文件共 703MB），是上述所有成本的基数分母。

## What Changes

- **修复 `SummaryIndex` 缓存策略**：STATE 签名变化时**保留旧缓存**，只对新增/删除/签名变化的 spec 增量重算；全量重建仅留给索引损坏场景。
- **消除 per-spec 全目录 glob**：`spec_summary` 复用已预扫描的 `_runs_by_spec_sigs` 映射，`get_runs` 增加接受预选文件集的入口。
- **run 尾读改增量**：`_read_run_lines` 改「先 seek 尾窗字节读，行长超窗时回退全读」，并保留现有的「末行超长不得从中间截断」正确性论证；run 元数据按 `(path, mtime_ns, size)` memo。
- **落地 runs 保留策略**：让 `runs.keep` 有真实消费点（daemon 周期任务把终态 run 移入 archive 并按数量/年龄清理），并修正 watcher 中与现实的偏差注释。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `dashboard-spec-summary-index`: 摘要索引的缓存失效语义从「STATE 变化即全丢」改为「按 spec 增量失效」。
- （可能的既有能力）`run-artifact-retention`: 使 `runs.keep` 由死键变为真实生效的保留策略。

## Impact

- **代码**：`core/dashboard/data.py`（`SummaryIndex`、`spec_summary`、`get_runs`、`_read_run_lines`、`_runs_by_spec_sigs`）、daemon 周期任务挂载点（`fenixd.py`）、`core/dashboard/watcher.py`（注释修正）。
- **API**：HTTP 端点行为不变；响应内容不变，仅延迟下降。预期 `/api/overview` 从 ~1.5s 降至 <100ms，`/api/specs` 冷路径消除秒级卡顿。
- **测试**：`tests/test_dashboard_index.py`、`tests/test_dashboard_data.py`、`tests/test_dashboard_watcher*.py` 为回归护栏；新增针对「STATE 变化不丢缓存」与「尾读等价性」的用例。
- **注意**：与 `refactor-dashboard-data-module` 有文件重叠，故本 spec 依赖链排在重构**之后**（避免同文件并发冲突）。
