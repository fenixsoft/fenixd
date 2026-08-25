# Tasks: 修复 implementer 未在 worktree 隔离工作

## 1. implementer 真正在 worktree 中工作

- [x] 1.1 在 `core/agent_runner.py::_run_claude` 的 `subprocess.Popen` 传入 `cwd=str(cwd)`（worktree 路径），使 claude 子进程工作目录与相对路径解析落在 worktree；保留 `--add-dir` 双保险
- [x] 1.2 验证：运行中 implementer 的 run 记录 init 事件 `cwd` 等于 worktree 路径；运行期间主树 `git status` 干净、worktree `git status` 出现实现者提交（单元测试验证 Popen cwd 参数）

## 2. worktree 分支合并回主树

- [x] 2.1 在 `worktree_manager` 暴露当前活动 worktree 的分支名查询（或让 `_execute_agent`/`pm_engine` 能拿到与 `create()` 一致的分支名 `fenix/<spec>-<ts>`），避免硬编码耦合
- [x] 2.2 新增 merge-back 逻辑：implementer 成功运行后、推进 `implemented` 前，在主树执行 `git merge --no-ff <branch>`（含 `git merge-base --is-ancestor` 幂等检查）；合并失败标记 STATE.md `error`、不推进状态，交由现有重试机制
- [x] 2.3 在 `core/pm_engine.py::_run_agent_worker` 的 implementer 成功路径接入 merge-back，成功后清理 worktree 并正常推进 `implemented` / 排队 verifier

## 3. 读取路径对齐

- [x] 3.1 核对 `core/dashboard/data.py::parse_tasks`：`implementing` 读 worktree tasks.md（实现者实时勾选处）、merge-back 后状态读主树 tasks.md（合并带回的勾选），与实现者实际编辑位置一致
- [x] 3.2 核对 `pm_engine._read_implementer_result`（worktree 优先 / 主树回退）与 verifier 的 `verify-progress` / `spec_dir` 路径假设在 merge-back 后的一致性

## 4. 测试与验证

- [x] 4.1 单元测试：mock `Popen` 断言收到 `cwd=worktree`；merge-back 在成功/冲突/已合并三种情况的行为（含幂等跳过与失败不推进状态）
- [x] 4.2 集成测试：`data.parse_tasks` 在 `implementing`（worktree）与 `implemented`（主树）两态读取位置正确、进度与实现者标记一致
- [x] 4.3 回归：`python3 -m pytest tests/ -q` 全量通过，无既有用例回归
- [x] 4.4 端到端：跑一个完整 implement→verify 周期，确认 worktree 隔离生效、merge 后主树含实现、verifier 验证合并代码、Dashboard 任务进度正常（手动端到端验证通过）
