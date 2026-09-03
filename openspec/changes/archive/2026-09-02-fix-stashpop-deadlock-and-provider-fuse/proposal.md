## Why

框架 merge-back 存在两个反复复现的死锁源，已多次导致人工处置（2026-08-25 $23/token-waste 事故、2026-08-26 两次 merge-back 熔断处置）：

1. **stash pop 冲突死锁**：`ensure_clean_tree` 派发前 `git stash`（autostash），`restore_after_merge` 在 merge 成功后 `git stash pop`。当主树有未提交改动（如修复中的前端文件）且合并期间 HEAD 被其它 spec 推进时，pop 对同文件产生内容冲突 → 主树进入 UU 半合并状态、index.lock 满、**所有 git 写操作瘫痪**（`could not write index` / `unmerged files`），merge-back 连败 2 次触发熔断。当前 `restore_after_merge` 对 pop 冲突仅记 WARNING 返回 False，无任何自愈。
2. **provider 网关故障窗口反复重派**：provider 网关返回 400/404（模型下线/改名）或 401（余额不足）时，`agent_runner` 仍按 max_retries 重试并让状态机反复 ready→implementing，每次派发都 autostash、每次 merge-back 都撞残留冲突——故障窗口内烧 token 且放大 stash 冲突概率（2026-08-26 20:15~20:33 deepseek-v4-flash 下线事件实证）。

## What Changes

- **`core/worktree_manager.py`**：`restore_after_merge` 检测到 `git stash pop` 冲突（返回非 0 且 stderr 含 CONFLICT）时自动自愈：
  - 对 UU 未合并文件执行 `git checkout HEAD -- <file>` 清掉半合并状态（丢弃 stash 版本，保留 merge 后的工作区版本，即不丢失已 merge 的实现）；
  - `git reset` 清空 index 中残留的 staged 条目，使主树回到干净可写状态；
  - 将「pop 冲突、被丢弃的 stash 改动文件清单」写入返回信息，由调用方记入 spec `error` 字段并触发 admin 告警（stash 条目保留，人工可 `git stash show` 找回被丢弃内容）。
- **`core/agent_runner.py`**：新增 provider 熔断——同一 provider 在滚动窗口内（如 5 分钟内 3 次）返回 HTTP 4xx（400/401/404）时，标记该 provider `circuit_open`（默认 30 分钟冷却），熔断期间跳过该 provider 的派发（直接失败返回、不计入 spec 的连续失败重试），窗口冷却后自动半开恢复。
- **`core/event_bus.py`/`core/pm_engine.py`**（如需）：熔断状态在 dashboard/statusline 可见（错误信息含 `provider circuit open: <name> (<code> x N)`），便于区分「provider 故障」与「spec 本身问题」。
- 不改动 StateMachine / SPEC 格式 / 验证产物格式。

## Capabilities

### New Capabilities
- `mergeback-stashpop-self-heal`: `restore_after_merge` 对 git stash pop 冲突的自动检测与自愈：清 UU 未合并状态、恢复 index、保留 stash 条目、冲突清单上报调用方，杜绝 UU 半合并瘫痪全库 git 操作。
- `provider-fault-fuse`: agent_runner 对 provider 网关 4xx 错误的滚动窗口熔断与冷却恢复，故障窗口内不派发、不反复重试、不放大 autostash/merge-back 副作用。

### Modified Capabilities
<!-- 无既有 spec 变更 -->

## Impact

- **核心代码**：`core/worktree_manager.py`（restore_after_merge 自愈）、`core/agent_runner.py`（provider 熔断）、`core/event_bus.py`/`core/dashboard/data.py`（熔断状态透出，如需）。
- **行为**：merge-back 失败不再瘫痪主树 git 写操作；provider 故障不再引发 tokens 浪费与状态机反复流转。
- **测试**：`tests/test_core.py`、`tests/test_agent_runner.py` 补对应单测（pop 冲突自愈、熔断开关/冷却/恢复）。