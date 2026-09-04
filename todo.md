## 2026-09-04

### 浪费
- 证据：add-run-cancel 首轮实现 run impl-add-run-cancel-1788489728（02:42:08Z 起，约 19 分钟、3.5MB 转录）在 03:01:02Z daemon 重启时被 SIGTERM，recovery 将 branch 置 null、worktree 按 orphan 清理，成果整体废弃后重派（现役 run 1788490880 从零开始，截至 03:13Z 仍在跑）；建议：重启 daemon 前先核对在跑 run——要么等其终态、要么先落盘分支/worktree 引用再重启，避免运行中实现成果整轮蒸发。

### 失误
- 证据：fenixd.log 02:35:54–03:00:32Z 每 30 秒一条 "Config hot-reload failed: agents.models key 'fast-track' is not a known agent type" 共实测 50 条（框架聚合 53），触发 critical 告警 47c17c728e2c 并升级 admin 处置（run admin-global-1788489923），最终靠 03:01Z 重启 daemon 才闭环；根因是运行中 daemon（02:30:23Z 启动）仍持旧版 KNOWN_AGENT_TYPES 白名单，修复 64d1086 直到本地 10:47:37 才提交且进程未重启；建议：凡改动 agent 类型白名单等需重启生效的代码，提交后立即重启 daemon。
- 证据：01:19:09Z task-track 首轮 run 合并分支 fenix/task-track-1788482892 时 core/dashboard/data.py 内容冲突（merge-back failed, fp=3cf770823ad5），被迫二轮 re-dispatch（01:19:10–01:51:44Z），spec 全程 total_duration 3811s、2 次 impl run、16.1M input tokens、$4.60，01:51:56Z 还有一次 push 因远端 main 前移被拒后自愈；根因是 main 侧 dashboard 系列提交与 spec 分支并行修改同一文件；建议：fast-track 收尾合并前先对 main 做预合并/预演，把冲突暴露在 run 内解决。
- 证据：03:01:03Z recovery 清理 worktree impl-add-run-cancel-1788489728（Cleaning up orphan）之后，03:01:13Z attempt-2 resume 仍复用该已删除路径，claude 以 [Errno 2] No such file or directory 秒挂（存活 0s，秒挂 1/3，tokens 计 0）；根因是恢复清理与 resume 复用两条链路对同一 worktree 的处置不一致；建议：resume 派发前校验 worktree/分支存在性，缺失即改走新建分支路径。

### 可改进
- 证据：热重载对 agents.models.fast-track 未知键整段拒绝（02:35–03:00Z 连发 50 条 ERROR，模型分配热更新 25 分钟不可用）；建议：立项 SPEC——热重载遇未知键降级为 WARNING 并跳过该键、其余配置照常应用，同时在热重载时检测「磁盘代码白名单与进程内不一致」并提示需重启。
- 证据：同一 ERROR 以 30 秒间隔连发，02:35:54Z 首条出现，直到 02:45:23Z（连续 6 条）才产生 critical 告警 47c17c728e2c，滞后约 10 分钟；建议：daemon_errors 告警对同类重复 ERROR 做去重计数，同一条错误复现第 2 次即升级，缩短无人介入窗口。
- 证据：被 SIGTERM 中断的 add-run-cancel run 分支引用被重置（03:01:20Z "Recovering interrupted SPEC" 将 branch 置 null、retry_count 清零）且 worktree 被清，首轮已做工作无法续做；建议：立项 SPEC「中断恢复保留分支」——recovery 保留已有分支与 worktree 引用并从 resume 续做，仅确认零提交时才走新建。
- 证据：task-track 两轮 run 结束均需事后补杀游离 worktree 进程（01:19:09Z 杀 1 个 PID、01:51:45Z 杀 3 个 PID），且每轮 run 都新起 dev-server（端口 19007/19008/19001）；建议：agent 进入终态时同步收割整个子进程树并按 spec 复用 dev-server，避免游离进程与后续 run 抢占同一工作区。
