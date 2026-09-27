# 修复必须落提交的强制门

<!-- knowledge: capability=repair-commit-enforcement rev=1
     sources=spec/archive/2026-09-21-fix-repair-commit-enforcement -->

merge-back 冲突 repair 的完成判定以分支 git 事实为准，「提交」是 repair 的强制终点。

## 规则

- repair agent 报告 success 后，框架在消费结果、进入 re-merge-back 之前，以分支的 git 事实复核 repair 是否真正完成，复核至少三项：① 分支 tip 相对 repair 派发前已前进（存在至少一个新提交）；② 实现分支 worktree 内无未解决冲突（`git ls-files -u` 为空，且 git 认可无冲突标记残留）；③ 该 worktree 不处于未完成 merge 状态（无 `MERGE_HEAD`）。任一项不满足判 repair 未完成：不进入 re-merge-back，走 repair 链回退路径（fallback 全新重派）。
- 因 git 事实复核未通过而回退时，注入下一轮重派的 merge 失败上下文必须包含具体未完成事实（如「分支无新提交」「存在未解决冲突」「存在未完成 merge」），不得仅以笼统的 merge-back 失败原因重派。
- repair prompt 把「合并 → 解决冲突 → 提交」定为在测试之前必须完成的强制终点，不得允许 repair agent 在跑完测试（尤其全量套件）之后才决定是否提交；测试无法在窗口内跑完时仍必须提交已解决的合并，并在结论文本中如实标注未跑完的验证边界。
- repair 测试范围收敛为「本次合并触及文件的定向回归 + 有界超时」，不得要求以跑完项目全量套件作为提交前提。
- repair agent 开工第一步检测 worktree 是否残留上一轮未完成的 merge（存在 `MERGE_HEAD`）：存在则先 merge abort 复位到当前分支干净 tip，再重新执行合入 main，不得把半成品合并现场当作本轮起点；无残留则直接在当前分支 tip 开工。

## 溯源

- 2026-09-21 2026-09-21-fix-repair-commit-enforcement — 新建本页：repair 成功以分支 git 事实三复核为准、回退上下文注入具体未完成事实、提交先于测试的强制终点、测试范围收敛定向回归、开场清理残留 merge 现场。
