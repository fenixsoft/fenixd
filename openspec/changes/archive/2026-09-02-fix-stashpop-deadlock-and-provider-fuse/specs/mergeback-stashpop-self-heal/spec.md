## ADDED Requirements

### Requirement: stash-pop 冲突自动检测
`restore_after_merge` 执行 `git stash pop` 后，若返回码非 0 且 stderr/stdout 含 `CONFLICT`，判定为 pop 冲突，进入自愈流程（不再仅记 WARNING）。

#### Scenario: 冲突检测
- **WHEN** 主树存在由本框架 autostash 产生的 stash 条目，pop 与已推进的 HEAD 发生内容冲突
- **THEN** `restore_after_merge` 识别全部 UU 未合并文件（`git ls-files -u` stage1/2/3 条目），记录冲突并进入自愈，而不是返回 False 后留下半合并状态

### Requirement: UU 半合并状态自愈
自愈流程须将主树恢复到干净可写状态：对每个 UU 文件执行 `git checkout HEAD -- <file>`（丢弃 stash 版本，保留 merge 后的工作区版本，已 merge 的实现不丢失），随后 `git reset` 清空 index，使后续 git 写命令（stash/merge/commit）可正常执行。

#### Scenario: 自愈后主树可写
- **WHEN** pop 冲突自愈完成后，daemon 再次执行 `git stash`、`git merge --no-ff` 或提交
- **THEN** 命令均正常执行（无 `could not write index` / `unmerged files` 错误），主树无 UU 条目、index 无残留 staged 冲突

### Requirement: 冲突清单上报与 stash 保留
自愈后须向调用方返回被丢弃的 stash 改动文件清单与创建的恢复信息：调用方须将其写入该 spec 的 `error` 字段并触发 admin 告警；stash 条目须保留在 `git stash list` 中供人工 `git stash show` / `git apply` 找回，不得自动 drop。

#### Scenario: 冲突信息可追溯
- **WHEN** 某 spec 的 merge-back 发生 pop 冲突并自愈后，查看该 spec 的 STATE.md error 与 admin 告警
- **THEN** error/告警包含「stash pop 冲突」字样及受影响文件名单，且 `git stash list` 仍可见对应 stash 条目

### Requirement: 无冲突路径行为不变
主树本来干净、无本框架 stash 条目、或 pop 成功时，`restore_after_merge` 行为与现状完全一致（返回 True 或记录成功日志），不对其它 stash 条目（非本框架创建）做任何操作。

#### Scenario: 干净路径无副作用
- **WHEN** merge-back 成功且无 stash 需要恢复（或 pop 直接成功）
- **THEN** 不产生任何文件改动、不 drop 任何 stash、返回 True