<!-- knowledge: capability=stale-code-selfheal rev=3 sources=spec/archive/2026-09-18-add-framework-self-evolution,spec/archive/2026-09-18-add-stale-code-selfheal,spec/archive/2026-09-25-fix-state-atomicity-and-selfheal-restart -->

# 代码陈旧自愈

daemon 进程持旧代码的持续状态检测与告警、空闲感知的优雅重启自愈、supervisor 启动失败熔断——「改代码 → 空闲 → 新代码生效」闭环。

## 现行规则

- 陈旧检测为持续状态：daemon 每个检测周期（既有 30s 配置热更新检测点）重新比对 `fenixd.py` 与 `core/**/*.py` 的最大 mtime 与进程启动时记录的 baseline，维护陈旧状态；陈旧期间每个周期都保持该状态，不在首次命中后永久静默。
- 陈旧告警：状态边沿（假→真）时经 AdminStore 写入一条 `signal_type: stale_code`、`severity: warning` 的 escalation 告警，描述说明「daemon 进程持旧代码，自愈将在连续空闲后触发重启」；写入即自动标记已处理（handled=true），不进入人工告警横幅/待处理队列，仅作历史记录保留。单个陈旧周期内不重复堆积；状态转假不产生新的陈旧告警；自愈重启后磁盘未再变化则状态为假、不再告警也不再触发自愈。
- 空闲判定（三源合取，任一来源非空即非空闲）：① `agent_runner` 无活跃 run（覆盖 planner/implementer/verifier/judge 全部 run 形态）；② 不存在任何未收口的在飞评审 run——含转录因 API 重试/停滞而暂不增长的 run，以「`reviewer_run` 锚点存在且该 run 尚在飞」判定（`PMEngine.is_review_in_flight` + `LivenessSupervisor.reviewer_in_flight` 双判据合取，与派发守卫同口径）；③ admin 处置 worker 池无在途任务。
- 在飞评审判定以进程存活（daemon 进程内 run 注册表）为主判据、run 流文件为兜底；不以「转录是否仍在增长」作在飞依据（停滞 run 的转录本就不增长）。对确已收口或已死亡的 run（进程表无记录且流文件末行已终态），不得使其永久占据「非空闲」——陈旧锚点判为无在飞评审，自愈在真正空闲时仍能触发。判定复用既有内部状态，不通过扫描外部进程列表（ps / /proc 遍历）反推。
- 自愈触发：陈旧状态为真、`stale_code_selfheal.enabled` 为真、项目存在活跃 supervisor 托管三条件齐备时判定空闲；连续空闲达 `idle_confirm_seconds`（缺省 120 秒）后写入 `.fenix/restart_request`（复用既有 supervisor 优雅重启协议，不引入新信号、不改协议语义），日志记录触发原因与等待时长。空闲计时在任一非空闲信号出现时立即清零；`.fenix/restart_request` 已存在时不重复写入、不产生重复日志。
- 边界：托管态 `unmanaged`（daemon 在跑但无 supervisor）不自愈——不写 restart_request（写了无人消费），陈旧告警维持，等待经 Dashboard「安装托管」或 `/fenix-setup` 恢复托管；`enabled: false` 时不写 restart_request，但陈旧状态与告警仍产生，日志明示自愈已被配置关闭。
- 配置节 `stale_code_selfheal`：`enabled`（布尔，缺省 true）与 `idle_confirm_seconds`（整数秒，缺省 120）；配置缺失或键非法回退缺省值、不使 daemon 启动失败；走既有 30s 配置热更新，改动下一检测周期生效、无需重启 daemon。
- 设置界面：Dashboard 设置页「自进化」页签下第一张卡片「代码陈旧自愈」，展示 `enabled` 与 `idle_confirm_seconds`（开关 + 连续空闲秒数输入），展示项与配置键一一对应；卡片不带独立保存按钮——保存入口为页签底部唯一保存按钮，一次提交同时覆盖本节两键（界面归属见 suggested-improvements-ui 能力页）。
- supervisor 启动失败熔断：`bin/fenixd_supervisor.py` 记录每次 daemon 启动后的存活时长；启动后 60 秒内退出判为启动失败并累计连续失败次数，连续 3 次即停止自动拉起 daemon、写入熔断标记、在 `.fenix/logs/supervisor.log` 落 critical 记录并经既有告警通道产出 critical 告警（描述含「daemon 连续启动失败，已停止自动拉起」与人工处置指引），不进入无限重启循环；存活超过 60 秒后退出则重置连续失败计数。熔断为人工可恢复：修复代码并清除熔断标记（或重启 supervisor 进程）后恢复自动拉起，旧计数不影响新进程。

## 溯源

- 2026-09-18 2026-09-18-add-framework-self-evolution — 自愈设置界面迁入「自进化」页签第一张卡片、保存按钮上提合并为页签唯一保存按钮（配置键、缺省值与面板控件语义不变）
- 2026-09-18 2026-09-18-add-stale-code-selfheal — 新增陈旧持续状态与 stale_code 边沿告警、空闲感知自愈触发（restart_request 协议复用、空闲判定与托管前置）、配置节与设置界面、supervisor 启动失败熔断
- 2026-09-25 2026-09-25-fix-state-atomicity-and-selfheal-restart — 空闲判定纳入在飞评审 run 全形态（停滞/API 重试中的 run 不算空闲、不得被自愈重启打断），并防陈旧锚点永久占据非空闲
