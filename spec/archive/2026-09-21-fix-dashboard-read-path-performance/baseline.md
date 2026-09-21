# 基线测量（fix-dashboard-read-path-performance 任务 1.1 / 6.1）

测量脚本：`.history/measure_baseline.py`（gitignored，不入库）。
合成项目规模对齐 proposal 实测（220 specs / 644 run 文件，每 run 产物 ~115 行）。
测量在**修复前**代码（本 SPEC 首个 commit 之前的工作树）上完成。

## 1.1 修复前基线（2026-09-17）

| 指标 | 修复前 | 说明 |
| --- | --- | --- |
| `SummaryIndex` 冷重建耗时 | **7.86 s** | 全新索引首次 `get()`；123,136 次 json.loads |
| `/api/overview` 单请求（冷） | **0.68 s** | 每次请求冷算 project_summary；93,304 次 json.loads |
| `/api/overview` 单请求（warm，第 2 次） | **0.58 s** | 无 memo，json.loads 次数与冷请求相同（93,304）——每次请求都重读全部 run 产物 |

### cProfile 主要热点（修复前）

- `SummaryIndex.get`（`summary.py:422`）→ `spec_summary` ×220（cumtime 7.83s）：冷重建时每个
  spec 都 `get_runs` 重新 glob runs/archive 目录并按名过滤 → O(specs × runs)。
- `_impl_budget_max`（`summary.py:204`）→ `ConfigLoader.resolve_config` ×220（cumtime 5.62s）：
  **每 spec 重解析 2 个 YAML 配置文件**（无缓存），是冷重建最大单项成本。
- `overview` → `project_summary`（`summary.py:83`）→ `get_runs`（`runs.py:103`）→
  `_read_run_lines` ×644（cumtime 0.29s）：为取末 3 行把整个 run 文件逐行读完并
  `json.loads` 每一行（93,304 次）。

## 5.1a 归档清理删前条目数

- proposal 实测（真实仓库）：runs 活跃 301 文件 + 归档 343 文件（共 703MB）。
- `runs.keep` 缺省 50：首次执行保留清理时，归档目录（343 条目）会一次删除约 **293** 个文件
  ——5.1a 要求的「可观测删除」据此落地（每周期删除量设批次上限、逐条记日志）。

## 6.1 修复后复测（任务 6.1）

同一合成项目、同一测量脚本（`.history/measure_baseline.py`），修复后：

| 指标 | 修复前 | 修复后 | 变化 |
| --- | --- | --- | --- |
| `SummaryIndex` 冷重建耗时 | 7.86 s | **0.96 s** | **8.2× 提速** |
| `/api/overview` 单请求（冷） | 0.68 s / 93,304 loads | **0.38 s / 19,888 loads** | 1.8× / loads −79% |
| `/api/overview` 单请求（warm） | 0.58 s / 93,304 loads | **0.27 s / 19,888 loads** | 2.2× / loads −79% |

说明：
- 冷重建 7.86s → 0.96s：增量失效（只重算变化 spec）+ 每 spec 不再 glob runs 目录
  + `_impl_budget_max` 按 config 签名缓存（原冷重建 5.6s 是 220 次 YAML 重解析）。
- overview 剩余 19,888 次 json.loads 为 `task_progress → parse_run_task_done` 的
  任务跟踪解析（读取最新 impl run 产物），不属于 4.2「run 元数据 memo」范围；
  `get_runs` 本身的每次请求读已在 memo 后降为 O(变更量)（稳态 0 读）。
- 复测规模（220 specs / 644 run 文件，每 run 115 行）与 1.1 基线完全一致，
  相对比较有效。

## 5.1a 归档清理删前条目数

- proposal 实测（真实仓库）：runs 活跃 301 文件 + 归档 343 文件（共 703MB）。
- `runs.keep` 缺省 50：首次执行保留清理时，归档目录（343 条目）会一次删除约 **293** 个文件
  ——5.1a 要求的「可观测删除」据此落地（每周期删除量设批次上限 100、逐条记日志，
  文件名可追溯）。
