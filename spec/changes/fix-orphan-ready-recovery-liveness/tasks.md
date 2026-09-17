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
- path: tests/test_run_spec_prefixed_attribution.py
  kind: modify
```

> `tests/test_run_spec_prefixed_attribution.py` 为**必改**项而非可选项：该文件 `_write_run()` 缺省 `tail="result"`（`:43-54`），其 `TestLivenessStreamRecent` 两例（`:229-238` 邻近）正是用「末行 = `result` 终态 + mtime 新鲜」的夹具断言 `_stream_recent(...) is True`——1.2 落地后必红。改夹具或改断言，二者择一但 MUST 保持「前缀归属守卫」这条原测试意图（详见 3.9）。

## 1. 存活判据：末行终态即非存活（recovery-state-consistency）

- [x] 1.1 `core/agent_runner/liveness.py` 新增模块级助手 `_file_tail_is_terminal(run_file) -> bool`：从文件尾部按字节窗口 seek 读取（**照** `core/dashboard/data/runs.py:293` `_read_run_lines` + `_READ_RUN_TAIL_WINDOW`（`:258`）的既有范式自实现——窗口首行是上一行残段必须丢弃；窗口内不足一行时回退全量逐行读。MUST NOT 反向 `import core.dashboard.*`，理由见 design D2），解析**末条非空行**，返回其 `type` 是否 ∈ `RUN_TERMINAL_EVENT_TYPES`。**失败方向固定为 fail-open**：文件不可读 / 空文件 / 末行损坏不可解析 / JSON 非 dict → 一律返回 False（= 非终态 = 仍视为存活）。文档字符串 MUST 写明「本助手判末行、`_file_has_terminal_event` 判全文件，语义不同不可互相替换」以及「superseded 不在终态集合内」两条约束
- [x] 1.2 `core/agent_runner/liveness.py::_stream_recent`（`liveness.py:284`）：在 `p.stat().st_mtime >= cutoff` 的命中分支内，追加「该文件末行非终态」条件——即 `mtime >= cutoff and not _file_tail_is_terminal(p)` 才 `return True`。MUST 复用 1.1 助手，MUST NOT 在调用点内联第二套末行解析。方法文档字符串 MUST 说明「mtime 新鲜只证明文件被写过，末行终态证明 run 已终结」的判据分层，并交叉引用本次事故（daemon 主动 SIGTERM 的 run 在 120s 窗口内阻塞恢复）
- [x] 1.3 在 `liveness.py` 内以注释登记三处同型点的处置（design D5）：① 本处（`_stream_recent`）已修；② `core/worktree_manager.py::_latest_stream_mtime`（`:1338`）的保守持锁分支本次未命中、书面 defer；③ `core/admin_monitor.py::_has_recent_spec_run`（`:365`）→ `spec_is_undriven`（`:392`）书面 defer 给在飞的 `evo-orphaned-state-probe-calibration`。每处注明「判定对象 / 为何本次不改 / 承接方」，MUST NOT 静默忽略。②的注释 MUST 额外记下**两处判定的交互**（勿误以为彼此独立）：本处修好后，`_on_spec_ready`（`core/pm_engine/engine.py:359-372`）对「在册陈旧锁 + 终态末行 + 挂锁流新鲜」的 SPEC 会由「静默跳过 live attempt」变为「锁冲突 → 进退避 → 退避耗尽可能 `dispatch_stalled` 升级」；因②的 `STALE_LOCK_IDLE_SECONDS`（1800s）远长于本处 120s 判活窗口，该升级路径在修复前同样存在（仅延后 120 秒），本 SPEC 不因此扩面，但②的承接方需知悉该形态会显性化为告警

## 2. 孤儿 ready 短周期精触发（full-scan-resilience）

- [x] 2.1 `core/event_bus.py`：新增 `recover_orphan_ready()` 公开入口——经 `state_machine.read_all()` 遍历，仅对 `status == "ready"` 的条目调用**既有** `_recover_ready(name, entry)`；逐条 try/except 隔离（单条异常记 error 日志后继续，沿用 `full_scan` 的 handled/failed 口径），整轮 MUST NOT 因单条异常中止。**入口 MUST 先过两道「有意等待」早退**（design D3）：`entry.get("_cancelled_hold")` 为真 → 跳过；`self.pm_engine._dispatch_backoffed(entry)` 为真（读 `_dispatch_backoff_until`，`core/pm_engine/dispatch.py:1427-1439`）→ 跳过。两条早退 MUST 零 STATE 写入、MUST NOT 打印「re-triggering implement for orphan ready」日志。任一闸门判定的异常 MUST 按「不早退」fail-open（保底恢复不被新闸门吞掉），并记日志
- [x] 2.2 `core/event_bus.py::_recover_ready`：把 `state_machine.update_spec(name, {"error": None})` 写回改为**仅在 `entry.get("error")` 非空时执行**（稳态零 STATE 写入，design D4）。保留既有注释中「error 清空必须写回，否则下轮 full_scan 仍读到此 error」的论证并补一句说明为何该论证仅对 error 非空成立。行为等价性：对已为 None 的字段写 None 本即空操作
- [x] 2.3 `fenixd.py` 主循环：在既有计时段模式中新增 `orphan_ready_check_ts`（60 秒粒度，对齐 `recovery_watch_ts` / `scheduling_check_ts` 的挂载写法），到期调用 `self.event_bus.recover_orphan_ready()`，异常捕获记日志不中断主循环。MUST NOT 新建线程或 `threading.Timer`；MUST NOT 改动 `schedule.poll_interval_minutes` 与 `full_scan()` 触发源
- [x] 2.4 核对精触发**未绕过任何闸门**，并把核对结论写入 `recover_orphan_ready()` 文档字符串（不是口头承诺）。核对口径以代码为准（2026-09-17 已核）：
  - 恢复侧既有门：`start_after_pending`（`core/event_bus.py:268-277`）、存活子进程（`_ready_has_live_child`，`:282`）；
  - 派发侧既有门（`_on_spec_ready`，`core/pm_engine/engine.py:316-425`）：关闭中 / 10 秒冷却 / 单飞 / `has_active_worktree` / `_dispatch_backoffed` / `start_after` / 依赖；
  - **方位校正（勿按错误归属核对）**：`_instant_fail_cooled` 与并发闸 `max_concurrent` 不在 `_on_spec_ready` 内，而在 `_process_queue` 的候选筛选与调度处（`core/pm_engine/dispatch.py:437`、`503`、`378-393`）——经 `_on_spec_ready → _enqueue → _process_queue` 生效即可判定为「未被绕过」；
  - **须纠正的原表述**：`_recover_ready` 与 `_on_spec_ready` 均**不读** `_cancelled_hold`，故「`_cancelled_hold` 由 `_on_spec_ready` 链路上的既有守卫覆盖」不成立——该守卫即 2.1 新增的早退闸门（复用既有标记，非新判据）
- [x] 2.5 有界性落地核对（design D4）：断言 60 秒重试的重复入队由 `_enqueue` 的 `(spec, agent_type)` 去重吸收（`core/pm_engine/dispatch.py:269-275`），而非由 10 秒冷却吸收；把该结论（及「冷却窗口不足以吸收 60 秒间隔」）写入 `recover_orphan_ready()` 文档字符串，防止后续有人删掉去重或误以为冷却已兜住

## 3. 回归测试

- [x] 3.1 `tests/test_run_lifecycle_governance.py::TestHasLiveAttempt` 新增「末行终态 ⇒ 不存活」参数化用例：构造 mtime 在 120s 窗口内的 run 流，末行分别写 `result` / `error` / `interrupted` / `cancelled`，`_pgrep_live_attempt` 判否 → 断言 `has_live_attempt(spec) is False`。**必须含本次事故形态**：末行 `{"type":"error","error":"Exit code: 143","exit_code":143}`
- [x] 3.2 同文件新增「fail-open 方向」用例：末行为非终态事件（如 `{"type":"system"}`）且 mtime 新鲜 → 断言返回 **True**；并加「末行损坏 JSON」与「空文件」两例 → 断言均返回 **True**（活 run 不被误杀）
- [x] 3.3 同文件新增「`superseded` 末行 ⇒ 仍存活」用例：末行 `{"type":"superseded",...}` 且 mtime 新鲜 → 断言返回 **True**（design D1：原地重试弃置窗口内不得判死，防双派发）。断言失败信息中写明「superseded 属弃置标记非终结」
- [x] 3.4 `tests/test_event_bus.py` 新增精触发用例：孤儿 ready（error 非空 + 无存活子进程 + 无 `start_after`）经 `recover_orphan_ready()` 触发重派（断言 `handle_event("spec_ready", ...)` 被调用、`update_spec` 收到 `{"error": None}`）；`start_after` 未到期与 `_cancelled_hold` 的 ready 不被重派
- [x] 3.5 `tests/test_event_bus.py` 新增「稳态零写入」用例：error 已为空的健康 ready SPEC 经 `recover_orphan_ready()` 处理后，断言 `state_machine.update_spec` / `write_all` **零调用**（把 design D4 的「60 秒零写」变成可执行断言）
- [x] 3.6 `tests/test_event_bus.py` 新增单条隔离用例：某条 ready SPEC 在恢复处理中抛异常 → 断言其余 ready SPEC 的处理照常完成，且异常被记 error 日志、未向上抛出
- [x] 3.7 `tests/test_daemon_lifecycle_races.py` 新增终态口径单源防漂移用例（对齐该文件既有 `test_file_has_terminal_event_shared_helper` 模式）：断言 `_file_tail_is_terminal` 对 `RUN_TERMINAL_EVENT_TYPES` 全集的判定与对 `superseded` 的判定分属两侧——防后续有人「顺手」把 superseded 并入终态集合
- [x] 3.9 **既有断言必改项**：`tests/test_run_spec_prefixed_attribution.py::TestLivenessStreamRecent` 的两例以「末行 = `result`（终态）+ mtime 新鲜」为夹具断言 `_stream_recent(...) is True`（夹具 `_write_run()` 缺省 `tail="result"`，`:43-54`），1.2 落地后必红。处置（择一，但 MUST 保留原测试的「spec 名互为前缀不得互相归属」意图）：① 夹具改为非终态末行（如 `tail="system"`，与本仓 `tests/test_run_lifecycle_governance.py::touch_run_stream` 的 `{"type":"system"}` 口径一致）；或 ② 保留 `result` 夹具并把断言翻转为 `is False`，另加一例证明「同前缀的另一 spec 流文件不参与本 spec 归属判定」。选 ① 时 MUST 在 3.1/3.3 的用例中另起一份终态夹具，不得让终态用例依赖此默认值
- [x] 3.10 `tests/test_event_bus.py` 新增「有意等待早退」用例（design D3）：① ready + `_dispatch_backoff_until` 未到期 → 经 `recover_orphan_ready()` 处理时 MUST 既不重派、也不清 error、且 `state_machine.update_spec` / `write_all` **零调用**（断言 `_handle_dispatch_lock_conflict` 写入的「backoff until」error 未被抹掉）；② ready + `_cancelled_hold=True` → 同样零写入、零重派、无「re-triggering implement for orphan ready」日志；③ 退避已到期（`_dispatch_backoff_until` 为过去时刻）→ MUST 恢复正常处理路径（防新闸门把恢复永久吞掉）
- [x] 3.11 `tests/test_run_lifecycle_governance.py` 新增去重有界性用例：ready SPEC 已在 `_run_queue` 中等待并发槽时，重复经 `recover_orphan_ready()` → `spec_ready` 触发 3 次，断言 `_run_queue` 中该 `(spec, "implementer")` 条目数恒为 1（锁定 design D4 的真实吸收点，防后续有人删掉 `_enqueue` 去重后误以为冷却已兜住）
- [x] 3.12 全量回归走有界入口 `python3 bin/run_full_suite.py --timeout 3600`（MUST NOT 裸调 `pytest tests/ -q`）；重点确认 `tests/test_run_lifecycle_governance.py`、`tests/test_event_bus.py`、`tests/test_daemon_lifecycle_races.py`、`tests/test_pm_recovery.py`、`tests/test_dashboard_data.py`、`tests/test_retry_orphan_active_runs.py`、`tests/test_run_spec_prefixed_attribution.py`、`tests/test_characterization_split.py`、`tests/test_transient_backoff.py`、`tests/test_orphaned_state_signal.py` 全绿，并与 `--baseline` 对比确认无新增失败。**放宽 `_stream_recent` 判据的连带面 MUST 由 baseline 对比兜住**：任何以「终态末行 + 新鲜 mtime」夹具隐式依赖「判定为存活」的既有用例都会在此暴露，逐条按 3.9 的口径处置（改夹具或翻断言），MUST NOT 用放宽判据（如把 fail-open 改成 fail-closed）换取测试变绿

## 4. 验证

- [x] 4.1 本地构造事故复现夹具：临时 runs 目录内放一个 mtime 新鲜的 run 流、末行写 `error` 终态，断言修复前 `has_live_attempt` 返回 True、修复后返回 False（把「取证」变成可复跑的对照）
- [x] 4.2 确认 `full_scan()` 的触发源数量与间隔常量无变化（`schedule.poll_interval_minutes` 仍为 30、periodic scanner 线程仍只有一个），且新增的是**同步调用**而非新线程/Timer——核对 `fenixd.py` 主循环的计时段清单与线程数
- [x] 4.3 真实环境观察：daemon 运行期间若出现 ready 态孤儿，日志中 `Recovery: re-triggering implement for orphan ready` 的出现时刻与孤儿产生时刻之差应为**秒级**（而非分钟级）；同时确认日志中**未**出现稳态 ready SPEC 的周期性 `Updated SPEC` 刷屏（design D4 的零写放大）
- [x] 4.4 退避窗口观察（design D3 早退闸门的真实环境验证）：构造/等待一次 `Dispatch lock conflict … backoff Ns` 后，统计退避窗口内的日志与 STATE.md 写入——精触发 MUST NOT 在该窗口内产生 `Updated SPEC` 写入，MUST NOT 出现「Recovery: re-triggering implement for orphan ready」；窗口结束后恢复链路 MUST 正常接管（退避到期的重试或下一轮精触发完成派发）。核对既有的退避到期重入路径（`_schedule_backoff_retry`）与精触发不互相打架
