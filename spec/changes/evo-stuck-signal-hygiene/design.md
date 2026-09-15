# design — stuck-signal-hygiene

## 现状（行号以当前 HEAD 为准）

- `_detect_stuck`（`core/admin_monitor.py:625-655`）：`updated` 超 `stuck_threshold_minutes` 且 `!_has_recent_progress` → 产生 stuck 信号。
- `_has_recent_progress`（`core/admin_monitor.py:1565`）：按 run 文件 mtime 判据（宽限 `max(STUCK_GRACE_MINUTES=10, interval_minutes*2)`，`:65`）；`_spec_from_run_id` 的 `-r<n>` 解析已由 8e510a87 修复。
- `_throttled`（`core/admin_monitor.py:890`）：唤起路径节流——查 `latest_signal` + `unhandled_for`。
- `merge_signal`（`core/admin_store.py:182`）：状态沉淀——同 `(spec, signal_type, status_hash)` 不新增记录、只刷 `last_seen`；`_signal_status_hash`（`core/admin_monitor.py:783`）以 `sha1(spec+status+error+updated)` 判定「状态未变」。
- 09-14 连发事故（14:46–15:31，`fix-command-main-serve-scope`）发生在 `merge_signal` 上线之前，**已由既有机制覆盖**。

## D1 进程存活反证（复用既有 API，不改 `agent_runner`）

- **数据源 = `AgentRunner.running_run_ids()`**（`core/agent_runner/runner.py:5013`，既有公开 API）：以进程表 `_running_agents`（`run_id → subprocess.Popen`）为真相，返回「进程仍存活（`proc.poll() is None`）」的 run_id 列表。
- ⚠️ **run 文件（`.fenix/runs/*.jsonl`）不携带 pid**（`append_run_line` 写入条目无 pid 字段）——首版 design 声称「解析 run 文件/转录中的 pid」为**错误前提**，已废弃。`os.kill(pid, 0)` 自解析方案不可行。
- `AdminMonitor` 已持有 `self.agent_runner`（`__init__` 注入，`core/admin_monitor.py:246`），无需新增跨类依赖；`agent_runner is None`（CLI/测试态）→ 跳过本检查，退回文件活跃度判据。
- 判定：`_detect_stuck` 中，若该 spec 存在活跃 run（`running_run_ids()` 中的 run_id 经 `run_spec_part` 命中该 spec，前缀取自 `RUN_ID_AGENT_PREFIXES` 唯一真源）→ 直接 `continue`（非 stuck）。
  - ⚠️ **run_id → spec 归属解析必须用 `_spec_from_run_id`（`core/admin_monitor.py:1511`，本模块既有方法）**，不可用 `run_spec_part`（`core/agent_runner/run_files.py:66`）。原因：`run_spec_part` 仅剥离 `-a\d+`（attempt），不处理 `-r\d+`（瞬态重试）后缀；对 `impl-myspec-1735-a1-r1` 会返回 `myspec-1735-a1-r1`，归属失败。`_spec_from_run_id` 的正则 `-(?:a|r)\d+` 同时覆盖两者。**这正是 8e510a87 修复的 `-r<n>` 根因形态**（见 `admin_monitor.py:1517-1520`），D1 若沿用 `run_spec_part` 会让「进程存活反证」在瞬态重试期间（run 文件 mtime 在退避窗口停止增长）重新失效。若实现者坚持用 `run_spec_part`，必须先补齐其 `-r` 支持并加回归测试。
- **代价需文档化**：进程存活但 hang 且无输出（如等大模型响应）不判 stuck，由 `agents.run_timeout_seconds` 超时兜底终止；此为可接受的 trade-off（hang 场景由超时机制覆盖，不在本 SPEC 处理）。

## D2 去重边界：不新增代码，只补回归测试

- 「5 连发压缩为 1 条」**= 既有 `merge_signal` 状态沉淀 + `_throttled` 节流的语义**，本 SPEC **不新增** signal 记录层去重逻辑（首版 D2「落记录前查 `latest_signal`」与 `_throttled` 语义重叠，已删除）。
- 唯一动作：新增回归测试锁定「冷却窗口内同 `(spec, signal_type, status_hash)` 重复触发只保留 1 条 signal 记录」（09-14 连发场景的防回退护栏）。

## D3 处置后静默期

- **锚点定义**：`(spec, signal_type)` 最近一条 `kind=disposition` 记录中 `result∈{resolved, partially-resolved}` 的处置时刻（取该记录 `created`；处置记录由 `AdminMonitor` 在 admin run 收口时落盘，`status`/`result` 同值）。
- **查询**：`AdminStore` 新增 `latest_resolved_disposition(spec, signal_type)`——仅匹配 `kind=DISPOSITION` 且 `result∈{resolved, partially-resolved}`，返回最近记录或 None。**不复用 `latest_signal`**（后者匹配 `kind∈{SIGNAL, ESCALATION, DISPOSITION}` 且不按 `result` 过滤，会把 `failed`/`pending` disposition 误当 resolved）。
- **判定**：`_detect_stuck` 产信号前查该查询，距处置时刻 < `admin.stuck_silence_minutes`（默认 120）→ 跳过。⚠️ 仅作用于 `_detect_stuck`（signal_type=stuck）；其他 `_detect_*`（如 flapping、merge_streak）不受影响——proposal 目标仅针对 stuck 信号噪音。
- **边界**：`result=escalated`（admin 升级人工）不触发静默——人工处置是唯一出路，不得被静默吞掉（与 `DISPOSITION_AUTO_RESET_SIGNAL_TYPES` 的既有语义一致）。

## D4 配置与 Dashboard 界面

- `core/config.py`：`get_admin_config` 新增 `stuck_silence_minutes`（默认 120，`admin.stuck_silence_minutes`）；校验段（`:384` 附近）加非负护栏。
- **新增配置项必须带 Dashboard 界面**（`fenix-new-config-needs-dashboard-ui` 约定）：
  - `core/dashboard/data.py`（`:3877` 受管键白名单）加入 `admin.stuck_silence_minutes`，使 read/write 生效；
  - `core/dashboard/static/src/pages/settings/components/SystemPanel.tsx` 增输入项（与 `admin.escalation_cooldown_minutes` 同型），`services/dashboard.ts` 的 `AdminConfig` 增字段。

## D5 兼容

- 真实 stuck（无存活 run + 无文件活跃 + 无近期 resolved 处置）仍正常产生信号；静默期仅限「处置后」，不掩真阳性。
- 不修改 stuck 主判据（`updated` 超阈值）本身；不改 baseline reset（extension）机制。
