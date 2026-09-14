# spec-recovery-branch-anchor

## ADDED Requirements

### Requirement: 实现产物成功即落锚点

implement / repair run 到达**终态成功**时，框架 MUST 在 merge-back（含 repair 的 re-merge-back）**之前**把该 run 的 `branch` 与 `implementer_run` 写入 STATE。MUST NOT 仅在 merge-back 成功后才写——该时机使「已实现、未合并」这一段在飞状态在 STATE 中无任何分支锚点。

`branch` 字段的语义为「**本轮实现分支**」（写入时机提前，取值集合不变）。run 未达终态成功（失败、中断、被杀）时 MUST NOT 写入，保持既有语义。

#### Scenario: implementer 成功即落盘，不等 merge-back

- **WHEN** implementer run 返回终态 success，随即 merge 预演检出语义冲突并直通 repair 通道
- **THEN** 进入 repair 之前 STATE 的 `branch` 已等于该 run 的实现分支，`implementer_run` 已等于该 run_id

#### Scenario: repair 成功即落盘，不等 re-merge-back

- **WHEN** repair run 返回终态 success，随后 re-merge-back 尚未执行
- **THEN** STATE 的 `branch` 已等于被修复的实现分支

#### Scenario: 失败 run 不写锚点

- **WHEN** implementer run 以 error 或非正常退出结束
- **THEN** STATE 的 `branch` 不被该 run 写入（保持原有值或 null）

#### Scenario: 与 merge-back 成功后写入值一致

- **WHEN** 同一 spec 的同一轮实现分别在「run 成功时」与「merge-back 成功后」观察 STATE.branch
- **THEN** 两次取值为同一分支名，MUST NOT 出现取值漂移

### Requirement: 锚点的 git 分支命名空间回落

恢复链解析某 spec 的分支锚点时，MUST 按以下顺序取值，任一环节命中即停止：

1. STATE 的 `branch` 字段；
2. `worktree_manager` 的 spec → 在册 worktree 事实查询（`git worktree list --porcelain` + worktree 命名约定）；
3. **git 分支命名空间枚举**：按配置 `worktree.implement_branch_prefix`（缺省 `fenix`）枚举 `refs/heads/<prefix>/<spec>-*`，候选排序规则为——先取 `main` 为其祖先者（`git merge-base --is-ancestor main <branch>` 成立，即已含 main 的合并），在此基础上取 committerdate 最新者；无「已含合并」候选时取 `git rev-list --count main..<branch>` 最大者。

命名空间枚举 MUST NOT 依赖内存表（`_active_worktrees` / `_wt_branches`），MUST NOT 因 worktree 已被清理而放弃该回落——枚举的事实源是 git refs，与 worktree 是否在册无关。

命中多个候选且无法按上述规则唯一确定时，MUST 取排序规则下的最优者并打 WARNING 列出全部候选；MUST NOT 静默取首个。

#### Scenario: worktree 已清但分支已合并 main

- **WHEN** 某 implementing spec 的 STATE.branch 为 null、无在册 worktree，但其分支 `<prefix>/<spec>-<旧ts>` 存在且 `main` 是其祖先
- **THEN** 回落命中该分支，恢复按保留续做路径命中并保留该 branch

#### Scenario: 分支尚未合并 main

- **WHEN** 某 implementing spec 的 STATE.branch 为 null、无在册 worktree，其分支存在但 `main..branch` 非空
- **THEN** 回落命中该分支，恢复保留该 branch 并按 resume 续做

#### Scenario: 多候选取最优并留痕

- **WHEN** 同一 spec 存在多个 `<prefix>/<spec>-*` 分支且均相对 main 有未合并提交
- **THEN** 取 `rev-list --count main..<branch>` 最大者，并打 WARNING 列出全部候选分支名

#### Scenario: 前缀取自配置

- **WHEN** 配置 `worktree.implement_branch_prefix` 为非 `fenix` 的值
- **THEN** 命名空间枚举使用该配置值构造匹配模式，MUST NOT 硬编码 `fenix`

#### Scenario: 无候选时不误判

- **WHEN** 命名空间枚举无任何 `<prefix>/<spec>-*` 命中，或全部候选相对 main 零提交且未被 main 包含
- **THEN** 锚点判定为不可得，走既有清空重建兼容路径

### Requirement: 锚点不可得的强制留痕

恢复链在「无任何锚点」而走清空重建路径时，MUST 打 WARNING，内容含 spec 名与命名空间枚举的命中结果（候选分支名清单，无命中则显式标注为空）。MUST NOT 以无日志的早退结束该判定——锚点缺失是重大恢复语义事件，必须有可检索的留痕。

#### Scenario: 无锚点清空重建时留痕

- **WHEN** 某 implementing spec 在 STATE.branch、在册 worktree、分支命名空间三处均无锚点
- **THEN** 日志出现 WARNING，含该 spec 名与「分支命名空间枚举：无候选」的显式结论

#### Scenario: 锚点存在但载体不可用

- **WHEN** 锚点已解析出分支名但 `is_available` 三态判定不可用
- **THEN** 在既有降级 WARNING 中一并打出该分支名与降级原因，不额外引入无锚点结论
