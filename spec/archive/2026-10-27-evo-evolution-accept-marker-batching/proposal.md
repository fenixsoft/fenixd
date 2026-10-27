## Why

自进化标记回写的接受路径逐条即时提交：potplayer-base 10-06 05:50:44-46 两秒 8 提交（7×1+/1- 翻转+6ed53a8 插 9 行），fenixd 自身仓同形态两批（10-06 02:02 三连、10-07 01:41 七连），按「每轮分析有接受条目」复现，单批敞口上限 self_evolution.max_items_per_run=20。核查证实这不是「未合并入账」：ingest 批末合并提交已在工作（evo-add-todo-marker-commit-on-write，2026-10-05），风暴来自同管线第二段循环 auto_accept_pending（core/evolution.py:2108，循环体 :2125-2149）逐条 accept_item（:1526，:1793 write_todo_marker 缺省 commit=True）——存量 spec 的 design 把 accept/reject/delete 定为「单点写写后即提交」，未考虑批循环形态。「批末单次提交」的机制与范式均已存在（commit_todo_marker + core/agent_runner/maintenance_runs.py:1095-1115 批末段），只差接到 accept 循环。

## What Changes

1. accept_item 加提交开关形参（缺省不变，dashboard 手动单条路径保持即时提交）；auto_accept_pending 批末对本项目调一次 commit_todo_marker 合并提交，消息附本批条目 id 明细。
2. 显式不采纳「1-2 秒文件级合并窗口」：.fenix/todo.md 有两个生产者（evolution 与 self_review 的 _commit_todo core/self_review.py:1994）以同 pathspec 提交，时间窗去抖会把对方滞留改动卷进错误消息的提交并随 push 外泄。

## Out of Scope

- 不做 hook_engine/文件级时间去抖窗口（有跨生产者误合并实害）。
- 不改 reject/delete 单点写路径与 dashboard 手动单条路径的即时提交语义。
- 不动 ingest 批量路径（evo-add-todo-marker-commit-on-write 语义不变）。