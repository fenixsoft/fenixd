# Tasks: fix-observability-gaps

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: bin/fenixd_supervisor.py
  kind: modify
- path: tests/test_run_metrics_persistence.py
  kind: new
- path: tests/test_transition_context.py
  kind: new
- path: tests/test_supervisor_log_single_write.py
  kind: new
```

> 路径说明（2026-09-15 评审更正）：原注释称时间轴消费点「`core/dashboard/data.py` 或其派生包（前序 SPEC 创建，本注册时尚不存在，故不列入 Deliverables）」——**与实测不符**。实测：`core/dashboard/data.py` 已存在（单文件 5333 行，时间轴函数 `get_spec_timeline` 在 `:3373`，Transition 正则在 `:3411`），`core/dashboard/data/` 包尚不存在（前序 `refactor-dashboard-data-module` 仅为 `ready`，未实现）。同批 `fix-dashboard-read-path-performance/tasks.md` 已就同一处陈旧注释做更正，并给出结论：「不登记权威修改路径会导致交付集缺项」。据此本 SPEC 显式登记两处权威修改路径：run 收尾日志点 `core/agent_runner/runner.py`（实测存在；收尾日志点在 `:3183-3201` 成功分支、`:3271-3304` 失败分支，另有 `:930/:983/:995/:1083` 等早夭分支）、时间轴消费点 `core/dashboard/data.py`。
>
> **实现前置确认（必做）**：动手前确认 `refactor-dashboard-data-module` 是否已落地——未落地则直接改 `core/dashboard/data.py`；已落地（`data.py` 已拆为 `data/` 包）则按符号名在 `core/dashboard/data/timeline.py` 内修改，并在实现记录中注明实际文件路径。`core/agent_runner/runner.py` 同理：若前序 `refactor-agent-runner-module` 已落地，按符号名落到对应子模块。

## 1. run 终止指标落盘

- [x] 1.1 在 run 收尾（成功与失败分支）记录结构化指标：`run_id / spec / agent_type / duration_seconds / turns / usage / cost_usd / terminal / provider`（耗时取自既有 `time.time() - start_time`）
- [x] 1.2 复用既有 usage/cost 计算与日志落盘设施，不另起一套
- [x] 1.3 新增 `tests/test_run_metrics_persistence.py`：成功与失败两分支各产生一条含 duration 的指标
- [x] 1.4 全量 pytest（重点 `test_cost_observability`、`test_run_latency_stats`），独立 commit
- [x] 1.5 **消费点验收（R1「指标可被消费」的落地口径，不得只写不读）**：至少一个消费点改为优先读结构化指标，替代现行「由 run 文件 mtime 推算耗时」——现状 `core/dashboard/data.py:2566` `duration_seconds = max(0, int(stat.st_mtime - real_dt.timestamp()))`，spec 级 `total_duration` 亦为该值求和（`core/pm_engine/engine.py:618-624`）。若不改消费点，R1 的「MUST NOT 仅依赖『由 run 文件 mtime 推算耗时』」与场景「无需事后扫描 run 产物文件」均落空（只能人工 grep 日志）。若本 SPEC 决定不做消费迁移，须在 proposal/spec.md 显式降级为 Non-Goal 并说明留待后续 SPEC，不得两边都不落地。
- [x] 1.6 **计价不得双源**：新增落盘的 `cost_usd` 与 dashboard 现有计价表现算（`core/dashboard/data.py:3678` `_cost_summary_from_timeline`，成本来自 `get_spec_timeline` 的计价分支）**MUST NOT 叠加**造成双重计价。本次落盘的 `cost_usd` 只做事件留痕，页面成本口径维持既有计价表（或明确二选一），并在实现记录中写明选择；`test_cost_observability` 为护栏。

## 2. 状态转换结构化 context

- [x] 2.1 `state_machine.transition` 增加 context：`trigger_run_id` / `agent_type` / `channel`。**`transition_gate` 必须同样带 context**：`core/state_machine.py:825-864` 是第二条状态转换写路径（VERIFIED→TESTING 门禁逃生门），其日志前缀为 `Gate transition: `（小写 t，`:857-861`），**实测不被** `core/dashboard/data.py:3411` 的 `Transition: ` 正则命中（`pat.search('Gate transition: fix-foo verified → testing')` → False），且同样无 context。不改则 spec.md「每次状态转换 MUST 携带结构化 context」在门禁回退路径上落空，且该路径在「结构化优先」读侧既无结构化字段、又不走正则兜底，只能靠 `update_spec` 侧路径间接重建。
- [x] 2.1a 确认幂等短路分支（`core/state_machine.py:798-810`、`:849-855`）是否属 R2 的「状态转换」——old==new 未改变状态，建议在 spec.md 措辞中显式排除，避免实现者按字面给无状态变化的分支也补 context。
- [x] 2.2 各调用方补齐来源标注。**签名 MUST 以可选参数方式扩展**（如 `transition(spec, status, *, run_id=None, agent_type=None, channel=...)`），保证既有调用点不破。**全量调用点清单（2026-09-15 实测，`.transition(` 非测试命中）**：`core/pm_engine/dispatch.py`（12 处，自动路径）、`core/pm_engine/verification.py`（5）、`core/pm_engine/engine.py`（5）、`core/pm_engine/spec_review.py`（3）、`core/admin_monitor.py`（`:1573`/`:1703`，恢复/解冻路径 2）、`core/dashboard/data.py`（1，人工路径）、`bin/fenix_cli.py`（1，人工 CLI 路径）。逐一确认覆盖，不得遗漏（D2 声称「写侧补 context」，漏一处即该路径的 channel 缺失）。另：`.transition(` 被 20+ 个 `tests/*.py` 调用，签名向后兼容是不破既有测试的前提。
- [x] 2.2a 明确 `update_spec` 直写 status 的打回路径是否属 R2 的「每次状态转换」。该路径无 Transition 行（见 `core/dashboard/data.py:3390-3392` 的记载与 `:3497-3525` 的重建逻辑）。若纳入则须一并补 context；若不纳入须在 spec.md 显式排除，不得含糊。
- [x] 2.3 新增 `tests/test_transition_context.py`：自动/人工/恢复三来源的 context 断言，**含 `transition_gate` 路径**
- [x] 2.4 全量 pytest（重点 `test_state_machine`、`test_spec_timeline_*`），独立 commit

## 3. 时间轴消费结构化事件

- [x] 3.1 时间轴重建改为优先读 Transition 的结构化 context；message 正则保留为历史日志兜底。**逐行互斥**：同一日志行有 context 走结构化解、无 context 走正则，同一行不得产出两个状态节点。
- [x] 3.1a **保留既有去重**：`get_spec_timeline` 现有「Transition 节点 vs `update_spec` 直写节点（Δt<2s 且目标相同）去重跳过」逻辑（`core/dashboard/data.py:3497-3525`，注释：「`transition()` 成对写的 Updated SPEC 行…去重跳过」）MUST 保留——`transition()` 一次转换会写 `Transition:` 与 `Updated SPEC` 两行，新解析路径不得让同一次转换在时间轴上出现两个状态节点。**混合窗口必须有用例**：升级后同一日志文件内必然同时存在旧格式行（无 context）与新格式行（有 context），该文件必须能正确重建且无重复节点。
- [x] 3.2 断言：新格式走结构化解路径、旧格式走兜底路径、混合窗口三路均能重建，且事件数与去重后节点数符合预期（无重复 / 无丢失）
- [x] 3.3 全量 pytest（重点 `test_dashboard_timeline*`、`test_cli_time_display`），独立 commit

## 4. 审计窗口与双写修正

- [x] 4.1 `admin_state_history.json` 保留窗由 1 小时提升到 ≥24 小时（`core/admin_monitor.py:1959` `cutoff = now - 60 * 60`）。**口径必须写清**：同一函数 `_update_history`（`:1956-1982`）另有「active 集合」清理——只记录 `ready`/`implementing` 的状态变化（`:1962-1964` `if status not in ("ready","implementing"): continue`），且非这两个状态的 spec 记录被整体删除（`:1976-1981`）。故 24h 窗只对 ready↔implementing 的反复生效；spec.md 对应场景已同步澄清口径。flapping 检测（`_detect_flapping`，`:728-757`，窗口 `FLAPPING_WINDOW_MINUTES=10`，`:736`）按其自身 10 分钟窗过滤，不受保留窗提升影响——须有用例断言窗提升后 flapping 判定输出不变。
- [x] 4.1a 保留窗提升后 `changes` **只按时间裁剪、无条数上限**（`:1970` 仅 `[c for c in changes if c[0] >= cutoff]`），故 design「已有上限裁剪」的表述不成立。实现时须实测 24h 内的条目量级（可接受则记录结论，不可接受则加条数上限），并把 design 该条风险表述改准。
- [x] 4.2 修正 supervisor 日志双写。**注意：不能改「stderr 单向」**——实际启动命令把 stdout 与 stderr 都重定向到同一文件（`core/fenix_session.py:328`、`:362`、`skills/fenix-setup/SKILL.md:156`：`python3 .fenix/bin/fenixd_supervisor.py ... >> .fenix/logs/supervisor.log 2>&1`），改 stderr 后仍每行双写，spec.md「MUST NOT 同时 print 与写文件到同一路径」依旧不满足。正确做法：`log()`（`bin/fenixd_supervisor.py:218-224`）去掉 `print(line, flush=True)`，文件写为唯一 sink；若须保留控制台可见性，改为「仅当 stdout 未被重定向到 LOG_FILE 时才 print」。`main()` 的 FATAL 提示（`:308-317`，`file=sys.stderr`）不属本项，勿改动。
- [x] 4.3 新增 `tests/test_supervisor_log_single_write.py`；全量 pytest（重点 `test_admin_health_monitor`），独立 commit

## 5. 收尾

- [x] 5.1 全量 `bin/run_full_suite.py`（**必须全量回归，不得只跑子集**） + 指标落盘/转换 context 的实证（在真实 daemon 日志中确认新字段出现）
- [ ] 5.2 经用户确认时机后重启 daemon 并冒烟验证
