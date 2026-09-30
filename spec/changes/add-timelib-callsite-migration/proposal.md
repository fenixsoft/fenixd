## Why

`add-timelib-consolidation-layer`（SPEC-A）已落地 `core/timelib.py` 收拢层、分层约定与 AST 守卫棘轮，但守卫白名单仍含上线当日全部存量违例：约 41 处写侧裸 `datetime.now()`（naive 本地）、16 处裸 `fromtimestamp()`、13 个文件绕过 `parse_ts` 的 `fromisoformat()`。收拢层已冻结而存量调用点未迁入，则 4→1 的 naive 策略定音只覆盖新代码，旧写手继续产出 naive 本地时间戳，读侧统一策略的收益无法兑现。

## What Changes

- `self_review.py` 本地 naive 气泡整体迁 aware UTC：19 处裸 `now()`、2 处 `fromtimestamp()`、`_in_window` 窗口比较、`HH:MM` 调度语义边界（人类时刻按本地墙钟解析、进入计算前转 aware UTC）
- 写侧散点迁移：`code_review.py`(6)、`evolution.py`(3)、`admin_monitor.py`(3)、`agent_runner/prompt_builder.py`(2)、`worktree_manager/stash_guard.py`、`mergeback.py`、`regression.py`、`dashboard/data/summary.py`、`spec_archive.py`、`bin/fenix_dashboard.py` 各 1
- 裸 `fromtimestamp()` 16 处改走 `timelib.from_epoch`（`agent_runner/runner.py`、`liveness.py`、`provider_circuit.py`、`admin_monitor.py`、`pm_engine` 3 文件、`fenixd.py`、dashboard data 2 文件、`bin/fenix_process.py`、`self_review.py` 2 处随气泡批）
- 绕过收拢层的 `fromisoformat()` 13 文件改走 `timelib.parse_ts`（`tui_format`、`admin_store`、`state_machine`、`latency`、`pm_engine/engine`、`alert_routes`、`admin_monitor`、`runner`、dashboard data、`fenixd.py`、`bin/fenix_dashboard.py`、`bin/fenix_status.py`）
- CLI 展示脚本统一 `timelib.fmt_display`：`bin/fenix_process.py` / `fenix_dashboard.py` 的 `_local_ts` 私有助手退役
- 守卫白名单清零：全部存量违例迁毕后白名单收缩为空，僵尸条目检测全绿
- `bin/` 真身修改后，`.fenix/bin` 部署副本刷新登记为人工步骤（未跟踪文件，merge-back 不落地，见 design）

**明确不在范围**：浏览器前端 dayjs（36 处，本地渲染正确）；`verify_engine/browser.py` `timezone_id`（playwright 语义）；`.astimezone()` 渲染边界转换（dashboard 展示路由合法在用，未列入守卫禁用模式）；`knowledge.py`/`knowledge_backfill.py` 盖戳时间源（SPEC-A 已迁）。

## Capabilities

### New Capabilities
- `timelib-callsite-migration`: 存量时间调用点向 `timelib` 收拢层迁移的完成性契约——守卫白名单清零、调度语义边界换算规则、bin 展示脚本统一、部署副本人工刷新登记

### Modified Capabilities

（无——本 SPEC 全部为调用点迁移与既有行为等价改造，不改任何既有能力的需求；`self_review` 气泡迁移的窗口判定结果与迁移前一致，属实现层等价替换）

## Impact

- **修改面**：约 20 个生产文件 + `bin/` 3 个 CLI 脚本 + 对应测试同步（自省窗口/调度类测试为用户级配置敏感区，须逐域核对替身时间戳格式）
- **行为等价性**：迁移后各域对外输出时刻不变（aware UTC 存储值与原 naive 本地值表示同一时刻）；唯一可感知差异是「字段开始带时区后缀」（naive 串 → `+00:00`/`Z` 后缀），下游解析一律走 `parse_ts` 已兼容
- **依赖**：`core/timelib.py` API 冻结（SPEC-A 交付）；本 SPEC 激活前置条件 = SPEC-A 归档
- **无 UI、无第三方依赖、无数据库迁移**
