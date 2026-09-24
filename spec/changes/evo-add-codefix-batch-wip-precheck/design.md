# Design: code-fix 选批前 WIP 重叠预检

## 现状与关键事实

- 选批点：core/code_fix.py CodeFixExecutor.checkpoint（def 于 :1039）内 select_batch（:1175-1179，排除失败档案、chain_skipped 与 defer 台账）之后直接进入契约守卫（:1228）与批 worker 投递（:1270 置单飞），全程无主树脏文件检查。
- 脏文件提取 helper 已存在：G6StashGuardMixin._list_dirty_tracked_files（core/worktree_manager/stash_guard.py:23，mergeback.py:466 在用）。
- 产物判别口径已存在：core/worktree_manager/mergeback.py:274-324 的 artifacts 切分——merge-time 闸门已排除产物重叠，选批预检必须同口径，否则比现状倒退。
- defer 重试点在选批之前：_process_deferred_merges（core/code_fix.py:1110/1389，挂选批前节拍），与新预检无冲突。
- 既有收敛出口可复用：「选批为空」按排除来源分流的 reason 文案体系（core/code_fix.py:1180-1225）。

## 设计

1. 预检插入点：select_batch 之后、契约守卫之前。取 _list_dirty_tracked_files 与 {rec.get("file") for rec in batch} 求交；台账条目 file 为仓库相对路径（items.jsonl 实证），可直接比对。
2. 产物豁免：交集先经 mergeback 同款 artifacts 判别过滤，dist 类产物路径不计入命中。
3. 推迟出口：命中即 write_progress(running=False, phase="blocked", reason="wip_overlap_at_select", current=交集文件文案) 并返回未触发；reason 纳入既有分流体系供前端透传，WIP 永不清理时落入既有 defer/预算降级语义而非无限重查。
4. 人工侧约定（非代码）：UI 会话触碰台账相关文件后及时提交或 stash——写入 proposal 非目标与 docs，不设框架强制。

## 风险与边界

- 产物判别必须与 merge-time 同口径，否则对 dist 产物脏文件整批误推迟（比现状倒退）。
- 预检只覆盖台账 file 字段与脏文件交集：agent 实际改动可能超出条目 file，merge-time 闸门与 defer 路径不可拆。
- 边际收益定位：事后 defer 已把代价从「整批作废+重跑」降为「保留现场、只补 merge」；预检的增量是再省掉被 defer 那一批的 agent run 与一轮回归（实测每批约 30–52 分钟 agent + 约 4.3 分钟回归），属低成本锦上添花。
