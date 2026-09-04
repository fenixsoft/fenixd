## Why

Fenixd 在 `add-multi-project-monitoring` 一个 spec 上因 merge-back 反复失败触发了 6+ 次全量重跑，烧掉 $23、965 轮、约 210 万 token（外加约 1600 万缓存读取），全部作废、无任何代码合回主树。根因是主树脏状态与无界重试叠加：每次 implementer 全量重做，merge 必败，重试从头再来。叠加问题：单次 run 无 turn 上限（118–125 轮）、遥测噪音占转录 98%、双 daemon 双派发。

## What Changes

- **merge 失败指纹熔断**：对 merge 错误做指纹哈希，同一指纹连续失败 ≥2 次 → spec 进入新增 `blocked` 状态，停止自动重试并等待人工介入
- **主树健康检查**：dispatch implementer 前检查主树 git 状态；脏则先 `git stash push --include-untracked` 再派发，merge 成功后 `git stash pop`
- **max_turns 强制执行**：真正读取 `agents.max_turns` 并传给 claude CLI，限制单次 run 轮数，不再无界运行
- **thinking_tokens 遥测过滤**：`_read_stream` 不再把每 token 一条的 `thinking_tokens` 遥测事件写盘（当前占转录 75%、事件数 98.7%）
- **孤儿 worktree 启动清理**：daemon 启动时扫描 `base_dir`，清理不属于活动集合的残留 worktree 与对应分支
- **单实例锁**：启动时加 flock 排他锁，第二个 daemon 直接退出并提示，防止双派发
- **run_id 每次 attempt 独立**：attempt 序号进入 run_id，产物文件与尝试一一对应，不再一文件混装多会话
- **失败重试 --resume 续跑**：attempt N+1 复用同一 worktree 与 session（`claude --resume`），不再从头全量重跑

## Capabilities

### New Capabilities

- `merge-circuit-breaker`: 主树健康检查 + merge 失败指纹熔断，终止无限重跑循环
- `agent-cost-control`: max_turns 强制 + thinking_tokens 遥测过滤，控制单次 run 成本与产物噪音
- `retry-resume`: 失败重试复用 worktree/session 续跑 + 每次 attempt 独立 run_id
- `daemon-singleton`: 单实例排他锁，防止双 daemon 双派发
- `worktree-hygiene`: 启动时清理孤儿 worktree 与残留分支

### Modified Capabilities

（无。openspec/specs/ 为空，全部为新增能力。）

## Impact

- **代码**：`core/pm_engine.py`、`core/agent_runner.py`、`core/worktree_manager.py`、`core/state_machine.py`、`core/config.py`、`fenixd.py`
- **状态机**：新增 `blocked` 状态，影响 `VALID_TRANSITIONS` 与 Dashboard 状态徽章
- **产物格式**：`.fenix/runs/` 的 jsonl 不再含 `thinking_tokens` 事件；`run_id` 格式变化（带 attempt 序号），依赖 run_id 解析的 Dashboard 需兼容
- **配置**：`agents.max_turns` 从死配置变为生效项
