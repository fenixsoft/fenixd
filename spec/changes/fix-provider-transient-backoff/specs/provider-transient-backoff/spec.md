# provider-transient-backoff — 瞬断原地退避与同现场续跑

## ADDED Requirements

### Requirement: 原地退避优先于换链

runner 的 attempt 循环在 attempt 失败且命中瞬断类错误（`classify_switch_error`：unrecognized_model / 5xx / 连接类）时，MUST 先消耗原地重试预算：不递增 attempt 计数、不触发该 provider 的 switch 冷却、不改变 chain_cursor，写入 `transient_retry` 事件后按 `agents.transient_backoff_schedule` 的下一档秒数退避，然后以同一 provider 重跑该 attempt（新 run_id 后缀 `r{n}`，独立产物文件）。

#### Scenario: 瞬断首败原地退避续跑成功

- **GIVEN** attempt 1 的 claude 进程死于网关瞬断（stderr 含 unrecognized_model / 或 exit≠0 且无 result 事件且 stderr 含 `[claude-code:]` 诊断行）
- **WHEN** 异常进入 attempt 循环分类且原地重试预算未耗尽
- **THEN** attempt 计数保持 1，provider 链候选不变，无 switch 冷却记录；产生一条 `transient_retry` 事件（含退避秒数与重试序号）；sleep 后以同 provider 发起新进程，且当上一产物可提取 session_id 时以 `--resume` 续跑

#### Scenario: 原地重试预算耗尽转换链

- **GIVEN** 同一 attempt 已连续原地重试次数达到 `agents.transient_backoff_schedule` 长度（缺省 3）仍失败
- **WHEN** 异常再次进入分类
- **THEN** 原地预算标记耗尽，转走现行逻辑：该 provider 进入 switch 冷却（300s）且 chain_cursor 前进，下一 provider 以同一 worktree 新会话（无 `--resume`）发起

#### Scenario: resume 死 session 兜底

- **GIVEN** 原地重试以 `--resume <session_id>` 发起后进程秒挂，产物错误含 `No conversation found with session ID`
- **WHEN** 发起下一次原地重试
- **THEN** 清除该 session_id 以全新会话重试，不因此递增 attempt 计数；连续 2 次 resume 失败后本次 attempt 剩余重试改为全新会话

### Requirement: attempt 间 worktree 现场保留扩展到全部 agent_type

attempt 失败后仍有重试额度（attempt 或原地重试）时，MUST 对全部 agent_type 保留 worktree（含其中 dev-server），下个 attempt/子重试复用同一目录与分支；无重试额度时按终态规则处置。

#### Scenario: planner-judge attempt 间复用 worktree

- **GIVEN** planner-judge run 的 attempt 1 死于瞬断
- **WHEN** 发起 attempt 2（原地重试耗尽后转换链）
- **THEN** attempt 2 使用与 attempt 1 相同的 worktree 目录与分支，不新建 worktree

### Requirement: transient 终态失败保留现场

run 以 error 终态收场且错误被判定为瞬断类时，MUST 以 `keep_for_reuse` 登记 worktree（目录与分支留作复用遗产），替代 `cleanup(success=False)`；非瞬断终态失败维持现行清理行为。

#### Scenario: 瞬断终态现场可被下轮认领

- **GIVEN** implementer run 烧尽 attempt 与原地重试预算，终态 error 带 `[provider-transient]` 标记
- **WHEN** 该 spec 稍后被重新派发
- **THEN** worktree 创建经 `_take_reusable_worktree` 认领此前登记的同一目录与分支，继承已提交与未提交现场；长期无人认领时由既有 `cleanup_stale_worktrees` 兜底清理

#### Scenario: 非 transient 终态失败不保留现场

- **GIVEN** implementer run 因真实缺陷类错误（非瞬断判定）烧尽全部重试
- **WHEN** 进入终态处置
- **THEN** 维持现行 `cleanup(success=False)` 行为，不登记复用遗产
