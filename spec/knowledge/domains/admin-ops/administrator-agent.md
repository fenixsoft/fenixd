<!-- knowledge: capability=administrator-agent rev=2 sources=spec/archive/2026-09-02-add-administrator-agent,spec/archive/2026-09-08-fix-admin-run-blocks-mainloop -->

# Administrator 自愈管理员 Agent

按需唤起的高级权限自愈 agent：处置 Agent 无法脱困的困境，仅处置不开发。

## 现行规则

- 唤起条件：健康监视器检测到困境信号且节流通过时唤起 Administrator（`claude -p` 子进程，`--permission-mode bypassPermissions`，`--output-format stream-json`）；无困境不唤起、零 LLM 成本。prompt 包含困境信号详情、可用高级处置手段与「仅处置困境、不开发功能」约束；自愈不终结在飞链路时不重复唤起。
- 执行模型：唤起与处置执行和 daemon 主循环解耦——主循环只负责拾取手动唤起请求与自动巡检信号并投递后台 worker 池，处置在 worker 中执行；主循环以 1 秒粒度继续 SPEC 派发、巡检与后续请求拾取，不因处置（单次可达数分钟）阻塞。
- 并行多实例：多个 Administrator run 可同时执行；仍在主树操作、不建 worktree（主树写冲突风险已评估并容忍）；worker 数量可配置（默认 2），不无界扩张，超出部分按到达顺序在队列等待。
- 处置状态文件按实例分离：`.fenix/admin_disposition-<run_id>.json`，每个实例 clear/write/read 仅作用自身文件，提示词中指示的写入路径按 run 注入；单 run 结束（读自身 disposition 落 final 记录）后清理自己的实例文件。
- 高级处置权限：杀死/重启卡死的 Agent 子进程与 fenixd 本身；git 清理（worktree prune/stash/reset）与 commit；修改 Fenixd 自身代码并提交（直接主树操作）；发起新 SPEC（创建 spec/changes/<name>/ 并注册 STATE.md）；重置/修复 spec 状态（update_spec 到 ready/blocked 等）。
- 落痕语义：唤起前落 pending disposition，结束后按 run_id 关联落 final disposition；`invoke_manual` 异常路径落 failed disposition 与升级告警，记录不因后台执行而丢失；worker 线程不因单次处置异常退出，继续领取队列后续请求。admin_alerts.json 是唯一聚合出口（watcher 监听点不变）。
- 处置留痕：每次处置（时间、spec、问题、处置动作、结果）写入 `.fenix/admin_alerts.json`，供 Dashboard 与人类追溯；run 产物与其他 agent 一样写入 `.fenix/runs/`。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：Administrator 为自愈 agent，健康监视器按需唤起，处置产出叙述总结与运维记录；自愈不终结在飞链路时不得重复唤起
- 2026-09-02 add-administrator-agent — 固化按需唤起契约、高级处置权限清单与处置留痕
- 2026-09-08 fix-admin-run-blocks-mainloop — 执行模型改后台 worker 池并行：主循环解耦、disposition 状态文件按 run 实例分离、落痕语义保持不变
