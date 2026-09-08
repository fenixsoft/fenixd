# add-runtime-run-sweeper 设计

## Context

2026-09-06 事故取证（详见 fenixd.log / supervisor.log / 记忆 fenixd-dangling-runs-daemon-sigkill-rootcause）：两次 daemon 重启（09-05 22:39:12Z、23:21:49Z）中，daemon 进入 drain（当时窗口 1800s）等待在飞 run，supervisor 60s 窗口到期 SIGKILL（22:40:12.445Z / 23:22:49Z），`wait_for_running_agents` 的 interrupted 标记写入（位于 drain 完成之后）永远未执行。三个 in-flight run 的监督线程随 daemon 进程死亡，jsonl 永久失去终态写入者。启动清扫（fix-daemon-lifecycle-races 2.1/2.2，dd563cde）能收口但仅在 daemon 启动期执行；事故中三次中间 daemon 启动均运行早于该提交的代码，悬空持续 12.3h。

监督机制（`_run_claude` 轮询环 + `_supervision_deadline_action`）是 in-process 的：宿主线程死亡即失效，无 out-of-band 兜底。残留缺口两个：
1. **进程级**：daemon 非优雅死亡（SIGKILL/OOM/断电）→ 在飞 run 悬空至下次重启；悬空期统计失真、孤儿 claude 持锁阻断重派（事故中多烧一次实现预算 used=2/6）。
2. **线程级**：`_run_claude` 轮询环未预期异常 → finally 只写 result/cancelled（runner.py:2498-2512），无 rc≠0/超时路径时 jsonl 悬空且异常归因丢失。

## Goals / Non-Goals

**Goals**
- daemon 存活期间，悬空 run 最坏检测延迟 ≈ 阈值 + 扫描周期（1800s + 30m ≈ 60min），对比事故 12.3h
- run 线程级异常即刻显式终态 + 异常归因落盘
- 零新增配置项、零前端、零新增接线参数

**Non-Goals**
- STATE.md 级状态回迁（补终态后由既有 recovery/full_scan 机器消费事实）
- 孤儿 claude 进程击杀（持锁释放已有 `no live process + stream idle >120s` 机制）
- admin 人工告警接入（v1 仅 WARNING 日志，避免告警噪音机器介入）
- 「清扫抬僵尸 mtime」读侧残留的治本（find_impl_run_file 优先 STATE implementer_run，另列修复方向，不在本变更代劳）

## Decisions

### D1 三重判据（AND，缺一不扫）

```
① run_id ∉ _running_agents 注册表   → 在飞保护（权威源；键=文件 stem，runner.py:2317 与文件名同源）
② mtime 停更 ≥ 1800s               → 流停保护（任何存活写入者都会刷新 mtime；先短路免读文件）
③ 尾部无终态事件（RUN_TERMINAL_EVENT_TYPES）
```

**安全性论证**：result 终态只能由 run 线程的 finally 块写出；线程不在注册表 = 该 run 的 result 已不可达（转写者死了，无论管道对端 claude 子进程死活）。补 interrupted 不销毁可恢复数据，只把「框架已知的死亡」显式化。

**既有窗口自然覆盖**：派发瞬间（provider_marker 落盘→Popen→注册表登记，毫秒级）与 finally 内先 pop 后写 result（µs 级）均因 mtime 新鲜被跳过；「主线程崩但读线程还活着继续写」的窗口同理延迟到流冷后处理。

### D2 阈值常量化（用户决策 2026-09-08）

`RUNTIME_SWEEP_IDLE_SECONDS = 1800`，落 liveness.py 常量区（`LIVE_ATTEMPT_STREAM_WINDOW_SECONDS` 旁）。不引入配置项即不触发「新增配置必须带 Dashboard UI」约定；需要时可再晋升。

### D3 落点与接线（零新增参数）

- 判定/补写逻辑：`LivenessSupervisor.sweep_dangling_runs()`（与启动清扫同文件，共享 `_file_has_terminal_event` helper 与 `RUN_TERMINAL_EVENT_TYPES`）
- 驱动：`event_bus._periodic_scan_loop` 每轮 `full_scan()` **前**调用 `self.pm_engine.agent_runner.sweep_dangling_runs()`——event_bus 已持 pm_engine、pm_engine 已持 agent_runner（engine.py:91），无新构造参数；先扫后 scan 使当轮 full_scan 看到最新终态事实
- 门面委托：AgentRunner 必须补一行委托（组件/门面漏改教训：billing WIP admin 解包事故）
- 缓存：`_terminal_verified: set[str]`（stem），确认终态或已补写即入缓存；在飞文件不入缓存；首轮全量建缓存，此后增量

### D4 源头修复并入（用户决策 2026-09-08）

轮询环加 `except Exception as e:` → `append_run_error(run_file, f"run thread crashed: {e!r}", returncode)` → 原样 `raise`。except 先于 finally 执行，error 行落为文件末行（崩溃场景无 result/cancelled 可写）；re-raise 保持 attempt 循环预算/STATE 语义不变。清扫器退居进程级死亡的唯一兜底。

### D5 补写产物

`{"type": "interrupted", "reason": "runtime terminal-state sweep", "idle_seconds": <int>, "timestamp": "<UTC ISO8601>"}`，经 `append_run_line` O_APPEND 原子追加。reason 与启动清扫构成 `terminal-state sweep` 同族后缀，时间轴/日志可辨识来源。补写动作出 WARNING（component=agent_runner，含 run_id 列表），与启动清扫告警格式对齐。

## Risks / Trade-offs

- **mtime 僵尸抬升频率放大**：补写即刷新 mtime，运行期化后裸 mtime 读侧（find_impl_run_file 排序、run_progress、verified 门禁）被短暂污染的频率从「每次启动」变「每次补写」。`_stream_recent`（120s 窗口）自愈；排序类读侧依赖已记录的读者侧修复方向。清扫器不改写读者侧。
- **注册表内卡死线程盲区**：run 线程卡死在轮询环外的同步调用 → 注册表条目在 → 清扫器不碰。与监督 deadline 同盲区，无法区分卡死与慢，接受。
- **首轮全量扫描成本**：daemon 启动后首个清扫周期需读全部无终态文件建缓存；runs 目录文件量级小（事故期 133 specs 全量 full_scan 同量级），可接受。
- **清扫与关闭竞态**：`wait_for_running_agents` 关闭写标记时若清扫器并发补写，O_APPEND 单行原子性保证 JSONL 不损；双 interrupted 无害（终态幂等）。

## Migration Plan

无迁移：纯增量机制，无配置、无数据格式变化；启动清扫行为保持不变（共享 helper 重构后回归测试覆盖）。

## Open Questions

无（设计决策均已由用户确认：连带修源头、阈值常量化、fast-track、凌晨两点后调度）。
