# recovery-watch-transition-guard 增量规格

## ADDED Requirements

### Requirement: 状态过渡窗口内不误判 stale

recovery watch 与假就绪巡检在把某 spec 判定为 stale（未恢复推进）之前，MUST 检查是否存在『正在进行的 implementer→merge 过渡』：spec 有待合并分支（worktree_manager 侧 pending merge），或 implementer succeed 信号落在判定缓冲窗口（设计固化秒数）内时，MUST 跳过本次判定（顺延复查）或直接视为已恢复，MUST NOT 升级 dispatch_stalled。

#### Scenario: 成功-合并过渡窗口内复查顺延
- **WHEN** implementer 已 succeed 但 merge/状态机 transition 尚未完成（worktree 已清理、spec 仍处过渡态），recovery watch 恰好到点复查
- **THEN** 系统 MUST 跳过本次判定并顺延复查（或视为已恢复），MUST NOT 升级 dispatch_stalled

#### Scenario: 真实 stale 仍被报出
- **WHEN** spec 确无待合并分支、无近期 succeed 信号，且超过复查时限仍未恢复推进
- **THEN** 系统 MUST 按既有语义升级 dispatch_stalled，行为与现状一致

#### Scenario: implementer 成功即重置计时器
- **WHEN** 框架收到某 spec 的 implementer succeed 信号
- **THEN** 该 spec 的 recovery watch 计时器 MUST 重置/顺延（若采用重置方案），避免旧登记在过渡窗口误触发