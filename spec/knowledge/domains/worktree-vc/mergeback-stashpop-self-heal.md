<!-- knowledge: capability=mergeback-stashpop-self-heal rev=1 sources=spec/archive/2026-09-02-fix-stashpop-deadlock-and-provider-fuse -->

# stash pop 自愈

merge-back 成功后恢复主树 WIP 时 stash pop 冲突的自愈底座：自动检出冲突、把主树恢复到干净可写状态、上报冲突清单，不留半合并死锁。

## 现行规则

- pop 冲突自动检测：`restore_after_merge` 执行 `git stash pop` 后返回码非 0 且 stderr/stdout 含 `CONFLICT` → 判定为 pop 冲突，进入自愈流程（不只是记 WARNING）；以 `git ls-files -u`（stage1/2/3 条目）识别全部 UU 未合并文件。
- 自愈目标为干净可写：冲突文件按三态处置回收 stash 版内容（现行处置契约见 stashpop-conflict-treatment 与 merge-back 能力页）；自愈完成后 `git reset` 清空 index——后续 git 写命令（stash/merge/commit）正常执行，无 `could not write index` / `unmerged files` 错误，主树无 UU 条目、index 无残留 staged 冲突。
- 冲突清单上报与条目保留：自愈后向调用方返回受影响文件清单，调用方写入该 spec 的 `error` 字段并触发 admin 告警（含「stash pop 冲突」字样及受影响文件名单）；stash 条目保留在 `git stash list` 中供人工 `git stash show` / `git apply` 找回，仅当树级证明其内容被合并结果完全取代时才自动 drop（判据见 stashpop-conflict-treatment 能力页）。
- 无冲突路径零副作用：主树本来干净、无本框架 stash 条目、或 pop 成功时，`restore_after_merge` 行为不变（返回 True 或记录成功日志），不对其它（非本框架创建的）stash 条目做任何操作。

## 溯源

- 2026-09-02 fix-stashpop-deadlock-and-provider-fuse（spec/archive/2026-09-02-fix-stashpop-deadlock-and-provider-fuse） — 新增 stash pop 冲突自动检测与 UU 半合并状态自愈（index 清理恢复可写、冲突清单上报 error/admin、stash 条目保留），解除 pop 冲突导致的写命令死锁（自愈中对 UU 文件的处置后经 2026-09-25 evo-stash-pop-conflict-triage 升级为三态重试）
