## Context

`worktree_manager.create()` 用 `git worktree add -b <branch> <path> HEAD` 从分支 HEAD 创建隔离工作区。SPEC 源文件（`spec/changes/<spec>/`）由 `/fenix-new` 写入主工作树且未提交，因此 worktree 中不存在。实测（`add-fenix-dashboard`）实现 Agent 找不到 SPEC 后回落到主仓库直接编辑并 `git commit` 到 `main`（`49c87de`），绕过隔离与审批门禁。

另外 daemon 读取实现结果的位置固定为主仓库根：`pm_engine.py` 的 `.fenix-run-result.json` 读取路径为 `self.project_root / ".fenix-run-result.json"`。任务进度（`tasks.md`）同样由各消费方从主仓库 `spec/changes/<spec>/tasks.md` 读取。

## Goals / Non-Goals

**Goals:**
- 恢复实现 Agent 的 worktree 隔离：SPEC 源文件对实现 Agent 可见，变更落在 `fenix/<spec>` 分支。
- daemon 与进度展示读取实现结果/任务进度时与实际实现位置一致（worktree 优先，主仓库兜底）。
- 对既有 SPEC（`add-fenix-dashboard`）与未使用该机制的异常场景保持兼容，不阻塞现有推进。

**Non-Goals:**
- 不改 SPEC 文件格式、不改 StateMachine / EventBus 语义。
- 不做「自动合并 worktree 分支回 main」——审批合并仍由 `/fenix-approve` 人工门禁负责。
- 不重构 worktree_manager 的清理/锁机制。

## Decisions

### D1. 播种方式：复制 SPEC 目录进 worktree 并提交到隔离分支

**决策**：在 `worktree_manager.create` 完成 `git worktree add` 后，检查 `spec/changes/<spec>/` 是否在主工作树存在且 worktree 内缺失；若是，则把该目录复制进 worktree，`git add` + `git commit`（提交信息 `[fenix] spec: <spec-name>`）到新分支。实现 Agent 随后在 worktree 内读写 SPEC、标记 tasks、写 `.fenix-run-result.json`，全部变更随分支走。

**理由**：使隔离分支自包含（SPEC + 实现同分支），实现 Agent 无需任何额外 add-dir 也能在 cwd（worktree）内完成全部工作；分支内容与 `/fenix-approve` 推送内容一致。
**备选**：
- 仅 `--add-dir` 注入主仓库 SPEC 路径——实现 Agent 可读但 tasks.md 标记/结果仍落在 worktree，结果读取链路仍断，且读写主仓库与 worktree 两处易混乱，弃用。
- 先在 main 提交 SPEC 再调度——改变 `/fenix-new` 工作流，需额外提交行为，弃用。

### D2. 结果读取：pm_engine 定位活跃 implementer worktree 读取 `.fenix-run-result.json`

**决策**：`pm_engine` 读取实现结果时，改为「worktree 优先、主仓库兜底」：给定 SPEC，查询其活跃 implementer worktree 路径（`worktree_manager` 提供查询，或按 `impl-<spec>-*` 目录名匹配），若该 worktree 存在 `.fenix-run-result.json` 则读取之；否则回退 `self.project_root / ".fenix-run-result.json"`。

**理由**：播种后实现 Agent 的结果文件天然位于 worktree；回退保证旧流程（结果写在主仓库）或异常场景不破坏。
**注意**：`.fenix-run-result.json` 当前由 `_read_verifier_result` 统一读取（verifier/planner 共用）。本能力只针对 **implementer 结果读取** 调整来源；verifier/planner 的结果仍按现状（主仓库）读取，避免扩大影响面。

### D3. 进度展示：tasks.md 对 implementing 的 SPEC 从 worktree 读取

**决策**：`bin/statusline.py` 与 `core/dashboard/data.py` 的任务进度解析，对状态为 `implementing` 的 SPEC 优先从活跃 implementer worktree 的 `spec/changes/<spec>/tasks.md` 读取（worktree 缺失回退主仓库）；非 implementing 状态一律读主仓库。`/fenix-status` skill 的 tasks 解析同理。

**理由**：播种后实现 Agent 标记 tasks.md 发生在 worktree；若进度展示仍读主仓库，会一直显示「无进度」。回退保证 testing/verified/done 阶段（worktree 已清理）仍读主仓库分支的最新进度。

### D4. Agent 派发线程化，保证 watcher 始终运行

**决策**：将 `pm_engine._process_queue` 的 Agent 执行改为**每个运行一个 worker 线程**（`threading.Thread`），并发上限由 `agents.max_concurrent` 约束（信号量/计数守卫）；派发调用（`handle_event` → `_process_queue`）在启动线程后立即返回，不再阻塞调用线程。`FenixDaemon.start()` 保持「先 `full_scan` 再 `event_bus.start()`」的顺序也可安全执行——因为 `full_scan` 派发 Agent 后立即返回，`event_bus.start()` 随之启动 watcher/scanner 线程。`_run_queue` 与 `_active_runs` 的读写加 `threading.Lock` 保护；Agent 完成后在 `finally` 中释放计数并继续处理队列。STATE.md 的写入沿用 `StateMachine.write_all` 既有的 `fcntl.flock` 文件锁，天然线程安全。

**理由**：这是「watcher 不启动」的根治——任何路径（启动 full_scan、watcher 事件、periodic scan）派发 Agent 都不再阻塞，事件循环持续运转；同时让 `max_concurrent` 从「名义值」变成「实际并发」，多 SPEC 可并行实现/验证。
**备选**：
- 仅重排 `start()` 让 watcher 先启动——能缓解启动阻塞，但 watcher 线程内派发 Agent 仍会阻塞该线程、且并发上限名存实亡，弃用。
- 使用 asyncio + 子进程异步——改动面大、与现有同步 `subprocess.run` 及重试逻辑冲突，弃用。
- 不处理——当前行为（启动即派发则 watcher 永不启动、新 SPEC 无法调度）在自托管场景已被实证，不可接受。

## Risks / Trade-offs

- **[播种引入分支上的 SPEC 提交]** → 分支自包含是预期结果；`/fenix-approve` 推送时 SPEC 与实现一同上主分支，符合 OpenSpec「change = spec + 实现」语义。若不需要，可在审批时过滤。
- **[worktree 定位不准确]** → 用 run_id 前缀（`impl-<spec>-`）匹配 + 存在性校验，找不到即回退主仓库，不抛错。
- **[多 attempt 残留多个 worktree]** → 只取最新/唯一活跃 worktree；旧 worktree 由既有 cleanup 机制清理。
- **[回退路径与旧行为兼容]** → 回退路径就是现状实现（读主仓库根），零风险。
- **[线程化引入竞态]** → `_run_queue` / `_active_runs` 全程加锁；Agent 结果处理与状态推进仍串行（同一时刻仅一个线程推进状态机结果），STATE.md 写入由文件锁保护。
- **[线程化改变调度时序]** → Agent 完成后的「verifier 立即入队」等既有时序保持（在 worker 线程的 finally 中继续处理队列）；`_active_runs` 计数精确维护，避免超发。
- **[并发下重复调度同一 SPEC]** → 沿用既有 `_spec_locks` / `_handling_events` 防重入；线程化不改变这些守卫的语义。

## Migration Plan

1. **阶段 A（worktree-spec-seeding）**：`worktree_manager.create` 播种 + 分支提交；用手工创建模拟 worktree 验证播种产物与分支自包含。
2. **阶段 B（worktree-result-readback）**：`pm_engine` 实现结果 worktree 优先读取；`statusline` / `dashboard data` / `fenix-status` tasks 进度 worktree 优先读取。
3. **验证**：运行既有测试；确认 `add-fenix-dashboard` 后续实现/验证阶段仍正常推进；观察下一个新 SPEC 的实现变更是否落在 `fenix/<spec>` 分支而非 main。

## Open Questions

- 播种提交是否需要在 `/fenix-approve` 审批时合并进主分支（当前按「推送分支即可」处理，SPEC 与实现同分支）。
- 是否需要把播种逻辑同时应用于 verifier worktree（验证 Agent 目前从主仓库读 SPEC 似乎可用，暂不播种，观察）。
