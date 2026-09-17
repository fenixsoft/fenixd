# Tasks: fix-orphan-ready-recovery-liveness

## Deliverables

```yaml
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: tests/test_run_lifecycle_governance.py
  kind: modify
- path: tests/test_event_bus.py
  kind: modify
- path: tests/test_daemon_lifecycle_races.py
  kind: modify
```

## 1. 存活判据：末行终态即非存活（recovery-state-consistency）

- [ ] 1.1 `core/agent_runner/liveness.py` 新增模块级助手 `_file_tail_is_terminal(run_file) -> bool`：从文件尾部按字节窗口 seek 读取（复用 `core/dashboard/data/runs.py` 既有 `_read_run_tail_window` 范式——窗口首行是上一行残段必须丢弃；窗口内不足一行时回退全量逐行读），解析**末条非空行**，返回其 `type` 是否 ∈ `RUN_TERMINAL_EVENT_TYPES`。**失败方向固定为 fail-open**：文件不可读 / 空文件 / 末行损坏不可解析 / JSON 非 dict → 一律返回 False（= 非终态 = 仍视为存活）。文档字符串 MUST 写明「本助手判末行、`_file_has_terminal_event` 判全文件，语义不同不可互相替换」以及「superseded 不在终态集合内」两条约束
- [ ] 1.2 `core/agent_runner/liveness.py::_stream_recent`（`liveness.py:284`）：在 `p.stat().st_mtime >= cutoff` 的命中分支内，追加「该文件末行非终态」条件——即 `mtime >= cutoff and not _file_tail_is_terminal(p)` 才 `return True`。MUST 复用 1.1 助手，MUST NOT 在调用点内联第二套末行解析。方法文档字符串 MUST 说明「mtime 新鲜只证明文件被写过，末行终态证明 run 已终结」的判据分层，并交叉引用本次事故（daemon 主动 SIGTERM 的 run 在 120s 窗口内阻塞恢复）
- [ ] 1.3 在 `liveness.py` 内以注释登记三处同型点的处置（design D5）：① 本处（`_stream_recent`）已修；② `core/worktree_manager.py::_latest_stream_mtime` 的保守持锁分支本次未命中、书面 defer；③ `core/admin_monitor.py::_has_recent_spec_run` → `spec_is_undriven` 书面 defer 给在飞的 `evo-orphaned-state-probe-calibration`。每处注明「判定对象 / 为何本次不改 / 承接方」，MUST NOT 静默忽略

## 2. 孤儿 ready 短周期精触发（full-scan-resilience）

- [ ] 2.1 `core/event_bus.py`：新增 `recover_orphan_ready()` 公开入口——经 `state_machine.read_all()` 遍历，仅对 `status == "ready"` 的条目调用**既有** `_recover_ready(name, entry)`；逐条 try/except 隔离（单条异常记 error 日志后继续，沿用 `full_scan` 的 handled/failed 口径），整轮 MUST NOT 因单条异常中止
- [ ] 2.2 `core/event_bus.py::_recover_ready`：把 `state_machine.update_spec(name, {"error": None})` 写回改为**仅在 `entry.get("error")` 非空时执行**（稳态零 STATE 写入，design D4）。保留既有注释中「error 清空必须写回，否则下轮 full_scan 仍读到此 error」的论证并补一句说明为何该论证仅对 error 非空成立。行为等价性：对已为 None 的字段写 None 本即空操作
- [ ] 2.3 `fenixd.py` 主循环：在既有计时段模式中新增 `orphan_ready_check_ts`（60 秒粒度，对齐 `recovery_watch_ts` / `scheduling_check_ts` 的挂载写法），到期调用 `self.event_bus.recover_orphan_ready()`，异常捕获记日志不中断主循环。MUST NOT 新建线程或 `threading.Timer`；MUST NOT 改动 `schedule.poll_interval_minutes` 与 `full_scan()` 触发源
- [ ] 2.4 核对精触发**未绕过任何闸门**：确认 `start_after_pending` / `_cancelled_hold`（经 `_on_spec_ready` 链路既有守卫）/ 存活子进程三道门均在路径上，且 `_on_spec_ready` 内的依赖/预算/内容完整性/冻结/冷却/单飞闸门全部照常生效；把核对结论写入 `recover_orphan_ready()` 文档字符串（不是口头承诺）

## 3. 回归测试

- [ ] 3.1 `tests/test_run_lifecycle_governance.py::TestHasLiveAttempt` 新增「末行终态 ⇒ 不存活」参数化用例：构造 mtime 在 120s 窗口内的 run 流，末行分别写 `result` / `error` / `interrupted` / `cancelled`，`_pgrep_live_attempt` 判否 → 断言 `has_live_attempt(spec) is False`。**必须含本次事故形态**：末行 `{"type":"error","error":"Exit code: 143","exit_code":143}`
- [ ] 3.2 同文件新增「fail-open 方向」用例：末行为非终态事件（如 `{"type":"system"}`）且 mtime 新鲜 → 断言返回 **True**；并加「末行损坏 JSON」与「空文件」两例 → 断言均返回 **True**（活 run 不被误杀）
- [ ] 3.3 同文件新增「`superseded` 末行 ⇒ 仍存活」用例：末行 `{"type":"superseded",...}` 且 mtime 新鲜 → 断言返回 **True**（design D1：原地重试弃置窗口内不得判死，防双派发）。断言失败信息中写明「superseded 属弃置标记非终结」
- [ ] 3.4 `tests/test_event_bus.py` 新增精触发用例：孤儿 ready（error 非空 + 无存活子进程 + 无 `start_after`）经 `recover_orphan_ready()` 触发重派（断言 `handle_event("spec_ready", ...)` 被调用、`update_spec` 收到 `{"error": None}`）；`start_after` 未到期与 `_cancelled_hold` 的 ready 不被重派
- [ ] 3.5 `tests/test_event_bus.py` 新增「稳态零写入」用例：error 已为空的健康 ready SPEC 经 `recover_orphan_ready()` 处理后，断言 `state_machine.update_spec` / `write_all` **零调用**（把 design D4 的「60 秒零写」变成可执行断言）
- [ ] 3.6 `tests/test_event_bus.py` 新增单条隔离用例：某条 ready SPEC 在恢复处理中抛异常 → 断言其余 ready SPEC 的处理照常完成，且异常被记 error 日志、未向上抛出
- [ ] 3.7 `tests/test_daemon_lifecycle_races.py` 新增终态口径单源防漂移用例（对齐该文件既有 `test_file_has_terminal_event_shared_helper` 模式）：断言 `_file_tail_is_terminal` 对 `RUN_TERMINAL_EVENT_TYPES` 全集的判定与对 `superseded` 的判定分属两侧——防后续有人「顺手」把 superseded 并入终态集合
- [ ] 3.8 全量回归走有界入口 `python3 bin/run_full_suite.py --timeout 3600`（MUST NOT 裸调 `pytest tests/ -q`）；重点确认 `tests/test_run_lifecycle_governance.py`、`tests/test_event_bus.py`、`tests/test_daemon_lifecycle_races.py`、`tests/test_pm_recovery.py`、`tests/test_dashboard_data.py`、`tests/test_retry_orphan_active_runs.py` 全绿，并与 `--baseline` 对比确认无新增失败

## 4. 验证

- [ ] 4.1 本地构造事故复现夹具：临时 runs 目录内放一个 mtime 新鲜的 run 流、末行写 `error` 终态，断言修复前 `has_live_attempt` 返回 True、修复后返回 False（把「取证」变成可复跑的对照）
- [ ] 4.2 确认 `full_scan()` 的触发源数量与间隔常量无变化（`schedule.poll_interval_minutes` 仍为 30、periodic scanner 线程仍只有一个），且新增的是**同步调用**而非新线程/Timer——核对 `fenixd.py` 主循环的计时段清单与线程数
- [ ] 4.3 真实环境观察：daemon 运行期间若出现 ready 态孤儿，日志中 `Recovery: re-triggering implement for orphan ready` 的出现时刻与孤儿产生时刻之差应为**秒级**（而非分钟级）；同时确认日志中**未**出现稳态 ready SPEC 的周期性 `Updated SPEC` 刷屏（design D4 的零写放大）
