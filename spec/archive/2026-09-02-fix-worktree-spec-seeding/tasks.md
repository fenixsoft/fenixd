## 1. worktree-spec-seeding（核心播种）

- [x] 1.1 `core/worktree_manager.py::create` 在 `git worktree add` 成功后，实现 SPEC 播种：当 `openspec/changes/<spec>/` 在主工作树存在而 worktree 内缺失时，复制进 worktree 并 `git add` + `git commit`（`[fenix] spec: <spec-name>`）到隔离分支；主工作树无该目录或 worktree 已含则跳过
- [x] 1.2 播种异常容错：复制/提交失败仅记录日志、不阻塞 worktree 创建流程（worktree 仍返回，实现 Agent 走主仓库兜底路径）
- [x] 1.3 手工验证：对未提交 SPEC 创建实现 worktree，确认 worktree 内含完整 SPEC 目录、分支含 `[fenix] spec:` 提交、`main` 工作树不被污染
- [x] 1.4 既有测试回归：`python3 -m pytest tests/ -v` 全绿

## 2. worktree-result-readback（结果与进度读取）

- [x] 2.1 `core/pm_engine.py`：实现 Agent 结果读取改为「活跃 implementer worktree（`impl-<spec>-*`，取最新）优先、项目根兜底」；仅影响 implementer 结果，verifier/planner 读取位置不变
- [x] 2.2 `bin/statusline.py` 与 `core/dashboard/data.py`：tasks.md 进度解析对 implementing 的 SPEC 优先从活跃 implementer worktree 读取，worktree 缺失回退主仓库；非 implementing 一律读主仓库
- [x] 2.3 `/fenix-status` skill：tasks 进度解析同步上述 worktree 优先逻辑
- [x] 2.4 验证：构造 worktree 内含结果的场景确认读取命中；worktree 缺失场景确认回退；`pytest` 全绿

## 3. daemon-watcher-startup（派发线程化）

- [x] 3.1 `core/pm_engine.py`：将 `_process_queue` 的 Agent 执行改为每个运行一个 worker 线程（`threading.Thread`），派发后立即返回；并发上限由 `agents.max_concurrent` 约束（`_active_runs` 计数守卫），Agent 完成后在 `finally` 中释放计数并继续处理队列
- [x] 3.2 `_run_queue` / `_active_runs` 加 `threading.Lock` 保护；确认既有防重入守卫（`_handling_events` / `_spec_locks`）在线程化下语义不变；STATE.md 写入沿用文件锁
- [x] 3.3 `fenixd.py`：确认 `full_scan` 派发后能继续 `event_bus.start()`；若需调整启动顺序使 watcher 更早就绪，做最小改动
- [x] 3.4 验证：daemon 启动时存在可派发 SPEC → 进程线程数 ≥3、watcher 感知后续 STATE.md 变更；两个待运行 SPEC 并发执行（`_active_runs==2`）；`pytest` 全绿

## 4. 端到端验证

- [x] 4.1 观察 `add-fenix-dashboard` 后续实现/验证阶段正常推进，无回归；确认新 SPEC 可在 daemon 运行期间被调度（不再停在 drafted）
- [x] 4.2 创建下一个新 SPEC（或临时最小 SPEC）确认：实现 Agent 在 worktree 内工作、变更落在 `fenix/<spec>` 分支而非 main、进度与结果展示一致
