# spec-agent-shutdown-interrupt（delta）

## ADDED Requirements

### Requirement: 关闭期分支的在飞引用保护

`cleanup_stale_worktrees` 在执行 `git branch -D` 删除分支之前，MUST 检查该分支是否被在飞或待收口的 spec 引用：若该分支名等于 STATE 中任一 `implementing` / `implemented` / `testing` spec 的 `branch` 字段值，或等于任一带 `_recovery_resume` 标记的 spec 的 `branch` 值（恢复保留续做后的形态其 status 为 `ready`，该 `branch` 正是被保留待续做的载体——保护义务 MUST NOT 因该 spec 不在 `implementing` 而失效），或按「**完整 spec 名 + 分隔符边界**」全等比较（口径同 `recovery-branch-anchor`：去掉 `<prefix>/` 后末段为纯数字时间戳、其前段与该 spec 名全等）匹配任一 `implementing` / 带 `_recovery_resume` 标记的 spec 的实现分支（MUST NOT 以 `<prefix>/<spec>-*` 前缀 glob 命中集合为判据——spec 名互为前缀时会把他人分支报成本 spec 的分支，误导人工归因；本方向虽只致过度保留、不损成果，口径仍 MUST 与 `recovery-branch-anchor` 一致），则 MUST 保留该分支（可照常删除 worktree 目录），MUST NOT 连带删分支。

现状缺口：`cleanup_stale_worktrees` 的删分支动作无条件执行。一旦某在飞 spec 的分支锚点尚未落盘、其 worktree 目录又侥幸存活到下一次 boot，该分支会被直接删除——此时连人工 `git merge --ff-only` 都无法救回成果。

分支保留与删除 MUST 记入日志（保留时打 WARNING 含 spec 名与分支名）。

#### Scenario: 在飞 spec 的分支不被清扫

- **WHEN** `cleanup_stale_worktrees` 处理一个 stale worktree，其分支正是某个 `implementing` spec 的实现分支
- **THEN** worktree 目录被清理，但该分支 MUST 保留

#### Scenario: 恢复保留续做的 ready spec 分支不被清扫

- **WHEN** 某 spec 经恢复保留续做落为 `ready`（带 `_recovery_resume` 标记与保留的 `branch`），其原先的工作目录已不在活动集而被判为 stale
- **THEN** `cleanup_stale_worktrees` MUST 保留该分支，MUST NOT 因该 spec 的 status 不是 `implementing` 而放行删除

#### Scenario: 无引用分支照常删除

- **WHEN** `cleanup_stale_worktrees` 处理的分支不被任何在飞/待收口 spec 引用
- **THEN** 按现行行为删除该分支

#### Scenario: 保留动作留痕

- **WHEN** 因在飞引用而保留某分支
- **THEN** 日志出现 WARNING，含被保留的分支名与其所属 spec 名

### Requirement: 关闭期保护集的结构性下界

停机路径构造 orphan 清理保护集时，MUST NOT 存在「保护集为空集 → 无差别清理」的退化路径。保护集 MUST 至少包含 STATE 中所有 `implementing` spec 经事实查询解析出的在册 worktree 路径，无论 sidecar 是否写过、无论排水是否超时。

理由：排水窗口内 agent 进程自行退出时 `drain_wait` 返回空集、sidecar 不写，但这并不意味着该 run 的收口已完成——其 worktree 仍被重启后的恢复链需要。保护集必须由**状态**而非**事件可见性**决定。

清理确有发生的场合，MUST 按既有要求打日志说明保护集构成（来源 (a)(b)(c) 各自的条目数），使「为何某 worktree 被保留/被删除」可事后归因。

#### Scenario: sidecar 未写时保护集不为空

- **WHEN** 排水窗口内所有 agent 自行退出、sidecar 未写，STATE 中仍有 `implementing` spec 且其 worktree 在册
- **THEN** 该 worktree MUST 进入保护集并跳过清理

#### Scenario: 同一 spec 多个在册载体全部受保护

- **WHEN** 某 `implementing` spec 存在多个在册 worktree（如 impl- 与 repair- 并存）
- **THEN** 全部候选 worktree MUST 进入保护集，MUST NOT 因单值事实查询（`find_worktree_by_spec`）对歧义返回 None 而漏保护

#### Scenario: 保护集构成留痕

- **WHEN** 停机路径执行 cleanup_orphans
- **THEN** 日志记录保护集各来源的条目数，事后可判断某 worktree 因何被保留

#### Scenario: 全然无在飞 spec 时正常清理

- **WHEN** STATE 中无任何 `implementing` spec 且 sidecar 无在册项
- **THEN** 保护集为空，orphan 清理按现行行为执行，MUST NOT 因本要求而拒绝清理

## MODIFIED Requirements

### Requirement: 被终止的 run 写入 interrupted 标记

被框架终止的 run MUST 在 run 文件中写入 `interrupted` 标记（含原因），使重启后的恢复与该 run 的失败归因可区分「框架主动终止」与「agent 自身失败」。

该标记的写入时机 MUST 早于或等于保全动作（sidecar 落盘）。适用对象 MUST 限定为**尾部无终态事件的 run**（与既有 `sweep_runs_without_terminal_state`（`core/agent_runner/liveness.py:99-130`）同判据——该方法对 `_file_has_terminal_event` 命中的文件直接 `continue`）：`interrupted` 本身即 `RUN_TERMINAL_EVENT_TYPES`（`core/agent_runner/liveness.py:58-60`）成员，该口径明载「任一类型出现即视为 run 已终结」，故对已含 `result` 终态的自完成 run 追加该标记会注入**第二个终态事件**、污染失败归因，MUST NOT 如此。**排水窗口内已自行退出、后置收口未落盘**的 run 不依赖本标记识别——其进程已产出 `result` 终态，收口未完成由 spec 级「待 re-merge-back」标记承载（见 `mergeback-inplace-repair` 的「repair 成功的待合并状态持久化」）与保全 sidecar 承载；本要求 MUST NOT 被读作「须为自完成 run 追加 `interrupted`」。

#### Scenario: 标记追加到 run 文件

- **WHEN** agent 在缓冲窗口内被 SIGTERM 终止
- **THEN** 该 run 的文件中出现 interrupted 标记，含终止原因

#### Scenario: 排水内自行退出的 run 同样可识别

- **WHEN** 某 run 的 agent 进程在排水窗口内自行退出，其后置收口未落盘
- **THEN** 重启后的恢复链能识别该 run 的收口未完成状态（不依赖 run 文件中的 interrupted 标记即可区分，见 `mergeback-inplace-repair` 的待 re-merge-back 标记）

