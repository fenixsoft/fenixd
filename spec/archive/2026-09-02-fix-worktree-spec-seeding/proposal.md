## Why

两个同属「SPEC 调度与隔离正确性」的框架缺陷：

1. **隔离被绕过**：实现 Agent 的隔离 worktree 是从分支 HEAD 创建的（`git worktree add -b <branch> <path> HEAD`），而 SPEC 源文件（`spec/changes/<spec>/` 下的 proposal/design/specs/tasks）由 `/fenix-new` 写进主工作树且**未提交**。因此 worktree 中不存在 SPEC 文件，实现 Agent 在 worktree 内找不到要实现的 SPEC，只能回落到主仓库直接编辑并提交（已观察到 `add-fenix-dashboard` 的实现被直接提交到 `main` 的 `49c87de`）。这完全绕过了「worktree 隔离 + 分支审批门禁」，使 `/fenix-approve` 对该批提交失效。

2. **调度系统启动被阻塞**：`FenixDaemon.start()` 先执行 `event_bus.full_scan()` 再执行 `event_bus.start()`（启动 watcher 线程）。而 `_process_queue` **在主线程内联运行** Agent（`subprocess.run` 阻塞直到实现/验证结束）。当启动时存在可派发的 SPEC，`full_scan` 同步派发并阻塞主线程（实测线程数=1，watcher 从未启动），导致之后所有 STATE.md 变更（新增 SPEC、状态转换）都不被感知——新 SPEC 永远停在 drafted，无法调度。

## What Changes

- **播种 SPEC 源文件到隔离 worktree**（`core/worktree_manager.py`）：创建 worktree 后，若某 SPEC 的 `spec/changes/<spec>/` 在主工作树存在但 worktree 缺失，将其复制进 worktree 并提交到隔离分支，使分支自包含（SPEC + 实现同分支，随 `/fenix-approve` 一起审批推送）。
- **daemon 从 worktree 读取实现结果**（`core/pm_engine.py`）：实现 Agent 的 `.fenix-run-result.json` 现改在 worktree 内产生；daemon 读取该结果时，对 implementing 的 SPEC 定位其活跃 implementer worktree 并从其中读取（worktree 不存在时回退主仓库根，保持兼容）。
- **进度展示从 worktree 读取任务进度**（`bin/statusline.py`、`core/dashboard/data.py` 及 `/fenix-status` 相关解析）：对 implementing 的 SPEC，其 `tasks.md` 勾选状态从该 SPEC 的活跃 implementer worktree 读取（worktree 不存在时回退主仓库），保证进度显示与实现实际位置一致。
- **daemon 启动不阻塞 watcher**（`core/pm_engine.py` + `fenixd.py`）：Agent 派发放入独立 worker 线程（并发上限 `max_concurrent`），派发不再阻塞调用线程；`event_bus.start()` 在初始扫描派发 Agent 时也能正常启动 watcher/scanner 线程，使新 SPEC 与状态变更持续被感知。
- **共享状态线程安全**（`core/pm_engine.py`）：`_run_queue` / `_active_runs` 等跨线程访问加锁保护，STATE.md 写入沿用既有文件锁。
- 不改动 StateMachine / EventBus / SPEC 格式，不改动验证产物格式。

## Capabilities

### New Capabilities
- `worktree-spec-seeding`: 创建实现 worktree 时，把主工作树中未提交的 SPEC 源文件播种进 worktree 并提交到隔离分支，使实现 Agent 全程在 worktree 内工作、变更落在分支上。
- `worktree-result-readback`: daemon 与进度展示从实现 worktree 读取实现结果（`.fenix-run-result.json`）与任务进度（`tasks.md`），worktree 缺失时回退主仓库，恢复隔离且不破坏既有读取路径。
- `daemon-watcher-startup`: daemon 启动/运行期间，Agent 派发异步化（worker 线程 + `max_concurrent` 并发上限），派发不阻塞事件处理线程，EventBus watcher 始终运行，新 SPEC 与状态变更持续被调度。

### Modified Capabilities
<!-- 无既有 spec，暂无修改 -->

## Impact

- **核心代码**：`core/worktree_manager.py`（create 中播种逻辑）、`core/pm_engine.py`（实现结果读取位置 + 派发线程化 + 共享状态加锁）、`fenixd.py`（启动顺序，如需）。
- **进度消费方**：`bin/statusline.py`、`core/dashboard/data.py`（任务进度解析）、`skills/fenix-status/SKILL.md`（tasks 解析）。
- **行为变化**：此后实现 Agent 不再直接改 `main`；实现与 SPEC 落在 `fenix/<spec>` 分支，审批推送时一并携带；多 Agent 可真正按 `max_concurrent` 并发执行；daemon 全程保持事件感知。
- **兼容性**：主仓库未初始化 git、或无活跃 worktree 等异常场景下回退旧行为；Agent 结果/状态推进语义不变。
- **无新依赖**：仅用 git 与标准库。
