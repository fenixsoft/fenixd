## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/agent_runner/provider_circuit.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_runner/latency.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/pm_engine/dispatch/backoff.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/tui_format.py
  kind: modify
- path: core/dashboard/routes/alert_routes.py
  kind: modify
- path: core/dashboard/data/summary.py
  kind: modify
- path: core/dashboard/data/spec_archive.py
  kind: modify
- path: core/dashboard/data/runs.py
  kind: modify
- path: core/dashboard/data/artifacts.py
  kind: modify
- path: core/code_review.py
  kind: modify
- path: core/evolution.py
  kind: modify
- path: core/regression.py
  kind: modify
- path: core/worktree_manager/stash_guard.py
  kind: modify
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: bin/fenix_process.py
  kind: modify
- path: bin/fenix_dashboard.py
  kind: modify
- path: bin/fenix_status.py
  kind: modify
```

注：文件清单为 2026-09-30 盘点快照，激活时以 SPEC-A 守卫白名单实际内容为准；若实际白名单含本清单外文件，随所属批次一并迁移（`--modify` 补声明）。守卫文件 `tests/test_timelib_guard.py` 由 SPEC-A 新建（主树尚不存在，不可声明 modify），白名单收缩任务在其落地后执行；测试文件（`tests/test_*.py`）随各批同步修改，不逐个声明。

## 1. 批①：self_review naive 气泡迁 aware UTC

- [x] 1.1 characterization 测试先行：以固定 run 数据集 + 固定调度配置固化 `_in_window`/`collect_runs_stats`/调度触发的现行为（命中集合快照），作为迁移等价性基准
- [x] 1.2 `core/self_review.py` 窗口计算迁 aware UTC：19 处裸 `now()` 走 `timelib.now_utc()`，2 处 `fromtimestamp` 走 `timelib.from_epoch`，1 处裸 `fromisoformat` 走 `timelib.parse_ts`，`_in_window`/`window_start`/`window_end` 全 aware 比较；`_parse_run_at` 保持本地墙钟语义解析后立即转 aware UTC，配置字面值不变
- [x] 1.3 同步迁移 `core/self_review.py` 测试替身时间戳格式（grep 测试内 naive 串构造、`ts[:19]` 切片、`fromtimestamp`），跑通 characterization 等价基准与全量自省测试
- [x] 1.4 守卫白名单收缩：清除 `self_review.py` 全部条目，僵尸检测通过

## 2. 批②：agent_runner 域与入口

- [x] 2.1 `core/agent_runner/runner.py`/`liveness.py`/`provider_circuit.py`：`fromtimestamp` 改 `timelib.from_epoch`，`fromisoformat` 改 `timelib.parse_ts`，liveness 心跳/stale 判定行为以既有测试锁定
- [x] 2.2 `core/agent_runner/prompt_builder.py`（2 处裸 `now()`）与 `core/agent_runner/latency.py`（`fromisoformat`）迁移，测试同步
- [x] 2.3 `fenixd.py`：`fromtimestamp` 与 `fromisoformat` 迁移，daemon 入口行为以既有生命周期测试锁定
- [x] 2.4 守卫白名单收缩：清除 agent_runner 域与 `fenixd.py` 全部条目

## 3. 批③：pm_engine 与 admin/store 域

- [x] 3.1 `core/pm_engine/engine.py`/`dispatch/backoff.py`/`verification/pipeline.py`：`fromisoformat`/`fromtimestamp` 改走 timelib，退避/升级判定行为以既有测试锁定
- [x] 3.2 `core/admin_store.py`/`state_machine.py`/`admin_monitor.py`/`tui_format.py`/`dashboard/routes/alert_routes.py`：`fromisoformat` 与 `admin_monitor` 3 处裸 `now()`、2 处 `fromtimestamp` 迁移，告警时间戳与 TUI 展示格式不变
- [x] 3.3 守卫白名单收缩：清除本批域全部条目

## 4. 批④：dashboard data 与散点收尾

- [x] 4.1 `core/dashboard/data/summary.py`/`spec_archive.py`/`runs.py`/`artifacts.py`：裸 `now()` 与 `fromtimestamp`/`fromisoformat` 迁移，dashboard 只读契约（容错、不抛）保持；抽查 dashboard API 时间字段（`frozen_until` 等）在前端 dayjs 渲染无 Invalid Date
- [x] 4.2 `core/code_review.py`（6 处裸 `now()`，含 aware→naive 剥时区写入点改 aware UTC 直写）、`evolution.py`（3 处）、`regression.py`、`worktree_manager/stash_guard.py`/`mergeback.py` 各 1 处迁移
- [x] 4.3 守卫白名单收缩：清除本批域全部条目

## 5. 批⑤：CLI 展示脚本与白名单清零

- [x] 5.1 `bin/fenix_process.py`/`fenix_dashboard.py` 私有 `_local_ts` 退役改走 `timelib.fmt_display`，三形态输入（`Z`/`+00:00`/无后缀）输出与迁移前逐字一致（对照测试锁定）；`bin/fenix_dashboard.py`/`fenix_status.py` 裸 `fromisoformat`/`now()` 改走 timelib
- [x] 5.2 守卫白名单清零为空列表，僵尸条目检测全绿，棘轮零豁免稳态确认
- [ ] 5.3 全量单测回归（`python3 -m pytest tests/ -x -q`）通过；`.fenix/todo.md` 登记 `.fenix/bin` 部署副本刷新人工步骤（未跟踪文件不随 merge-back 落地，主树手工同步或重启部署机制）
