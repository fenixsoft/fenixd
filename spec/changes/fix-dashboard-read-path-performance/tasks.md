# Tasks: fix-dashboard-read-path-performance

## Deliverables

```yaml
- path: core/dashboard/data/summary.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/dashboard/watcher.py
  kind: modify
- path: tests/test_dashboard_index.py
  kind: modify
- path: tests/test_dashboard_index_incremental.py
  kind: new
- path: tests/test_run_tail_read_equivalence.py
  kind: new
- path: tests/test_runs_retention.py
  kind: new
```

> 路径说明：本 SPEC 的读路径修复落在 `core/dashboard/data.py`（经 `SummaryIndex`、`spec_summary`、`get_runs`、`_read_run_lines`、`_runs_by_spec_sigs`、`_spec_dep_sigs` 等符号定位）。**实测（2026-09-15）：`core/dashboard/data.py` 已存在（单文件，约 256KB），`core/dashboard/data/` 包尚不存在**；前序 `refactor-dashboard-data-module` 当前为 `status: ready`（尚未实现），其拆分产物才是 `core/dashboard/data/` 包。（原注释称该文件「由前序 SPEC 创建、本 SPEC 注册时尚未存在」与实测不符，据此不登记权威修改路径会导致交付集缺项，故更正并显式登记 `data.py`。）
>
> **实现前置确认（必做）**：动手前确认 `refactor-dashboard-data-module` 是否已落地——
> - **未落地**：直接在 `core/dashboard/data.py` 内按符号名修改（本 Deliverables 已登记该文件）。
> - **已落地**（`data.py` 已拆为 `data/` 包）：按符号名在包内对应子模块修改，并在实现记录中注明实际文件路径。
>
> **实现记录（2026-09-17，实测 `refactor-dashboard-data-module` 已落地）**：
> `core/dashboard/data.py` 已拆为 `core/dashboard/data/` 包，本 SPEC 按符号名在
> 包内子模块修改，实际文件路径：
> - `core/dashboard/data/summary.py`：`SummaryIndex`、`spec_summary`、`_runs_by_spec_sigs`、
>   `_spec_dep_sigs`、`_entry_fingerprint`、`_impl_budget_max`（缓存化）
> - `core/dashboard/data/runs.py`：`get_runs`（预选文件集）、`_read_run_lines`（尾读）、
>   `_run_meta_cached`（memo）、`runs_retention_check`（新增）
> - `core/dashboard/data/tasks.py`：`task_progress`/`parse_tasks`/`run_task_progress`（透传预选集）
> - `core/run_task_track.py`：`find_impl_run_file`（预选文件集入口）
> - `core/dashboard/data/__init__.py`：门面 re-export `runs_retention_check`
> 另见 `.fenix-run-result.json` 的 `findings` 中 `deliverable-dispute` 登记。
>
> **依赖登记不一致（需操作者处理）**：STATE.md 为本 SPEC 登记的 `depends_on` 是 `refactor-verification-module`，而 proposal「注意」段的并发避让理由指向 `refactor-dashboard-data-module` —— 两者不一致。若不同文件并发跑（`refactor-dashboard-data-module` 优先级 1、status ready），调度器不会阻止二者同时改 `data.py`。需把 `depends_on: refactor-dashboard-data-module` 补登记（该动作在 STATE.md，超出本 SPEC 写边界）。

## 1. 基线测量与用例

- [x] 1.1 用 cProfile 测量修复前 `SummaryIndex` 冷重建耗时、`/api/overview` 单请求耗时、单次请求 `json.loads` 次数，记录为基线（写入 spec 目录 `baseline.md`）
- [x] 1.2 新增 `tests/test_dashboard_index_incremental.py`：断言「仅 1 个 spec 变化时不重算其余 spec」（用 spy 计数重算次数）
- [x] 1.3 新增 `tests/test_run_tail_read_equivalence.py`：尾读路径与全量读取对小文件/大文件/超长末行三种输入的解析结果等价
- [x] 1.4 **跨快照用例（关键，1.2 的等价性无法替代）**：依赖文件全未变、仅 STATE.md 中该 spec 的条目字段（如 `status`、`error`）变化时，断言该 spec 被重算且摘要 `status` 为新值。注意 spec.md 的「缓存结果与全量重建等价」是**同快照**对比——两条路径读同一 `entry`，即便漏了条目指纹也必然一致，故**不能**用它防住「条目变了但文件没变」的陈旧摘要。

## 2. SummaryIndex 增量失效

- [x] 2.1 修改 `SummaryIndex.get`：STATE 签名变化时保留既有缓存条目，只重算「新增 / 删除 / 自身签名变化」的 spec；全量重建仅用于 `idx is None` 或损坏
- [x] 2.1a **（阻塞级，必做）把 spec 自身的 STATE 条目并入失效签名**：`_spec_dep_sigs`（`core/dashboard/data.py:2937`）现只返回文件签名，**不含 `entry` 内容**；而 `spec_summary`（`:2819`）的输出直接由 `entry` 决定（`status`:2844、`priority`:2847、`created`/`updated`:2848-2849、`error`:2850、`reviewer_run`:2853、`start_after`:2857、`frozen_until`:2858、`frozen`:2861、`progress_phase`:2866、`budget_override`/`budget_used`:2832-2837、`verify_infra_rounds`:2891、`infra_failure_count`:2893；`task_progress`:2821 取 `entry.status`）。**若不补这一步，2.1 会引入真实回归**：spec 被预算/env 闸门置为 `blocked` 或自动冻结时依赖文件均未变，列表页将一直显示旧 `status`（现状由 `state_changed → idx = {}` 掩盖）。做法：把该 spec 的 `entry` 关键字段（至少上述字段，含 `_` 前缀计数）序列化为稳定指纹并并入 `_spec_dep_sigs` 返回值。
- [x] 2.1b 更新既有用例 `tests/test_dashboard_index.py::TestSummaryIndex::test_state_change_full_rebuild`（:124-142）与 `test_spec_deleted_removed_from_index`（:144）：其命名/注释（「STATE.md 新增一个 spec 条目 → 全量重建」）编码的是旧语义，`idx = {}` 移除后名实不符，须改名并补断言「新增 spec 计算 / 其余 spec 命中缓存」
- [x] 2.2 全量 pytest（重点 `test_dashboard_index` / `test_dashboard_watcher*` / `test_dashboard_data`），独立 commit

## 3. 消除 per-spec 全目录 glob

- [x] 3.1 `get_runs` 增加「接受预选文件集」的入口参数；`spec_summary` 改为从 `_runs_by_spec_sigs` 预扫描映射取本 spec 的 run 文件列表，不再自行 glob
- [x] 3.2 断言单轮目录 glob 次数为常数（测试内计数）；全量 pytest + 性能复测，独立 commit

## 4. run 尾读增量 + 元数据 memo

- [x] 4.1 `_read_run_lines` 改为「先 seek 尾部字节窗口读取；窗口内不足 N 行或行长超窗时回退全量逐行读」，保留「不得从行中间截断」的正确性论证与实现
- [x] 4.2 run 元数据（status/started/duration/size）按 `(path, mtime_ns, size)` memo（沿用既有 `_RUN_TASK_CACHE` 模式）
- [x] 4.3 全量 pytest + 1.3 等价性用例 + 性能复测，独立 commit

## 5. 落地 runs 保留策略

- [x] 5.1 在 daemon 周期任务中挂载 runs 清理：终态 run 移入归档 + 按 `runs.keep` 上限清理（参照既有 archive_check 段的挂载方式）
- [x] 5.1a **明确上限语义并防静默大批量删除**：`runs.keep` 缺省 50（`core/dashboard/data.py:4129`/`:4307`），而当前归档目录实测 343 个条目（活跃 311 个）——首次执行会一次删除约 293 个归档文件。要求：(a) 清理 MUST 记录日志（删除数量 + 文件名，可追溯）；(b) 每周期删除量 SHOULD 有上限或分批，避免单轮 I/O 尖峰；(c) 删前条目数记入 `baseline.md`。另需确认上限约束的是**归档目录**（活跃目录由「终态即移出」保证有界）——否则 watcher 注释（`core/dashboard/watcher.py:32`、`:219` 的「runs 保留 ≤50」）改成什么都无从谈起，5.2 无法正确落地。
- [x] 5.1b **归档删除的下游影响须在实现中确认**：归档 run 被读路径消费于 `spec_summary` 耗时回退（`data.py:2824` → `_spec_total_duration`:2767）、spec 时间轴（`data.py:3416`）、spec 详情运行历史（`data.py:3686`）、done 时刻耗时快照（`core/pm_engine/engine.py:621`）。终态 spec 的耗时已有 STATE 固化值（`_spec_total_duration` 的 persisted 分支）不受影响，但**非终态 spec 的归档 run 被删后其 timeline/运行历史会缩水**——proposal 的 Non-Goals「不改 HTTP 响应契约」只保证契约不变，内容会变，须在实现记录中显式确认该取舍可接受。
- [x] 5.2 修正 `core/dashboard/watcher.py` 中关于 runs 保留数量的失实注释
- [x] 5.3 新增 `tests/test_runs_retention.py`：终态归档 + 上限清理；全量 pytest，独立 commit

## 6. 收尾

- [x] 6.1 复测三个基线指标，与 1.1 对比写入 `baseline.md` 结论；全量 `bin/run_full_suite.py`
- [x] 6.2 经用户确认时机后重启 daemon 使新代码生效并冒烟验证（实现侧：根路径落位 restart_request 交付物 + 冒烟预演通过——参照 refactor-dashboard-data-module 先例 99c7d9a0，实际重启由 supervisor 消费 restart_request 信号完成）
