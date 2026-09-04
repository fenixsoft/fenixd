# Tasks: fix-fenix-token-waste

## 1. 基础：状态机新增 blocked 状态

- [x] 1.1 `core/state_machine.py` 新增 `BLOCKED` 状态，扩展 `VALID_TRANSITIONS`（`implementing→blocked`、`blocked→ready`、`ready→blocked`）
- [x] 1.2 Dashboard 状态徽章/筛选兼容 `blocked`（渲染为阻塞样式，不崩溃）

## 2. merge-circuit-breaker

- [x] 2.1 `core/worktree_manager.py` 封装主树健康检查：`ensure_clean_tree()`（`git status --porcelain` 非空则 `git stash push --include-untracked`，返回是否 stash 过）与 `restore_after_merge()`（`git stash pop`，冲突则保留 stash + WARNING）
- [x] 2.2 `core/pm_engine.py` dispatch implementer 前调用 `ensure_clean_tree()`；派发入口失败时记录错误
- [x] 2.3 `pm_engine.py` merge-back 成功后调用 `restore_after_merge()`，冲突不阻塞 spec 流转
- [x] 2.4 `pm_engine.py` merge 失败路径：对 `merge_error` 计算归一化指纹，连续相同指纹 ≥2 次 → spec 置 `blocked` 并停止重试

## 3. agent-cost-control

- [x] 3.1 `core/agent_runner.py:_run_claude` 读取 `agents.max_turns`（默认 50）拼入 `claude --max-turns <n>`；若 CLI 不支持则回退不传 + WARNING
- [x] 3.2 `agent_runner.py:_read_stream` 丢弃 `system`/`thinking_tokens` 事件，不写入产物文件

## 4. retry-resume

- [x] 4.1 `agent_runner.py:_execute_agent` run_id 追加 attempt 序号（`impl-<spec>-<ts>-a<attempt>`），每次 attempt 产物写入独立文件
- [x] 4.2 implementer 失败重试复用同一 worktree 目录 + `claude --resume <session_id>` 续跑；session 丢失时回退全新运行并记录 WARNING

## 5. daemon-singleton

- [x] 5.1 `fenixd.py` 启动时对 `.fenix/daemon.lock` 获取 flock 排他锁；已被持有则打印「已在运行」并以非零码退出

## 6. worktree-hygiene

- [x] 6.1 `worktree_manager.py:cleanup_orphans` 改为全量扫描：删除所有不在 `_active_worktrees` 的目录 + 对应分支 + `git worktree prune`；失败记 WARNING 不阻塞

## 7. 测试与验证

- [x] 7.1 补 `blocked` 状态流转单元测试（tests/test_core.py）
- [x] 7.2 补 merge 熔断 + 主树健康检查（stash/pop）单元测试
- [x] 7.3 补 max_turns 参数拼接 + thinking_tokens 过滤单元测试
- [x] 7.4 补 run_id attempt 序号 + daemon 单实例锁单元测试
- [x] 7.5 运行 `python3 -m pytest tests/ -q` 全绿（含既有 193 项）
