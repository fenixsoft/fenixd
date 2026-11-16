# impl-delivery-preservation Specification

## ADDED Requirements

### Requirement: 清扫前快照写入共享引用

worktree 清扫（rmtree）前对脏工作区的快照 MUST 写入主 gitdir 的共享引用（refs/preservation/<run_id>，指向快照 commit），保证快照对象 GC 可达；MUST NOT 仅以悬空 commit + 日志指引的形式交付恢复信息。快照 commit MUST 包含未跟踪（untracked）文件内容——stash create 默认不含 untracked 文件，仅不可达 blob + 日志 SHA 留档不满足 GC 可达要求。

#### Scenario: 清扫后快照仍引用可达

- **WHEN** 对含未提交改动的 impl worktree 执行清扫
- **THEN** refs/preservation/<run_id> 存在且指向快照 commit，for-each-ref --contains 可列出交付链

#### Scenario: 恢复指引指向真引用

- **WHEN** 快照落成后输出恢复信息
- **THEN** 指引内容为「git update-ref/branch 自 refs/preservation/<run_id> 恢复」形态，而非依赖人工 stash store 转正

#### Scenario: untracked 文件纳入引用链

- **WHEN** 脏工作区含未跟踪新增文件并执行清扫前快照
- **THEN** untracked 文件内容可经 refs/preservation/<run_id> 引用链检出，而非仅以不可达 blob + 日志 SHA 留档

### Requirement: preservation 引用按终态清理

refs/preservation/<run_id> MUST 保留至对应 spec 达到终态（merge-back 决策完成或人工消费记录）后再由清扫删除；删除前 MUST 校验对应交付已被消费或显式放弃，MUST NOT 在人工裁决在途时删除。

#### Scenario: 人工裁决在途时不清理

- **WHEN** spec 处于冻结待人工裁决、preservation 引用仍被裁决流程引用
- **THEN** 清扫不删除该引用与所指对象

#### Scenario: 终态后清理

- **WHEN** spec 终态落定且交付已被消费（合回/放弃留痕）
- **THEN** 清扫删除 refs/preservation/<run_id>，仓库不留长期悬挂引用

### Requirement: 终态 impl 分支保留至决策后

预算耗尽/冻结场景下终态 impl 分支的删除 MUST 推迟到 merge-back 决策之后执行，删除动作 MUST 在 preservation 引用就位后进行。worktree 无脏改动（无可快照内容）时，preservation 引用 MUST 指向该 impl 分支 tip，保证已提交交付链在分支删除后仍引用可达。

#### Scenario: 分支删除不早于保全

- **WHEN** 清扫流程删除终态 impl 分支
- **THEN** 该分支 tip 已被 preservation 引用（或等价引用）覆盖，删除后交付链仍引用可达

#### Scenario: clean worktree 已提交交付保全

- **WHEN** 终态 impl worktree 无脏改动（交付已全部提交）且清扫删除其分支
- **THEN** refs/preservation/<run_id> 指向该分支 tip，删除后交付链仍 for-each-ref 可达