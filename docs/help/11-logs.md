# 日志体系

Fenix 是一个基于日志运作的框架：daemon 的每次决策、Agent 的每轮对话、每条告警与处置、每次 hook 执行都落成文件，事后可逐行回放取证。本章梳理框架运行时产出的全部日志与账本文件——它们在哪、谁在写、记什么格式、如何轮转与归档。[文件与数据地图](10-artifacts.md)回答「某个东西存在哪」，本章回答「这份日志本身是什么」。

所有时间戳一律 UTC（`docs` 中不再重复标注）。

## 总览

| 类别 | 位置 | 形态 | 代表文件 |
|------|------|------|---------|
| 守护进程与进程日志 | `.fenix/logs/` | 追加（JSON 行 / 文本行） | fenixd.log、supervisor.log |
| Agent run 流 | `.fenix/runs/` | 逐行追加 JSONL | `impl-<spec>-*.jsonl` |
| 审计日志 | `.fenix/` 顶层 | append-only JSONL / 原子重写 JSON | hook_audit.jsonl、admin_alerts.json |
| 项目事件账本 | `.fenix/PROJECT_LOG.md` | Markdown 追加 | PROJECT_LOG.md |
| 子系统台账 | `.fenix/<子系统>/` | JSONL 台账 / 快照 JSON | code-review/items.jsonl、regression/last-run.json |
| 信号与状态文件 | `.fenix/` 顶层 | 一次性文件，消费即删 | scheduling_kick/、daemon_started |

最后一类**不是日志**（无历史可查，消费即删），仅作区分说明；各类日志的「写入方式与可靠性」在[文末速览表](#写入方式与可靠性速览)汇总。

## 守护进程与进程日志（.fenix/logs/）

### fenixd.log — 全框架唯一结构化运行日志

- **轮转**：单文件 10MB，保留 5 个历史（`fenixd.log.1` … `fenixd.log.5`），由 `core/logger.py` 的 RotatingFileHandler 管理。
- **格式**：每行一个 JSON 对象：

  ```json
  {"timestamp": "2026-09-14T09:37:33.594539Z", "level": "INFO", "component": "state_machine", "message": "Transition: evo-judge-rerun-stability blocked → reviewing", "context": {"updates": {"status": "reviewing"}}}
  ```

  字段：`timestamp`（UTC）、`level`（DEBUG/INFO/WARNING/ERROR）、`component`（写入组件名）、`message`、`context`（可选结构化负载）。
- **写入者**：daemon 内所有组件经统一 Logger 落盘；dashboard 服务器进程不共享 Logger 实例，由 `core/dashboard/data/log_index.py` 的 `record_project_event` 按同一格式跨进程追加。
- **两类特殊 message**（被程序消费，不是给人读的普通日志）：
  - `Transition: <spec> <from> → <to>` — SPEC 状态转移记录。打回类直写不走转移函数时时间轴上没有该行，Dashboard 时间轴按此重建流转节点。
  - `run metrics: …`（`context.metric_type == "run_metrics"`）— 每次 run 收尾的计量汇总（时长、轮次、token、cost_usd、终态、provider），由 `core/agent_runner/runner.py` 写入。
- **消费方**：AdminMonitor 规则检测、Dashboard 日志页与时间轴、`/fenix-status`、人工取证（spec 文档与事故记录里大量「fenixd.log 第 N 行」式引用）。
- **偏移索引**：`logs/.idx/fenixd.log.offsets.json` 存 64KB 块首行偏移，Dashboard 读日志尾部分片时免全文件扫描；由 `log_index.py` 全量/增量构建，原子落盘，构建失败静默降级为全扫。

### supervisor.log — 看门狗生命周期

- **格式**：纯文本行（非 JSON）：

  ```
  2026-08-26T00:54:00.551321+00:00 supervisor: daemon exited (rc=0, restart=auto)
  ```

- **写入者**：`bin/fenixd_supervisor.py` 的 `log()`，文件是唯一 sink；同一次启动重定向还把 daemon 进程的 stdout/stderr 也汇入此文件。
- **内容**：supervisor 启动/守护的 daemon 启动、退出码与重启动作、SIGKILL、熔断标记。排障「daemon 为什么重启了」先看这里，再对照 fenixd.log。
- **无轮转**，持续追加。

### 不再增长的残留文件

`dashboard.log`、`dashboard-serve.log`、`stdout.log`、`hook-restart-when-idle.log` 在现行代码中**没有任何写入点**：前两者是早期把 dashboard 进程 stdout 重定向到文件的残留，后两者分别是 daemon stdout 重定向与旧版「等空闲重启」hook 的留痕。看到它们不要再当作活跃日志排查。

## Agent run 流（.fenix/runs/）

每个 Agent run 对应一个 JSONL 转录文件，逐行记录该次运行的全部事件——这是框架的「行车记录仪」，排查「某次 run 到底做了什么」的唯一权威来源。

### 命名规则

`<前缀>-<spec>-<unix秒>[-a<尝试次>][-r<重试次>].jsonl`。前缀与 Agent 类型的对应关系由 `core/agent_runner/run_files.py` 的 `RUN_ID_AGENT_PREFIXES` 唯一维护（顺序敏感，长前缀在前）：

| 前缀 | Agent | 前缀 | Agent |
|------|-------|------|-------|
| `impl-` | 实现者（含 fast-track） | `planner-plan-` | 计划生成 |
| `verify-` | 验证者 | `planner-judge-` | 计划裁决 |
| `test-` | 测试者 | `spec-review-` | 方案评审 |
| `repair-` | 修复者 | `code-review-` | 代码审查 |
| `planner-` | 规划者（兜底） | `code-fix-` | 审查修复 |
| `admin-` | Administrator | `dispute-judge-` | 争议裁决 |

例外：自进化分析 run 无 spec 段，命名为 `evo-<unix秒>.jsonl`（`core/agent_runner/maintenance_runs.py`）。

### 行类型清单

| type | 含义 |
|------|------|
| `system` | 会话框架事件（subtype：`init` 初始化、`hook_started`/`hook_response` hook 执行） |
| `assistant` | 模型消息；`message.usage` 是逐轮 token 计量的来源 |
| `user` | CLI 回包事件（tool_result 被包裹在其内） |
| `provider_marker` | 一次 attempt 启动前写入的网关/模型链标记（spec、agent_type、provider、model、chain_index/chain_len） |
| `result` | 成功终态（num_turns、result 文本、session_id、total_cost_usd），保证是文件最后一行 |
| `run_metrics` | run 收尾计量汇总（与 fenixd.log 的 run metrics 行同源） |
| `stderr` | CLI stderr 噪声兜底行 |
| `throttled-wait` | planner 网关节流等待的保活心跳 |
| `timeout_extension` / `turn_extension` | 超时监督/轮次上限续期记录 |
| `transient_retry` | 网关瞬断退避重试 |
| `gate-blocked` | 车道门禁阻断 |
| `superseded` | 同 spec 重复派发，本次 run 作废 |
| `cancelled` / `frozen-terminated` | 人工取消 / 冻结终止（终态行） |
| `error` | 失败终态（error、exit_code），保证是文件最后一行 |
| `interrupted` | 悬空清扫补写的终态（daemon 启动期/运行期发现 run 流无终态行时补写） |

`thinking_tokens` 类事件被过滤不落盘（省约 75% 噪音）。终态判定、成本归因、活性检测（文件尾部 mtime + 末行类型）、任务完成度解析都消费此文件。

### 写入与保留

- **写入**：统一走 `run_files.py` 的 `append_run_line`，每行独立 `open("a")` + flush，依赖 O_APPEND 原子性，无跨进程锁；运行期间 Dashboard 即可实时轮询该文件画时间轴。
- **归档**：终态 run 由 daemon 每 300 秒的保留检查（`core/dashboard/data/runs.py`）移入 `runs/archive/`；归档目录按 `runs.keep`（缺省 50）上限以 mtime 最旧优先删除。SPEC 归档时其全部 run 流一并移入 archive。
- **取证夹具**：`stream_cut.py`、`gwcut.log`、`errcut.log` 是某次网关流中断事故的手工复现脚本与取样，非框架产物，代码零引用。

## 审计日志

### admin_alerts.json — 告警/信号/处置台账

- **形态**：单个 JSON 数组（非 JSONL），整体读-改-写；flock 跨进程排他 + tempfile/rename 原子替换；写回前裁剪到最近 **150 条**（`core/admin_store.py` 的 `MAX_RECORDS`）；文件损坏时改名 `.corrupt-<时间戳>` 留底并拒绝写入（fail-closed）。
- **每条字段**：`kind`（`signal` 信号 / `escalation` 升级 / `disposition` 处置）、`id`（12 位十六进制）、`created`、`handled`/`handled_at`、`severity`（critical/major/minor）、`signal_type`、`spec`、`description`、`evidence`（JSON 字符串契约）、`action_taken`、`result`、`recommended_action`。
- **写入者**：AdminMonitor 各检测器、hook 失败、provider 熔断、stale-code 检测等（经 AdminStore 统一入口）。Dashboard 告警横幅与「运维记录」页的数据源。

### dispute_audits.jsonl — 自动裁决审计

- **形态**：append-only JSONL + flock，无轮转。
- **每行字段**：`kind: "dispute-audit"`、`created`、`spec`、`trigger_run_id`、`judge_run_id`、`verdicts`（裁决 JSON 全文，逐产物 element/verdict/reasoning）、`diff`（交付物声明修正前后对照）。
- **用途**：dispute-judge 自动裁决与声明重定位的完整留痕，人工可复核、可回滚；与人工告警流（admin_alerts.json）刻意隔离。

### hook_audit.jsonl — hook 执行审计

- **形态**：append-only JSONL + flock，无轮转；Dashboard 读尾部倒序展示。
- **每行字段**：`ts`、`spec`、`event`、`from_status`、`to_status`、`hook_id`、`action`（webhook/command 等）、`scope`、`status`（success/failure）、`detail`（截断后的错误信息）、`duration_ms`。
- **用途**：SPEC 状态流转触发的 hook 是否执行、执行成败的唯一凭证。

### admin_disposition-<run_id>.json — 处置交接文件

Administrator agent 与 daemon 之间的一次性交接文件：agent 按提示词写入处置结果，daemon 读取后落盘到 admin_alerts.json 并删除该文件。目录里能看到的存量都是未被清理的历史实例。它是交接件而非日志。

## 项目事件账本（PROJECT_LOG.md）

给人看的项目大事记，Markdown 追加流，无锁无轮转。四类写入者：

| 写入内容 | 触发 | 格式 |
|----------|------|------|
| SPEC 生命周期事件（完成、bug 打回、调度派生等） | 各状态节点 | `- [YYYY-MM-DD HH:MM UTC] 🐛/✅ …` 单行 bullet |
| Blocker 巡检报告 | 巡检发现阻塞（1 小时节流） | `### ⚠️ Blocker Report — <时间戳>` 小节 + 逐 spec bullet |
| 每日统计报告 | 每日调度 | `---` 分隔的完整报告段 |
| task-reflow 回炉留痕 | 任务回炉重排 | `- [时间戳] 回炉(task-reflow, 来源=…)：…` |

注意它是**追加流不是状态源**：查 SPEC 当前状态以 STATE.md 为准，这里只回答「什么时候发生过什么」。

## 子系统台账

### cost/ — 运维车道 token 对账

`code_review_tokens.json` 与 `self_review_tokens.json`：无 spec 维度的运维车道（代码审查、每日自省、自进化分析）的逐 run token 成本记录。格式 `{"date": …, "runs": [{"agent_type", "date", "timestamp", "input_tokens", "output_tokens", "cost_usd"}…]}`，flock 内读-改-写整体替换。有 spec 归属的 run 成本不在这里（在 run 流与 STATE.md 侧）。

### code-review/ — 代码审查工作区

| 文件 | 角色 |
|------|------|
| `items.jsonl` | 审查发现台账（权威存储）：`item_id`、`file`/`line`、`severity`、`category`、`title`/`description`/`suggestion`、`fingerprint`（去重指纹）、`status`（`open` / `in_spec` / `resolved` / `ignored`——`fixing` 是批修复的阶段而非条目态）、`first_seen_at`/`last_seen_at`、`review_id`。按 fingerprint 去重 upsert，flock + 原子替换 |
| `manifest-<run_id>.json` | 派发前框架写的审查范围声明（scope、files[]、window_start），审查进度 total 的权威来源 |
| `out-<run_id>.jsonl` | 审查 agent 逐文件追加的发现流（增量落盘），run 结束后读取并入 items.jsonl 台账 |
| `out-<run_id>-b<N>.jsonl` | code-fix 批内并行的修复分片产物（每批一个分片，N 数值升序；非 `-b<正整数>` 后缀的同形文件不被消费，`core/code_review.py` 的 `shard_paths` 是分片发现唯一入口） |
| `fix-progress.json` | 自动修复批次进度（done/total）；条级进度与 startup_stage 由读侧合成 |
| `fix-deferred.json` | WIP defer 台账（worktree/branch/tip_sha/item_ids/fixed_ids/defer_count/first_deferred_at/last_overlap 八字段；90 分钟 / 6 次双门预算） |
| `fix-failed.json` | 批失败档案（fail_count 预算，达 3 次一次性告警转人工；人工处置后 `core.code_fix.release_failed_batch` 解除） |
| `code_review_request_result.json` | 手动触发受理回链凭据（`started` / `dropped` / `failed` 三态 + 受理窗口标记） |
| `batch_N.json` | agent 自发切批的中间产物，非契约产物，框架不读 |

同层的 `code_review_state.json`（`last_run_date`）是调度防重状态，不是日志。

### evolution/ — 自进化台账

`items.jsonl`（条目状态机，按 id 幂等更新）、`state.json`（逐项目分析水位）、`drafts/<id>/`（SPEC 草稿暂存）——语义详见[文件与数据地图](10-artifacts.md#fenixevolution-自进化产物gitignored非交付物)。

### regression/ — 全量回归产物

| 文件 | 角色 |
|------|------|
| `junit.xml` | 回归命令自己产出的 JUnit XML（路径由 verify.yaml 的 `regression.output` 声明），框架起跑前删除旧文件、结束后解析 |
| `junit.xml.log` | 回归子进程 stdout 落盘；运行中框架 tail 它提取 pytest 进度百分比 |
| `last-run.json` | 最近一次回归结果**单快照**（覆盖式，不留历史）：status、cmd、output、起止时间、total/passed/failed/errors/skipped、failures[]、long_tests[] |
| `state.json` | `last_run_date` 同自然日防重状态 |

语义详见[文件与数据地图](10-artifacts.md#fenixregression-全量回归产物gitignored非交付物)。

### 验证车道产物（verify-progress/ 与 verify-serving/）

验证进度（`<spec>.json`）、场景报告（`report.json`）、逐轮 token（`tokens.json`）、judge 归因（`scenario-attribution.json`）、被测实例登记与启动日志（`verify-serving/servers.json`、`<spec>-boot.log`，探活失败时读尾 2KB 溯因）——这些归[验证体系](05-verification.md)章节管辖，此处不展开。

## 写入方式与可靠性速览

| 文件 | 写入方式 | 锁 / 轮转 / 保留 |
|------|---------|-----------------|
| fenixd.log | 追加（JSON 行） | RotatingFileHandler 10MB×5；dashboard 跨进程 O_APPEND |
| supervisor.log | 追加（文本行） | 无轮转 |
| runs/*.jsonl | 逐行 open+flush 追加 | O_APPEND 原子性；终态移 archive + `runs.keep`（缺省 50）上限 |
| hook_audit.jsonl / dispute_audits.jsonl | append-only | flock（`.lock` 文件），无轮转 |
| admin_alerts.json | 整体读-改-写（原子替换） | flock + 裁剪最近 150 条 + 损坏留底 |
| STATE.md 及各 *.json 状态 | tempfile + rename 原子重写 | 各自 flock；`.tmp` 残留即崩溃痕迹 |
| PROJECT_LOG.md | Markdown 追加 | 无锁、无轮转 |
| cost/、code-review/、evolution/ 台账 | 读-改-写原子替换（JSONL 台账为整体重写） | 各自 flock |

设计取向：**日志类只追加**（保历史、可回放），**状态类原子重写**（保一致、可恢复），两者不混。看到 `.tmp`、`.lock`、`.corrupt-*` 伴生文件即对应机制的痕迹，不要手工删除正在使用的 `.lock`。

## 与信号文件的区分

以下文件长得像日志但**只承载一次信号，消费即删或随状态覆盖**，无历史可查：`scheduling_kick/<spec>.json`（即时派发唤醒）、`admin_invoke_request.json`（Admin 唤起）、`regression_request.json`（手动回归触发）、`code_fix_request.json`（手动自动修复授权）、`spec_delete_request.json`（SPEC 删除异步受理）、`restart_request.json`、`daemon_started`（最近启动时刻）、`daemon.lock`/`lifecycle.lock`/`full-suite.lock`（互斥锁）、`recovery_watch.json`、`self_review_state.json`/`code_review_state.json`/`regression/state.json`（调度防重水位）。它们的语义见[文件与数据地图](10-artifacts.md)。

## 排障入口速查

| 要回答的问题 | 看哪里 |
|--------------|--------|
| daemon/supervisor 为什么重启 | supervisor.log，对照 fenixd.log 同时刻 ERROR |
| 某 SPEC 状态为什么变了 | fenixd.log 搜 `Transition: <spec>`（时间轴同源） |
| 某次 run 卡在哪一步 / 花了多少 token | `.fenix/runs/<run_id>.jsonl` 尾部事件 + `run_metrics` 行 |
| 告警为什么触发、自动处置做了什么 | admin_alerts.json 对应 id 条目（evidence + action_taken） |
| hook 有没有执行成功 | hook_audit.jsonl 尾部 |
| 自动裁决是否可靠、改了什么 | dispute_audits.jsonl 对应 judge_run_id 行 |
| 历史上某天发生过什么 | PROJECT_LOG.md 时间线（精确状态以 STATE.md 为准） |
| 运维车道花了多少钱 | cost/*.json |

现象→根因→处置的完整手册见 [FAQ 与故障排查](12-faq.md)。

## 相关文档

- [文件与数据地图](10-artifacts.md) — 全部文件的定位地图
- [调度与治理规则](06-governance.md) — 告警分级与处置语义（admin_alerts.json 的上游）
- [验证体系](05-verification.md) — 验证产物语义
- [FAQ 与故障排查](12-faq.md) — 按现象直连处置
