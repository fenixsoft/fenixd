<!-- knowledge: capability=mergeback-stashpop-self-heal rev=2 sources=spec/archive/2026-09-02-fix-stashpop-deadlock-and-provider-fuse,spec/knowledge/_inbox/done/memory-distill-ops-runbook.md -->

# stash pop 自愈

merge-back 成功后恢复主树 WIP 时 stash pop 冲突的自愈底座：自动检出冲突、把主树恢复到干净可写状态、上报冲突清单，不留半合并死锁。

## 现行规则

- pop 冲突自动检测：`restore_after_merge` 执行 `git stash pop` 后返回码非 0 且 stderr/stdout 含 `CONFLICT` → 判定为 pop 冲突，进入自愈流程（不只是记 WARNING）；以 `git ls-files -u`（stage1/2/3 条目）识别全部 UU 未合并文件。
- 自愈目标为干净可写：冲突文件按三态处置回收 stash 版内容（现行处置契约见 stashpop-conflict-treatment 与 merge-back 能力页）；自愈完成后 `git reset` 清空 index——后续 git 写命令（stash/merge/commit）正常执行，无 `could not write index` / `unmerged files` 错误，主树无 UU 条目、index 无残留 staged 冲突。
- 冲突清单上报与条目保留：自愈后向调用方返回受影响文件清单，调用方写入该 spec 的 `error` 字段并触发 admin 告警（含「stash pop 冲突」字样及受影响文件名单）；stash 条目保留在 `git stash list` 中供人工 `git stash show` / `git apply` 找回，仅当树级证明其内容被合并结果完全取代时才自动 drop（判据见 stashpop-conflict-treatment 能力页）。
- 无冲突路径零副作用：主树本来干净、无本框架 stash 条目、或 pop 成功时，`restore_after_merge` 行为不变（返回 True 或记录成功日志），不对其它（非本框架创建的）stash 条目做任何操作。
- 悬空 autostash 人工找回配方：pre-dispatch autostash 被无守护 pop 永久滞留时，gate stash（本框架条目）查 `git stash list`；autostash 已不在栈中则 `git fsck --dangling` 找悬空 commit（筛 committer date 落事故窗口 + message 含 `pre-dispatch autostash` + parents=2）。恢复 `git diff <autostash>^1 <autostash> | git apply --3way`——`--3way` 会静默跳过部分文件（exit 0 但 22/39 被跳过实证），必须逐文件二次核对补齐（`git diff --quiet HEAD -- <file>` 未生效则 `git checkout <autostash> -- <file>`）。untracked 文件不进 stash（merge commit 只有 2 parents），只能从源头重建。找回内容落盘后立即 commit 入库，不留被清理路径再次吞掉的窗口。

## 溯源

- 2026-09-02 fix-stashpop-deadlock-and-provider-fuse（spec/archive/2026-09-02-fix-stashpop-deadlock-and-provider-fuse） — 新增 stash pop 冲突自动检测与 UU 半合并状态自愈（index 清理恢复可写、冲突清单上报 error/admin、stash 条目保留），解除 pop 冲突导致的写命令死锁（自愈中对 UU 文件的处置后经 2026-09-25 evo-stash-pop-conflict-triage 升级为三态重试）
- 2026-11-04 memory-distill-ops-runbook（spec/knowledge/_inbox/done/memory-distill-ops-runbook.md） — 折叠悬空 autostash 人工找回配方（fsck 悬空 commit 筛选、--3way 静默跳过陷阱逐文件核对、untracked 不进 stash、找回即 commit）
