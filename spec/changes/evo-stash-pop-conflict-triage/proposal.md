# stash-pop-conflict-triage

## Why

**merge-back 的 WIP 重叠闸门把主树未提交改动 stash 后，merge 成功但 pop 冲突时自愈逻辑直接丢弃 stash 版——交付物静默丢失，且已有 4+ 起前例、窗口内 QualityPanel.tsx 两次丢失。**

2026-09-19 实证（本 SPEC 立项的直接触发）：add-impl-code-review-tuning 合流前 WIP 重叠闸门（policy=auto）把 6 个重叠文件收入 stash（`git show 7cd88ca8`），merge 后 pop 在 core/dashboard/static/src/pages/settings/components/QualityPanel.tsx 冲突——`.fenix/admin_alerts.json` 记录 974eb0ec6da3（12:33:14Z，signal_type=stash_pop_conflict）：「1 个文件的未提交改动被丢弃 (…QualityPanel.tsx)。stash 条目保留在栈中」；根目录 fenixd.log 已滚动（现仅 6 行，不含该时段，取证以 admin_alerts 记录为准）。该文件「周期性代码审查」开关交付物丢失，同日由 admin 从 stash 手工找回（978f9f65，2026-09-19 20:41 CST；其 commit message 记该文件当日 12:17 首丢、20:32 再丢）。同类前例可见 09-18 add-impl-code-review-gate 的 VerifyPanel.tsx（告警 e6dc571fb2b1 / 处置记录 a74ae0053e39）与 git 历史中的 f652d2fe（「恢复自进化面板被 autostash 冲掉的前端功能」）；`.fenix/admin_alerts.json` 现存窗口（2026-09-17..09-20）内 stash_pop_conflict 记录共 6 条。

根因：core/worktree_manager/stash_guard.py pop 冲突路径直接丢弃 stash 改动（仅发 stash_pop_conflict 信号唤起 admin + 保留 stash 条目供 git show 找回）——没有把 stash 版内容落回工作区的重试通道，丢失的交付物依赖人工/admin 二次介入。

本 SPEC 把「丢弃 stash 版」改为三态重试（作用面为 **UU 冲突文件**——非冲突文件与无冲突
hunk 在 `git stash pop`（本身就是一次三方合并）中已自动落回工作区，实测口径见 design D0）：

1. **首选双版本落盘**：对每个 UU 冲突文件做三方重试（ours=已合入 HEAD 版 / base=stash 父
   提交版 / theirs=stash 版），无冲突则写回工作区（两侧改动都保留）；纯文本同 hunk 冲突
   仍留标记（pop 已做过同样合并），此时进入态 2；
2. **次选恢复 commit（路径作用域）**：逐文件取回 stash 版（`git checkout --theirs -- <path>`，
   **不读工作区冲突标记**——二进制/非 UTF-8 文件 pop 时工作区被 merge 结果整体覆盖、无标记），
   并以 `git add -- <paths>` + `git commit --only -- <paths>` **只把本次冲突路径**入库留审计，
   登记 disposition；
3. **兜底保留并登记**：态 2 落盘或入库任一步失败时，至少保证 stash 版内容落回工作区并显式
   登记 disposition——**绝不静默丢弃**；stash 条目保留与 stash_pop_conflict 信号现有行为
   保持不变。