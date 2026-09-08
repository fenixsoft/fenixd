# stashpop-conflict-treatment 能力规格

merge-back 过程中 `ensure_clean_tree` → merge → `restore_after_merge` 链路上，stash pop 冲突自愈后的事件必须可见（admin 告警）、被取代的 stash 条目可自动清理（drop 判据）、且冲突发生前有 WIP 重叠预警。

## ADDED Requirements

### Requirement: 冲突自愈后直发 admin 告警

pop 冲突自愈完成（UU 清空、stash 条目保留或 drop）后，dispatch 层必须直接向 admin_alerts 追加一条 `signal_type: stash_pop_conflict` 的告警记录，不得依赖 spec 的瞬态 error 字段或日志指纹风暴规则作为唯一通知渠道。

- `core/admin_monitor.py` 的 `STORED_SIGNAL_TYPES` 必须收录 `stash_pop_conflict`，`SIGNAL_SEVERITY` 给 major 级，`SIGNAL_RECOMMENDATION` 给出核对指引
- 告警 description 必须包含：spec 名、冲突文件清单、stash 条目去向（保留/drop + sha）、逐文件找回命令 `git show <sha>:<file>`（条目保留时）
- 既有 spec.error 字段写入行为保持不变（向后兼容 dashboard 时间轴读侧）

#### Scenario: 冲突自愈产生告警记录

- **WHEN** merge-back 后 `restore_after_merge` 返回非空 conflict_files 且自愈完成
- **THEN** admin_alerts.json 出现一条 `signal_type == "stash_pop_conflict"`、`spec == <spec_name>`、`handled == false` 的记录，description 含冲突文件清单

#### Scenario: 无冲突不产生告警

- **WHEN** merge-back 的 stash pop 成功（conflict_files 为空）
- **THEN** admin_alerts.json 不新增 `stash_pop_conflict` 记录，spec.error 保持 None

#### Scenario: 新信号类型被 monitor 收录

- **WHEN** admin_monitor 扫描含 `stash_pop_conflict` 的未处理告警
- **WHEN** 该类型在 `STORED_SIGNAL_TYPES` 白名单内、severity 为 major
- **THEN** 告警进入正常处置流程（admin 唤起），不被扫描过滤跳过

### Requirement: 被取代条目自动 drop

`restore_after_merge` pop 冲突自愈完成后，若 stash 条目对全部冲突文件的内容与合并后 HEAD 完全一致（树级 `git diff --quiet <sha> HEAD -- <file>` 判定），该条目零独有内容，必须自动 drop；任一冲突文件存在差异则必须保留。

- drop 前必须核对 stash sha 仍为栈顶（防并发 autostash 插队误删），sha 记入日志（gc 前可按 sha 找回）——与 reclaim_stale_autostash（4f753ed）同款防线
- 非冲突文件的 stash 改动已在 pop 时回贴工作区，不参与判定
- drop 与保留两种结局都必须在日志中明确记载

#### Scenario: 内容被取代自动 drop

- **WHEN** pop 冲突仅 1 个 UU 文件且 `git diff --quiet <stash_sha> HEAD -- <file>` 退出码 0（stash 版 == 合并后 HEAD 版）
- **THEN** 自愈完成后 `git stash list` 中该条目消失，日志记录 drop sha

#### Scenario: 内容有差异保留条目

- **WHEN** 任一 UU 文件的 stash 版与合并后 HEAD 版树级 diff 非空
- **THEN** stash 条目保留在栈中，告警 description 含该文件的找回命令

#### Scenario: sha 不在栈顶时放弃 drop

- **WHEN** 自愈完成但 `rev-parse stash@{0}` 与 pop 前钉住的 sha 不一致（期间有新条目入栈）
- **THEN** 不执行 drop，条目保留，日志记录跳过原因

### Requirement: merge-back 前 WIP 重叠预检

merge-back 在执行 stash 之前必须检测「实现分支改动文件 ∩ 主树脏 tracked 文件」的重叠集合；非空时记 WARNING 日志，并把重叠清单挂到 MergeConflictInfo 供 dispatch 并入告警文本。

- 预检为只读操作，不改变既有 stash/merge/预演闸的执行顺序与行为
- 重叠非空不阻断 merge-back（不同 hunk 可自动合并，重叠仅是预警）
- 无重叠或主树本就干净时行为与现状逐字节一致

#### Scenario: 重叠文件预警

- **WHEN** 主树存在脏 tracked 文件 core/a.py，且待合并分支的 merge-base..branch diff 也含 core/a.py
- **THEN** 日志出现含两文件名的 WARNING，MergeConflictInfo 携带该重叠清单

#### Scenario: 无重叠静默放行

- **WHEN** 主树脏文件与分支改动文件无交集
- **THEN** 不产生重叠 WARNING，merge-back 流程与现状一致
