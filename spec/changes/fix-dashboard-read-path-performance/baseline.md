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

## 6.1 修复后复测（任务 6.1 填充）

（待实现完成后回填与上表对比。）
