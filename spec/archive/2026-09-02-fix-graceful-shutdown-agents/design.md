# Design: fix-graceful-shutdown-agents

## Context

daemon 优雅退出（`fenixd.py:235` 起）执行 `admin_thread.join(5s)` → `event_bus.stop()` → `agent_runner.wait_for_running_agents(timeout=300)` → worktree 清理。其中 `wait_for_running_agents` 对每个在跑 agent 依次 `wait(remaining)`，最多 300s/agent（agent_runner.py:1059-1073）。

外部 supervisor（frac66 `bin/fenixd_supervisor.py`）检测 `.fenix/restart_request` 后 SIGTERM daemon，**固定 60s 后超时 SIGKILL**（fenixd_supervisor.py:81-85）。

两者叠加的必然结果：**只要 SIGTERM 时存在未完成 agent，daemon 输出的 run 结果超过 60s 就会被 kill -9。** supervisor.log 累计出现 5 次 SIGKILL（09:12/09:21/11:01/13:11/15:24），3 次优雅退出（10:39/10:56/11:07）则发生在无 agent 在跑的时刻。

被打断的 admin agent 不留下任何 run 最终结果 → disposition 长期 pending → AdminMonitor 孤儿检测（admin_monitor.py:369-440）升级为"疑似 daemon 崩溃"。improve-dashboard-sections 事件即此链路的实证：同一 run（1787749459）被升级 3 次（13:21/14:47/17:34），直到 73f0fb6 加入"升级即终结"才止血。

## Goals

- daemon 优雅退出时，在跑 agent 无论是否完成，重启过程总耗时压到秒级（≪ supervisor 60s 窗口），不再触发 SIGKILL。
- 被打断的 agent run 留下可识别证据（interrupted 标记），孤儿检测将"已知中断"与"疑似崩溃"区分，杜绝误报。
- 不改变 supervisor 行为、不新增配置项、不引入新依赖。

## Non-Goals

- 不修"agent 真卡死时如何完成结果"（那是运行态超时问题，另有 stuck 信号覆盖）。
- 不给 run 文件保留策略加长（interrupted 标记随 run 正常生命周期被 prune 属可接受的保守降级）。
- 不做 daemon 崩溃瞬间（连 interrupted 都写不出）的恢复——此场景维持现有"疑似崩溃升级"兜底。

## Decisions

### D1: 改 daemon 关闭语义，而非扩展 supervisor 窗口

**选择**：重写 `wait_for_running_agents` 为 terminate 流程——SIGTERM 全部在跑 agent → 写 interrupted 标记 → ≤10s 缓冲 → 未退出者 SIGKILL。

**备选 A（否决）**：supervisor 窗口 60s → 300s+。缺点：a) 重启可长达 5+ 分钟且不可控（每 agent 300s 串联叠加）；b) agent 若真卡死，等待无意义；c) 需同时维护两处窗口常量，漂移风险仍在。**备选 B（否决）**：直接 SIGKILL 不缓冲。缺点：claude CLI 无收尾机会，流式输出可能截断在 JSONL 行中间；且 SIGKILL 语义与"崩溃"不可区分，孤儿检测无法降噪。

### D2: 顺序 = SIGTERM 全部 → 写标记 → 等待 ≤10s → SIGKILL 兜底

- 先 SIGTERM 后写标记：SIGTERM 让 claude 开始收尾，标记由 daemon 侧同步写入，互不阻塞。
- 10s 缓冲取 claude 收尾所需量级（关闭会话、flush 输出缓冲），用常量 `AGENT_TERMINATE_GRACE_SECONDS = 10` 便于测试注入。
- 写标记与 reader 线程并发 append 同一 run 文件：均以 append 模式单行写入（append_run_line，agent_runner.py:93-101），单行原子追加不会交错破坏 JSONL 结构。
- 边界安全：shutdown 时 `_running_agents` 中只含未完成 agent（完成的已 finalize 并移除），写标记不会误标已完成 run。

### D3: interrupted 标记 = run 文件末行 `{"type": "interrupted", "reason": "daemon shutdown", "by": "agent_runner"}`

- 选 run 文件而非 admin_state：run 文件对所有 agent 类型（impl/verify/planner/admin）统一生效，admin_state 只覆盖 admin 处置，且 run 文件天然带进程生命周期语义。
- 下游读取兼容：JSONL 追加一条不影响既有解析（逐行读入仍按 type 分发）。

### D4: 孤儿检测前置 run 文件判定

`_recover_orphaned_dispositions` 对超时 pending 增加一步：读取 `<runs_dir>/<admin_run_id>.jsonl`，若含 interrupted 类型记录 → 追加 final disposition（`status=interrupted`）终结该 run 且**不升级**；文件不存在或读不到 interrupted → 维持现有升级兜底。

- 复用 73f0fb6 的"终结即 final"机制：追加非 pending 记录后，`by_run` 分组 final=True，下轮跳过，天然去重。
- run 文件可被 prune 清理（78xxxx 文件保留策略）：文件不存在按"无证据"处理 → 升级。对齐"宁可多告警、不漏告警"的保守方向。

### D5: 多 agent 并行 terminate

不沿用现有"逐个 wait"的串行循环；先统一 SIGTERM+标记（O(n)），再统一轮询 ≤10s，最后 kill 存活者。避免 N 个 agent 串行叠加超出 60s 窗口。

## Risks / Trade-offs

- [SIGKILL 仍发生在 interrupted 标记写入之前（daemon 秒级窗口内被外部强杀）] → 该 run 无标记，孤儿检测按疑似崩溃升级兜底。已知且保守，可接受。
- [10s 缓冲内 agent 输出不完整] → run 以 interrupted 标注，任何下游不得视其为 success；stuck/失败信号自然覆盖后续。
- [run 文件被 prune，孤儿检测读不到标记 → 误升级] → 保守方向，可接受；dashboard 上人工可区分（升级文本含"疑似 daemon 崩溃"）。
- [shutdown 其他环节（worktree 清理等）拖慢总时长] → 新 wait 恒 ≤~10s，总关闭时长预计 <30s，远低于 60s 窗口；由测试覆盖整链路时长阈值。

## Migration Plan

无数据迁移。发布后 daemon 重启即生效：新终止的 run 带 interrupted 标记，旧孤儿按原有逻辑处理（不追溯）。

## Open Questions

- interrupted 标记是否需要在 Web Dashboard 的 run 详情上做视觉区分（如"已中断"标签）——不影响本次行为正确性，可作为后续增强，本 SPEC 不包含。