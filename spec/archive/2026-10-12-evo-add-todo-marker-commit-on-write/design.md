## 方案

参照 core/self_review.py:1974 _commit_todo 的既有形态（git add -- .fenix/todo.md → commit → push），把提交动作放进 core/evolution.py write_todo_marker() 的写入成功分支：

- 先以 git ls-files 判定 todo.md 是否 tracked（ls-files 本身非零退出——如目录不是 git 仓库——同视为未 tracked 跳过），未 tracked 直接跳过提交（行为与现状一致）。
- 提交动作实现为 core/evolution.py 内独立函数（如 `_commit_todo_marker(proot)`），`write_todo_marker()` 增加提交开关参数（缺省开）；**ingest_item 内部 4 处调用（evolution.py:1141/1150/1165/1170）必须传关闭**，否则批量路径退化为逐条提交风暴。accept / reject / delete 三个单点写路径（evolution.py:1648/1729/1778）保持开关缺省开、写后即提交；ingest_item 的批量落条目由编排层（core/agent_runner/maintenance_runs.py 一轮 ingest 循环结束后）对**本轮涉及的项目集合按项目各触发一次**合并提交（write_todo_marker 按条目 project 名经 registry 解析目标项目，一轮可涉及多个项目，不存在跨项目单提交），避免逐条提交风暴。
- 提交命令形态与 _commit_todo 一致：`git add -- .fenix/todo.md` 与 **同样带 pathspec 限定的** `git commit -- .fenix/todo.md`——commit 不带 pathspec 会把索引里并发暂存的其他内容（merge-back、交付物守卫等自动化产物）卷进本提交并随 push 外泄（self_review._commit_todo 注释明言此防护，本仓库两类自动化均活跃）。
- 提交动作在 todo.md 的 flock 释放后执行：write_todo_marker 的读-改-写全程持 `.<name>.lock`（code_fix.py:1243 锁契约），git 子命令（各 30s 超时）不得放入锁内，避免拉长持锁窗口阻塞 code_fix / self_review 的并发追加。
- 提交信息遵循仓库惯例，形如 `[fenix] evolution: 自进化标记回写 <date>`；push 跟随 _commit_todo 既有形态，push 失败降级 WARNING 不重试。
- 提交失败（含 index.lock 竞争）捕获异常降级为日志留痕，不向调用方抛错、不回滚写入；不做自动重试（下一次写入自然再试）。

## 权衡

- 每轮多一枚小提交：与 ADR-060 取舍一致，换取滞留盘点指纹归零与 admin 车道零消耗（对照 2026-10-04 d8c60d9 案例约 4 分钟 run）。
- 不做后台定时/批量提交：即时性是告警消除的必要条件（盘点宽限仅 30 分钟，写入后 49 秒即被看到）。