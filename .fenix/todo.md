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


## 2026-09-05

### 浪费
- 证据：（新增）当日管线零活动（121/121 pushed、0 run、0 ERROR、0 告警），本次回顾 run review-2026-09-05 于 local 09-05 02:04（UTC 09-04T18:04:32Z）启动，聚合窗口仅覆盖当天前 2 小时、产出近乎空报告；而 09-04 唯一一次回顾在 11:19:39+08:00 执行（.fenix/self_review_state.json），其证据止于 local 11:13——09-04 11:19 之后的 5 个 run（impl-add-activities-pagination×3 于 16:08/18:11/20:12 结束、add-dashboard-help-center planner-plan/impl/planner-judge 21:25–22:07）与 4 个 merge 提交（ade86ea 20:12、52e0a9d 21:33、2523281/901e8c3 23:27）从未进入任何回顾。建议：把自省调度移到「当日末」或让凌晨执行时聚合上一日全天，详见可改进第 1 条；在此之前今日回顾对昨日午后的覆盖缺口需人工补看。

### 失误
- 证据：（新增）main 工作区滞留 5 个文件 229 行未提交改动（core/dashboard/data.py、core/dashboard/server.py、SelfReviewPanel.tsx、settings/index.tsx、services/dashboard.ts）加未跟踪 tests/test_dashboard_todo_api.py，mtime 09-04 23:37–23:42，晚于当日最后 run（22:07）与最后提交（b3d75c9 23:35），且无任何 branch/run/STATE 条目对应（当日 0 run、121 条 SPEC 全部 pushed）——实现成果游离于分支、merge-back 与验证链路之外；这已是第二次：距上次手工同步提交 1f4ff86（09-04 11:04「同步主树未提交工作区」）仅约 12 小时再度积累。根因：改动未走 spec 分支流程，框架对 main 工作区残留无检测与告警。建议：先核对这批改动的归属——属某 spec 范畴则走 fast-track 补提交入管线并补验证，非 spec 范畴立即提交并注明来源；系统性上立项「main 工作区漂移检测」（见可改进第 2 条）。

### 可改进
- 证据：（新增）自省默认 02:00 执行（1f4ff86「自省默认时间 02:00」）且按执行日命名：09-05 回顾 02:04 跑、窗口仅 2 小时（run=0）；09-04 回顾 11:19 跑、只覆盖上午，午后 5 个 run 与 4 个 merge 提交成盲区。建议：立项 SPEC——自省调度移至每日 23:30–23:59，或次日凌晨执行但按「聚合窗口 D-1 全天」过滤 runs/日志/告警，并在 self_review_state.json 落窗口起止时间与覆盖 run 数，窗口错位时自动补扫。
- 证据：（新增）main 工作区再次出现无归属的未提交实现（见失误条目），且无任何机制发现——框架只盯 SPEC 状态，工作区脏度不进 admin 信号。建议：立项 SPEC——daemon 周期检测 main 工作区未提交/未跟踪文件并按「来源未知改动」产生 admin 告警，提示提交、入 fast-track 或清理，防成果无声丢失。
- 证据：（未复现，仍未闭环）core/config.py:389–392 对 agents.models 未知键仍硬抛 ValueError（昨日 02:35–03:00Z 连发 50 条 ERROR、热更新 25 分钟不可用），今日 0 ERROR 未复现但代码未改、SPEC 未立项。建议：照昨日建议立项——热重载遇未知键降级为 WARNING 并跳过该键、其余配置照常应用，同时检测磁盘白名单与进程内不一致并提示需重启。
- 证据：（未复现，仍未闭环）state_machine.recover_interrupted 对 implementing 仍整段清空 implementer_run/branch（core/state_machine.py:628–640，branch: None 在 635），worktree_manager.py:651 仍按 orphan 清理 worktree——昨日 add-run-cancel 首轮 19 分钟成果整轮蒸发、resume 秒挂的路径原样存在；今日 0 run 未复现。建议：照昨日建议立项——recovery 保留分支与 worktree 引用、resume 派发前校验存在性，仅确认零提交才走新建。
- 证据：（未复现，仍未闭环）admin_monitor.py:36 DAEMON_ERROR_THRESHOLD=3 且按扫描节拍触发，昨日同一条 Config hot-reload ERROR 从 02:35:54Z 首现到 02:45:23Z 才升级 critical（滞后约 10 分钟、6 连发），今日 0 ERROR 未复现但阈值与去重逻辑未改。建议：照昨日建议立项——按错误指纹去重计数，同条错误复现第 2 次即升级，并缩短 ERROR 聚合扫描间隔。
