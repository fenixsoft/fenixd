# stash-pop-conflict-triage

## Why

**merge-back 的 WIP 重叠闸门把主树未提交改动 stash 后，merge 成功但 pop 冲突时自愈逻辑直接丢弃 stash 版——交付物静默丢失，且已有 4+ 起前例、窗口内 QualityPanel.tsx 两次丢失。**

2026-09-19 实证（本 SPEC 立项的直接触发）：add-impl-code-review-tuning 合流前 WIP 重叠闸门（policy=auto）把 6 个重叠文件收入 stash（fenixd.log 12:32:46Z），merge 后 pop 在 core/dashboard/static/src/pages/settings/components/QualityPanel.tsx 冲突（12:33:13Z「Stash pop conflict self-healed; discarded stash changes on 1 file(s)」），stash 版被丢弃，仅留 git show 7cd88ca8… 口令。该文件「周期性代码审查」开关交付物丢失，约 9 分钟后由 admin 从 stash 手工找回（978f9f65）。此前 12:17 该项目页「质量」分面开关已首丢一次；更早 09-14（SuggestedImprovementsPanel）、09-15（admin_store.py）、09-18（todo.md）同文案丢弃各一起。

根因：core/worktree_manager/stash_guard.py pop 冲突路径直接丢弃 stash 改动（仅发 stash_pop_conflict 信号唤起 admin + 保留 stash 条目供 git show 找回）——没有把 stash 版内容落回工作区的重试通道，丢失的交付物依赖人工/admin 二次介入。

本 SPEC 把「丢弃 stash 版」改为三态重试：

1. **首选 merge**：pop 冲突时用 git merge 合并 stash 版与 merge 结果（不同 hunk 自动合并，真正冲突才留标记）；
2. **次选恢复 commit**：merge 不可行时自动创建恢复 commit（stash 版内容 + 冲突标记）留审计，登记 disposition；
3. **兜底保留并登记**：两者均不可行才保留冲突文件（含冲突标记）并登记 disposition——**绝不静默丢弃**；stash 条目保留与 stash_pop_conflict 信号现有行为保持不变。