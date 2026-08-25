# merge-circuit-breaker Spec

## ADDED Requirements

### Requirement: Merge 失败指纹熔断
Fenixd SHALL 对 implementer merge-back 失败计算稳定失败指纹（对错误信息做归一化哈希）。同一 spec 的同一指纹连续失败达到阈值（默认 2 次）后，Fenixd MUST 将 spec 置为 `blocked` 状态并停止自动重试，等待人工介入。人工确认根因消除并将状态重置为 `ready` 后，Fenixd SHALL 恢复对该 spec 的正常调度。

#### Scenario: 连续两次相同 merge 失败进入 blocked
- **WHEN** 某 spec 的 implementer merge-back 因「本地改动将被覆盖」失败，指纹为 F
- **AND** 重试后再次以相同指纹 F 失败
- **THEN** spec 状态变为 `blocked`，错误信息记录指纹 F，且不再自动派发 implementer

#### Scenario: 不同指纹失败不触发熔断
- **WHEN** 某 spec merge-back 首次以指纹 F1 失败，重试后以不同指纹 F2 失败
- **THEN** spec 按现有重试逻辑处理（`_retry_count` 递增），不进入 blocked

#### Scenario: blocked 状态可人工恢复
- **WHEN** spec 处于 blocked 状态，人工将状态改为 ready
- **THEN** Fenixd 恢复对该 spec 的正常调度

### Requirement: 主树健康检查
Fenixd MUST 在 dispatch implementer 前检查主工作树 git 状态。若主树存在未提交改动（含未跟踪文件），Fenixd SHALL 先执行 `git stash push --include-untracked` 暂存，再创建 worktree 派发。implementer merge-back 成功后 MUST 执行 `git stash pop` 恢复原有改动；pop 冲突时 SHALL 保留 stash 条目并记录 WARNING，不阻塞 spec 流转。

#### Scenario: 主树脏时自动暂存后派发
- **WHEN** 主树存在未提交改动（M 或 ??），spec 进入 dispatch
- **THEN** Fenixd 先 stash（含 untracked），再创建 worktree 派发 implementer

#### Scenario: merge 成功后恢复暂存
- **WHEN** implementer merge-back 成功
- **THEN** Fenixd 执行 `git stash pop`，主树恢复原有未提交改动

#### Scenario: stash pop 冲突不阻塞
- **WHEN** merge-back 成功后 stash pop 产生冲突
- **THEN** Fenixd 保留 stash 条目、记录 WARNING，spec 仍正常流转到 implemented
