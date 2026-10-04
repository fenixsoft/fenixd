## 方案

参照 core/self_review.py:1974 _commit_todo 的既有形态（git add -- .fenix/todo.md → commit → push），把提交动作放进 core/evolution.py write_todo_marker() 的写入成功分支：

- 先以 git ls-files 判定 todo.md 是否 tracked，未 tracked 直接跳过提交（行为与现状一致）。
- accept / reject / delete 三个单点写路径复用同一提交动作；ingest_item 的批量落条目由编排层（core/agent_runner/maintenance_runs.py 一轮 ingest 循环结束后）触发一次合并提交，避免逐条提交风暴。
- 提交失败捕获异常降级为日志留痕，不向调用方抛错、不回滚写入；不做自动重试（下一次写入自然再试）。

## 权衡

- 每轮多一枚小提交：与 ADR-060 取舍一致，换取滞留盘点指纹归零与 admin 车道零消耗（对照 2026-10-04 d8c60d9 案例约 4 分钟 run）。
- 不做后台定时/批量提交：即时性是告警消除的必要条件（盘点宽限仅 30 分钟，写入后 49 秒即被看到）。