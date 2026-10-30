# Proposal：maintree-stray-attribution-log-dedup

## 背景

主树散件盘点器（core/worktree_manager/stray_wip.py，60 秒一轮，由 fenixd.py 周期车道驱动）在 tracked WIP 归因到主树活交互会话时打 info 留痕（481-487 行）。该留痕无状态变化检测：归因结论稳定时每轮重写同一行，5 天在单个项目日志积累 5267 条、字节占比近六成（实测 57.9%），排障必须先过滤，已实证污染唯一的全局日志。引入源为 evo-add-maintree-interactive-session-attribution（提交 e1391f13）。

## 目标

1. 会话归因留痕收敛为状态变化驱动：同文件集同占用者仅在首次与变化时落全量行。
2. 稳定期以每小时 1 条聚合行替代（含重复计数），保留「归因被探测到」的可观测性。
3. 归因解除（文件消失、升级处置接管、占用者清空）补一条解除行，闭环留痕状态机。

## 非目标

- 不改散件宽限/升级处置管线本身。
- 不新增 AdminStore signal_type（模块既有约束，见 stray_wip.py 注释），不进人工队列。
- 不做跨重启持久化：允许重启后首轮重复一条，与 tracked 流 first_seen 内存态同一取舍（stray_wip.py:28-29：D5 持久化仅取代 untracked 注册表，tracked 流维持内存态）。
- 不收敛 keep 回退态的逐轮回退说明日志（496-500 行）：缺省 action=info 不触发该行，keep 仅配置事故/人工回退保守向暂态，留待实际成为问题时另立 SPEC。

## 方案概要

MainTreeStrayWipSweeper 新增进程内留痕去重状态（上次归因键=文件集+占用者会话标识、抑制轮计数、上次留痕时间戳），_tracked_sweep_locked 会话归因分支改三态落日志。与已归档的 evo-fix-stale-code-alert-window-dedup、evo-supervisor-drift-log-dedup 同型。