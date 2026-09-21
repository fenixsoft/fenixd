# 验证报告：evo-stash-pop-conflict-triage

> ⚠️ 本报告由框架于 2026-09-20T20:51:59Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-20T20:51:59.080785+00:00

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.79M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| triage-state2-text-conflict-recovery-commit | 纯文本同 hunk 冲突 → 态 2 恢复 commit 落盘：stash 版内容（LOCAL\n）在恢复提交（HEAD）中可见、工作区为 stash 版、无 UU 残留、stash 条目保留、无静默丢弃（tasks 2.1）tests/test_stash_pop_conflict_triage.py:51 | pass | 0/2 | - |
| triage-state2-theirs-binary-bytes | 二进制冲突（d.bin）→ 态 2 经 --theirs 取回 stash 版字节，恢复 commit 中该文件与 stash 版字节级一致、条目保留（tasks 2.2）tests/test_stash_pop_conflict_triage.py:77 | pass | 0/2 | - |
| triage-path-scope-staged-preserved | 路径作用域不变量——预置 other.ts staged 修改，态 2 恢复 commit 只含冲突路径、other.ts 条目仍在 index 且内容未被吞并、主树 porcelain 非空属预期（tasks 2.3）tests/test_stash_pop_conflict_triage.py:116 | pass | 0/2 | - |
| triage-state3-fallback-commit-failure | 兜底路径——态 2 的 git commit 注入失败 → 态 3：stash 版内容仍在工作区、mode=3 disposition 已登记、条目保留、无静默丢弃（tasks 2.4）tests/test_stash_pop_conflict_triage.py:153 | pass | 0/2 | - |
| triage-suite-full | 三态重试全部用例套件（tasks 2.1-2.4）全量通过，确认无一回归（tests/test_stash_pop_conflict_triage.py 全文件） | pass | 0/2 | - |
| r1-stray-identical-divergent-copy | R1 回归：分歧本地修改→autostash→merge→pop 冲突经态 2 自愈，stash 版 LOCAL\n 落工作区（不再分支版胜出丢弃）、记入 last_stash_pop_conflicts、条目可找回（tasks 2.5）tests/test_worktree_stray_and_identical.py:219 | pass | 0/2 | - |
| r1-stray-identical-mixed-blockers | R1 回归：混合修改（一份与分支一致、一份分歧）→ merge 成功，一致文件干净合入、分歧文件以 stash 版 LOCAL\n 落地并记入冲突清单（tasks 2.5）tests/test_worktree_stray_and_identical.py:237 | pass | 0/2 | - |
| r1-merge-guard-restore-conflict-kept | R1 回归：真实 pop 冲突走态 2 恢复 commit 路径，冲突文件以 stash 版落地（恢复提交可见）、主树无 UU 残留、条目保留、日志含逐文件找回命令（tasks 2.6）tests/test_worktree_merge_guard.py:748 | pass | 0/2 | - |
| r1-merge-guard-superseded-drop-class | R1 回归：TestSupersededStashDrop 类全量（6 例）——恢复冲突保留条目 + 零独有内容 drop 判据 + sha 栈顶防线不被破坏（tasks 2.6）tests/test_worktree_merge_guard.py:652 | pass | 0/2 | - |
| r1-stray-identical-full-file | R1 回归全量：test_worktree_stray_and_identical.py 11 例全过（含 2 个新口径用例 + identical/discard 纵深防御，确认无回归） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 10 个（第 1 轮）。

- 首轮写入 10 个场景

