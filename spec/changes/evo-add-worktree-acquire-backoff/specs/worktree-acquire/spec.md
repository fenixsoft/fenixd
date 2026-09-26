# worktree-acquire：锁让路退避与降级计数

## ADDED Requirements

### Requirement: 锁活跃导致的 worktree 创建失败须退避重试
_prepare_worktree 在 worktree_manager.create 返回 None 且原因是同 spec:agent_type 锁活跃时，按短退避序列等待重试；重试耗尽才返回既有 gave up 错误。

#### Scenario: 持锁方排空后取得 worktree
- WHEN 并行 run 持锁、退避期间锁释放且 spec 状态仍在预期态
- THEN create 成功、run 正常启动，不触发新验证流程降级

#### Scenario: 重试耗尽仍锁活跃
- WHEN 退避序列耗尽锁仍活跃
- THEN 返回既有 gave up 错误，走既有降级路径

### Requirement: 人工接管语义不自动穿越
frozen、_cancelled_hold、status 迁出预期态三种让路原因保持立即放弃，不进入退避重试；退避循环每轮重探前复查三种原因，等待期间出现任一即立即让位，不得照常取得 worktree。

#### Scenario: 手动冻结立即让位
- WHEN spec 处于 frozen 且 worktree 创建失败
- THEN 不等待立即返回既有错误，行为与现状一致

#### Scenario: 退避期间人工接管
- WHEN 退避等待期间 spec 被冻结或 status 迁出预期态
- THEN 下一轮复查命中立即让位，不取得 worktree

### Requirement: 降级 WARNING 附计数
新验证流程降级分支的 WARNING 附累计降级次数。

#### Scenario: 降级可统计
- WHEN 第 N 次降级发生
- THEN WARNING 文案含累计次数信息，可据日志统计降级频率