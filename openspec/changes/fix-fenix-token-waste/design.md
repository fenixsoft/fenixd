# Design: fix-fenix-token-waste

## Context

Fenixd 的 agent 编排（implementer/verifier/planner）通过 `claude -p` 子进程 + git worktree 隔离实现。`add-multi-project-monitoring` 事故暴露了一组叠加的浪费点：

1. **merge-back 死循环**：主树脏时 `git merge --no-ff` 必败 → spec 回 `ready` → 全新 worktree 全量重跑 → 再败。一次事故烧掉 $23、965 轮、~210 万 token，全部作废。
2. **无界运行**：`agents.max_turns` 是死配置，`agent_runner.py` 从不读取，单次 run 跑到 118–125 轮。
3. **遥测噪音**：claude CLI `--verbose` 模式每 token 发一条 `thinking_tokens` 事件，占转录 75%、事件数 98.7%。
4. **重试不续跑**：每次 attempt 新建 worktree + 新 session，前次成果全丢。
5. **运行卫生**：孤儿 worktree 不清理、双 daemon 可并发、run_id 复用导致一文件混装多会话。

本 change 全部针对以上根因，不改外部行为契约，只改 fenixd 自身的运行机制。

## Goals / Non-Goals

**Goals**
- 消除 merge 失败导致的无限重跑循环（熔断 + 主树健康检查）
- 单次 run 成本减半以上（max_turns 强制 + 续跑）
- 产物与磁盘噪音下降 ~98%（遥测过滤）
- 运行卫生：单实例、孤儿清理、run_id 独立

**Non-Goals**
- 不改 claude CLI 调用以外的外部接口
- 不引入新依赖（全用标准库/现有工具）
- 不改变 spec 内容规范（openspec 文档契约不变）
- 不为历史 run 产物做数据迁移（旧 jsonl 含遥测事件可继续被 Dashboard 兼容读取）

## Decisions

**D1: 熔断用错误指纹哈希，而非简单计数**
- 对 `merge_error` 文本做归一化（strip + 取关键行）后哈希。同一指纹连续失败 ≥2 次 → `blocked`。
- 替代方案：纯计数（失败 N 次就熔断）。否决原因：不同原因（如网络抖动 vs 主树脏）混在一起，会误熔断可恢复的失败。
- 涉及：`pm_engine.py` 重试分支、`state_machine.py` 新增 `blocked` 状态、`VALID_TRANSITIONS`。

**D2: 主树健康检查用 stash，而非强制 commit**
- dispatch implementer 前若 `git status --porcelain` 非空，`git stash push --include-untracked` → merge 成功后 `git stash pop`。
- 替代方案：直接 commit 主树改动。否决原因：可能把用户未完成的半成品写进历史；stash 可逆且不污染历史。
- pop 冲突时保留 stash + WARNING，不阻塞流转（spec 走 `implemented`）。
- 涉及：`worktree_manager.py`（stash/pop 封装）、`pm_engine.py` dispatch 前置。

**D3: max_turns 用 CLI 层限制**
- `_run_claude` 读取 `agents.max_turns`（默认 50）拼入 `claude --max-turns <n>`。
- 若当前 claude CLI 版本不支持该 flag，回退为不传（记录 WARNING），保证不破坏现有运行。
- 涉及：`agent_runner.py:_run_claude`。

**D4: thinking_tokens 直接丢弃，不做聚合**
- `_read_stream` 遇到 `system/subtype=thinking_tokens` 直接跳过，不写盘。
- 替代方案：聚合为每分钟一条 summary。否决原因：Dashboard 不需要该遥测，聚合徒增复杂度。
- 涉及：`agent_runner.py:_read_stream`。

**D5: 续跑用 `--resume` 复用 session，仅 implementer**
- attempt 1 失败后，attempt 2 复用同一 worktree 目录 + `claude --resume <session_id>`。
- 仅 implementer 启用（verifier/planner 单次较短，续跑收益低）；session 丢失时回退全新运行。
- 涉及：`agent_runner.py:_execute_agent`、`worktree_manager.py`（worktree 复用）。

**D6: 单实例锁用 flock 文件锁**
- 启动时对 `STATE.md` 同目录的专用锁文件（`.fenix/daemon.lock`）获取排他 flock；失败即退出。
- flock 跨进程可靠、异常退出自动释放，无需清理逻辑。
- 涉及：`fenixd.py` 启动段。

**D7: run_id 带 attempt 序号**
- `_execute_agent` 内部 attempt 循环里 run_id 追加 `-a<attempt>`，产物文件一一对应。
- 涉及：`agent_runner.py`。

**D8: 孤儿清理在启动时全量扫描**
- 启动时遍历 `base_dir`，删除不在 `_active_worktrees` 的所有目录 + 对应分支 + `git worktree prune`。
- 涉及：`worktree_manager.py:cleanup_orphans`（从"仅活动集合"改为"全量扫描"）。

## Risks / Trade-offs

- [stash pop 冲突导致主树混乱] → 保留 stash 条目 + WARNING；stash 可 `git stash list` 找回，不丢失数据。
- [`--resume` 在部分场景不可用] → 捕获异常回退全新运行并记录 WARNING。
- [`--max-turns` 不受 claude CLI 支持] → 回退不传 flag，不破坏运行。
- [新增 `blocked` 状态影响 Dashboard] → Dashboard 状态徽章需兼容未知状态（不渲染为新样式即按 `error` 处理），不阻塞。
- [旧 run 产物含遥测事件] → Dashboard 解析本就逐行容错，旧产物继续可读。

## Migration Plan

1. 本 change 无外部部署依赖，直接改代码。
2. 配置文件不变：`agents.max_turns` 已在 `config.yaml`（值 50），从死配置变为生效。
3. 新增 `blocked` 状态：`state_machine.py` 与 Dashboard 渲染兼容。
4. 回滚：git revert 本 change 即可（无数据迁移）。

## Open Questions

- `--resume` 是否需要覆盖 verifier/planner？（当前定 implementer only，收益评估后可扩展）
- `blocked` 状态是否需要 Dashboard 增加「重置为 ready」操作按钮？（最小实现先人工改 STATE.md）
