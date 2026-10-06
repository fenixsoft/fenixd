## Why

同一 tracked 构建日志（build-win-configure.log）三天内两度触发 maintree_stray_wip_stale 并各烧一条 admin 处置 run（10-04 run admin-potplayer-base-1791048866 实测 $0.78/12 轮、10-06 run admin-potplayer-base-1791275605 实测 $0.92/11 轮/约 7 分钟）；10-04 处置正文（commit 5935771）已逐字写明根治方案（git rm --cached + .gitignore）却以「留给人类决策，本次不擅动」收尾，无人值守框架里该决策不会到来，10-06 原样复发（commit 95a0c01 循先例再入库）。且 potplayer-base 10-04 自省已把同主题条目标「✓ 值得立项 · 处理：接受」（.fenix/todo.md:105-111），挂账三天无人落 SPEC——被动挂账与「留给人类」同样不被消费。框架现状：检测→告警→一键提交闭环齐全（evo-add-maintree-stray-wip-sweep 检测、evo-add-commit-stray-wip-choice 一键提交），唯独缺「复发→根治」一环：裁决空间 maintree 桶只有 commit 一项（core/dashboard/data/adjudication_choices.py:101-108），admin 处置契约（agents/administrator.md）对主树散件根治只字未提，告警也不携带复发计数。

## What Changes

1. 裁决空间扩 untrack：maintree 散件桶新增 UNTRACK_STRAY_WIP 一键选项与执行器——对告警指认文件执行 git rm --cached、.gitignore 追加（去重）、独立提交，复用 core/worktree_manager/stash_guard.py 的 staged 子集守卫/回滚骨架（不打开其「check-ignore 全须忽略」前置门）。
2. 复发识别与根治强制：散件告警检索同文件历史处置并在 evidence 带出「已 N 度处置」计数与根治指引；admin 处置契约（agents/administrator.md 铁律区）新增——复发型散件（同文件第 2 次处置起）必须当场执行根治或显式挂账，禁止第三次循「仅提交」收尾；首次处置维持「提交+建议」现状。

## Out of Scope

- 不改 maintree_stray_wip_stale 的检测与触发逻辑（evo-add-maintree-stray-wip-sweep 语义不动，盘点仍无写副作用）。
- 不做 stash/discard 类姊妹处置项（沿 evo-add-commit-stray-wip-choice 非目标）。
- 不修改 stash_guard 既有「check-ignore 全须忽略」前置门（扩其暴露面风险另评，本 SPEC 用独立执行器复用其子函数）。
- 首个根治对象（potplayer-base 的 build-win-configure.log）由新 untrack 选项在下一次告警处置时执行，不在本 SPEC 内跨仓改动。