<!-- knowledge: capability=administrator-agent rev=5 sources=spec/archive/2026-09-02-add-administrator-agent,spec/archive/2026-09-08-fix-admin-run-blocks-mainloop,spec/archive/2026-09-29-evo-alert-noise-governance,spec/archive/2026-10-15-evo-add-admin-run-wrapup-contract,spec/archive/2026-10-26-evo-add-night-window-inflight-guard -->

# Administrator 自愈管理员 Agent

按需唤起的高级权限自愈 agent：处置 Agent 无法脱困的困境，仅处置不开发。

## 现行规则

- 唤起条件：健康监视器检测到困境信号且节流通过时唤起 Administrator（`claude -p` 子进程，`--permission-mode bypassPermissions`，`--output-format stream-json`）；无困境不唤起、零 LLM 成本。prompt 包含困境信号详情、可用高级处置手段与「仅处置困境、不开发功能」约束；自愈不终结在飞链路时不重复唤起。
- 夹具项目自动召唤抑制：各自动检测路径的召唤决策点对 fixture 标记项目抑制自动召唤 Administrator（含全局巡检类 admin-global run），抑制决策记 INFO 留痕（含错误指纹与抑制原因）。抑制判定位于各自动调用点、先于共用唤起入口——人工显式触发与自动检测共用该入口，抑制 MUST NOT 收进共用唤起入口本体，人工显式触发的管理员 run 不受限。抑制不修改/删除告警记录（存储信号路径先按既有语义 mark escalated 消费「写入即待唤起」，防每轮重复摄取与重复留痕，记录保留可查），仅召唤动作被阻断。标记读取失败或项目未标记一律按非夹具处理（fail-open），不因标记异常让召唤通道失效。
- 唤起避让闸门：provider 瞬断冻结态或夜间静默窗期内，共用唤起入口跳过本轮唤起，自动检测与人工显式触发同政策；本轮跳过仅记 INFO 留痕跳过原因，留待下一轮盘点重新评估，窗外正常信号的唤起行为不受影响。跳过属非失败路径：MUST NOT 增 retry_count、MUST NOT 落升级告警。
- 避让闸落点与抑制分野：保护类避让闸（瞬断冻结/静默窗）收在共用唤起入口本体（与信号死法冷却同位）且覆盖人工通道——断窗/冻结期内人工唤起同样必死；抑制类判定（夹具项目抑制）留在各自动调用点、不上收本体且人工显式触发不受限。静默窗与 code-fix 车道共用同一配置键与窗解析（[codefix-night-quiet-window](../code-fix-lane/codefix-night-quiet-window.md)），不设第二份窗配置。
- 执行模型：唤起与处置执行和 daemon 主循环解耦——主循环只负责拾取手动唤起请求与自动巡检信号并投递后台 worker 池，处置在 worker 中执行；主循环以 1 秒粒度继续 SPEC 派发、巡检与后续请求拾取，不因处置（单次可达数分钟）阻塞。
- 并行多实例：多个 Administrator run 可同时执行；仍在主树操作、不建 worktree（主树写冲突风险已评估并容忍）；worker 数量可配置（默认 2），不无界扩张，超出部分按到达顺序在队列等待。
- 处置状态文件按实例分离：`.fenix/admin_disposition-<run_id>.json`，每个实例 clear/write/read 仅作用自身文件，提示词中指示的写入路径按 run 注入；单 run 结束（读自身 disposition 落 final 记录）后清理自己的实例文件。
- 高级处置权限：杀死/重启卡死的 Agent 子进程与 fenixd 本身；git 清理（worktree prune/stash/reset）与 commit；修改 Fenixd 自身代码并提交（直接主树操作）；发起新 SPEC（创建 spec/changes/<name>/ 并注册 STATE.md）；重置/修复 spec 状态（update_spec 到 ready/blocked 等）。
- 落痕语义：唤起前落 pending disposition，结束后按 run_id 关联落 final disposition；`invoke_manual` 异常路径落 failed disposition 与升级告警，记录不因后台执行而丢失；worker 线程不因单次处置异常退出，继续领取队列后续请求。admin_alerts.json 是唯一聚合出口（watcher 监听点不变）。
- 处置留痕：每次处置（时间、spec、问题、处置动作、结果）写入 `.fenix/admin_alerts.json`，供 Dashboard 与人类追溯；run 产物与其他 agent 一样写入 `.fenix/runs/`。
- 收尾次序硬契约：诊断闭环判定后 MUST 先覆盖写最终处置记录，再执行环境恢复/清理/重启等长动作；自建任务全部 completed 后 MUST NOT 开启新一轮诊断实验；最终处置记录不得留作最后一个动作。预算封顶时的收尾宽限配套见 [admin-run-wrapup-contract](admin-run-wrapup-contract.md)。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：Administrator 为自愈 agent，健康监视器按需唤起，处置产出叙述总结与运维记录；自愈不终结在飞链路时不得重复唤起
- 2026-09-02 add-administrator-agent（spec/archive/2026-09-02-add-administrator-agent） — 固化按需唤起契约、高级处置权限清单与处置留痕
- 2026-09-08 fix-admin-run-blocks-mainloop（spec/archive/2026-09-08-fix-admin-run-blocks-mainloop） — 执行模型改后台 worker 池并行：主循环解耦、disposition 状态文件按 run 实例分离、落痕语义保持不变
- 2026-09-29 2026-09-29-evo-alert-noise-governance（spec/archive/2026-09-29-evo-alert-noise-governance） — 自动召唤通道新增夹具项目抑制：fixture 标记项目的升级信号不再自动召唤 Administrator（INFO 留痕、告警记录保留、人工显式触发不受限、判定 fail-open）
- 2026-10-15 evo-add-admin-run-wrapup-contract（spec/archive/2026-10-15-evo-add-admin-run-wrapup-contract） — 提示词新增收尾次序三条硬契约（闭环先落终稿、任务清零禁开新实验、终稿不得留作最后动作）
- 2026-10-26 evo-add-night-window-inflight-guard（spec/archive/2026-10-26-evo-add-night-window-inflight-guard） — 唤起入口新增两不派避让闸（provider 瞬断冻结态、夜间静默窗）：自动与人工同政策、跳过非失败路径（不增 retry_count、不落升级告警、INFO 留痕）、闸收本体与夹具抑制分野、窗配置复用 code-fix 静默窗
