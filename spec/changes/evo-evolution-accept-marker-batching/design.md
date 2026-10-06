## Context

core/evolution.py accept_item :1526（回写点 :1793 write_todo_marker(rec, disposition=…) 缺省 commit=True）；auto_accept_pending :2108（循环体 :2125-2149 逐条调用）；批末合并机制已有：commit_todo_marker（_commit_todo_marker :932，支持自定义消息后缀）与编排层批末提交范式 core/agent_runner/maintenance_runs.py:1095-1115；ingest 侧批量合并回归 tests/test_evolution_todo_marker_commit.py（test_ingest_pending_batch_defers_commit，a33d73d7）。共用文件生产者：core/self_review.py:1994 _commit_todo 以同 pathspec（git commit -- .fenix/todo.md）不同消息提交。dashboard 手动路径 core/dashboard/routes/evolution_routes.py:137。实证：potplayer-base 10-06 05:50:44-46 八连提交；fenixd 仓 10-06 三连/10-07 七连。

## Goals / Non-Goals

- Goals：接受批的提交数从 O(条目数) 降为 1；消息可审计（条目 id 明细）；零跨生产者风险。
- Non-Goals：不做时间窗去抖；不改 reject/delete 与 dashboard 手动路径；不动 ingest 批量路径。

## Decisions

- D1 生产者-scoped 批末收集而非文件级合并窗口：self_review 共用同 pathspec，时间窗会把对方滞留改动卷进错误消息的提交并随 push 外泄（实害）；批末收集沿 ingest 侧与 maintenance_runs 既有范式，作用面限于本循环自己的写入。
- D2 accept_item 加 defer_commit 开关、缺省不变：存量 spec（evo-add-todo-marker-commit-on-write）对单点写「写后即提交」的显式决策对 reject/delete/手动路径继续成立，只有批循环消费方显式声明 defer。
- D3 消息附条目 id 明细：合并提交丢失逐条边界，明细保证 git 历史仍可对账到条目（_commit_todo_marker 已支持自定义消息后缀，改动极小）。

## Risks / Trade-offs

- 批中途中断（daemon 被杀）时已写标记未提交：与 ingest 侧批量路径同样的窗口，todo.md 状态与 git 提交解耦、下轮扫描以文件为准，既有恢复/盘点流程已覆盖。
- 合并提交消息变长：明细行数与条目数线性，可接受。