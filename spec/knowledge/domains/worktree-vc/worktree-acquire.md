# worktree 获取退避等待与降级计数
<!-- knowledge: capability=worktree-acquire rev=1
     sources=spec/archive/2026-10-04-evo-add-worktree-acquire-backoff -->

agent run 启动取 worktree 时对「同 spec:agent_type 锁被并行 run 持有」的短退避等待与人工接管让路规则，以及新验证流程降级 WARNING 的累计计数口径。

## 现行规则

- 锁活跃退避等待重试：worktree 创建返回 None 且原因是同 spec:agent_type 锁被并行 run 持有（`has_active_lock` 探针命中）时，按短退避序列（30s/60s/120s）逐轮等待重试，等持锁方排空；等待重试在 run 获取层（agent_runner `_prepare_worktree`）内同步完成，不消耗 attempt 重试额度、不写 STATE 退避字段。锁释放后下一轮创建即取得 worktree，run 正常启动，不触发新验证流程降级。
- 重试耗尽才放弃：退避序列走完仍锁活跃，才返回既有 gave up 终态，错误文案签名保持 `Failed to create worktree (gave up: parallel run or manual freeze)` 不变，走既有降级路径。
- 人工接管立即让位（不可自动穿越）：frozen、`_cancelled_hold`、status 迁出预期态三种让路原因保持立即放弃——创建失败即返回既有错误，零等待、不进退避。退避循环每轮重探创建前复查三种人工接管态；等待期间出现任一（含并行 run 完成后的状态迁移）即立即让位，不得在锁释放后照常取得 worktree。
- 非锁失败不进退避：非锁、非人工接管的创建失败（git 命令失败等其它原因）保持既有 attempt 层重试语义（attempt 未达上限时短 sleep 后继续）；退避等待中锁已释放但创建仍失败，即按其它失败原因返回，不空转退避。
- 分层边界：锁等待只存在于 run 获取层——worktree_manager 创建与锁归属诊断层不排定重试定时器、不写 STATE 退避字段，创建层对活动锁不清理（活动/残留归属判定与残留清理重试由「run 工作树隔离与冲突恢复」页承载）。锁释放后再创建取得的是空闲 worktree，不形成并行 run，不违反双派发防护。
- 降级可统计：新验证流程降级到旧版 verifier 时，降级 WARNING 附模块级累计计数（「第 N 次降级」）；计数器 MUST 为模块级而非实例级——PMEngine 按 run 重建实例，实例级计数恒为 1、无法统计频率。计数只做观测，不改变降级行为。

## 溯源

- 2026-10-04 evo-add-worktree-acquire-backoff（spec/archive/2026-10-04-evo-add-worktree-acquire-backoff） — 新增本页：锁活跃创建失败由「sleep 5 秒一次即放弃」改为获取层短退避等待重试（不消耗 attempt 额度），人工接管三态立即让位且退避每轮复查、非锁失败保持 attempt 层语义，新验证流程降级 WARNING 附模块级累计计数
