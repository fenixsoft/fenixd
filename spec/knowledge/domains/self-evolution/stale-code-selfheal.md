# 代码陈旧自愈

<!-- knowledge: capability=stale-code-selfheal rev=5
     sources=spec/archive/2026-09-18-add-framework-self-evolution,spec/archive/2026-09-18-add-stale-code-selfheal,spec/archive/2026-09-25-fix-state-atomicity-and-selfheal-restart,spec/archive/2026-09-28-fix-fasttrack-implemented-deadstate,spec/archive/2026-10-05-evo-reduce-stale-code-selfheal-noise -->

daemon 进程持旧代码的持续状态检测、按自愈健康度分级的告警留痕、空闲感知的优雅重启自愈、supervisor 启动失败熔断——「改代码 → 空闲 → 新代码生效」闭环。

## 规则

- 陈旧检测为持续状态：daemon 每个检测周期（既有 30s 配置热更新检测点）重新比对 `fenixd.py` 与 `core/**/*.py` 的最大 mtime 与进程启动时记录的 baseline，维护陈旧状态；陈旧期间每个周期都保持该状态，不在首次命中后永久静默。
- 陈旧告警按自愈链路健康度分流，写入时点为陈旧状态边沿（假→真），`signal_type` 均为 `stale_code`：
  - 健康路径 → info 级留痕：`stale_code_selfheal.enabled` 为真且未悬空超限（均为写入时点可判定条件；重启成功与否发生在写入之后的空闲确认窗内，不作写入分支条件）时，以 `kind: info`、`severity: info` 写入，日志输出含当日累计次数的日计数，文案保留「无需人工干预」自述。info 记录随写入自带 handled=true + handled_at 落盘（不经 mark_handled 接口——该接口仅锚定 ESCALATION），无处理生命周期，不进人工告警队列与升级路径，也不出现在待处理告警与 SPEC 时间轴视图。
  - 升级路径 → escalation 级（写入即自动标记已处理、仅作历史记录，不进人工告警横幅/待处理队列）：① 自愈禁用（`enabled: false`，此时陈旧状态与告警仍产生，日志明示自愈已被配置关闭）；② 陈旧悬空超过 `max_dangling_seconds`，由既有独立通道 `signal_type=stale_code_dangling_timeout` 升级，不写 info、不双重升级；③ `.fenix/restart_request` 写失败，追加一条 escalation（signal_type 仍为 `stale_code`，复用悬空升级的写入与去重范式）。
- 日计数口径：info 级「当日累计」以 admin_alerts.json 中当日 `signal_type=stale_code` 记录数计（遍历持久存储、跨重启存活）；不用进程内计数器——daemon 高频自愈重启下进程内计数随重启归零，撑不起「当日」语义。
- 60 分钟窗口去重对 info 级与 escalation 级同窗互斥生效（`info` 在 latest_signal 的 kind 白名单内）：任一在窗内即跳过写入、降为日志输出，持续陈旧不重复成条，写失败升级与 info 记录亦互斥。
- 单个陈旧周期内不重复堆积；状态转假不产生新的陈旧告警；自愈重启后磁盘未再变化则状态为假、不再告警也不再触发自愈。
- 空闲判定（四源合取，任一来源非空即非空闲）：① `agent_runner` 无活跃 run——覆盖 `pm_engine` 活跃 run 计数（planner/implementer/verifier/judge 全部 run 形态）与 `agent_runner._running_agents` 进程内注册表（任一登记在册的 run 都计非空闲，读法与容错细节见 [stale-selfheal-cooldown](stale-selfheal-cooldown.md)）；② 不存在任何未收口的在飞评审 run——含转录因 API 重试/停滞而暂不增长的 run，以「`reviewer_run` 锚点存在且该 run 尚在飞」判定（`PMEngine.is_review_in_flight` + `LivenessSupervisor.reviewer_in_flight` 双判据合取，与派发守卫同口径）；③ admin 处置 worker 池无在途任务（`_admin_executor` 为 None 即 `admin.workers=0` 同步回退时该维度视为空闲）；④ 无在飞 impl-ocr 车道（`ocr_lane_busy()` 无参口径为假）。判定复用既有内部状态，不通过扫描外部进程列表（ps / /proc 遍历）反推。
- 在飞评审判定以进程存活（daemon 进程内 run 注册表）为主判据、run 流文件为兜底；不以「转录是否仍在增长」作在飞依据（停滞 run 的转录本就不增长）。对确已收口或已死亡的 run（进程表无记录且流文件末行已终态），不得使其永久占据「非空闲」——陈旧锚点判为无在飞评审，自愈在真正空闲时仍能触发。
- 在飞 impl-ocr 车道维度：车道由 dispatcher 以裸后台线程跑维护型 run，在飞登记由线程收尾（finally）清理；车道在飞全程——含转录停止增长时段——不累计连续空闲时长，自愈不写 restart_request，在飞车道 run 不被重启杀死。消费点单点容错（getattr 链：瘦门面/替身缺 `ocr_lane_busy` 属性时该维度不阻断、不抛异常；仅采纳真 bool；判定异常按非空闲处理并记告警日志——宁紧勿松），阻断原因挂自愈阻断原因体系（`reason="ocr-lane"` 边沿日志）。对外判定只走属主层公开方法 `ocr_lane_busy(spec_name)`（无参任一在飞即 busy、带参按该 spec 精确判、方法内异常按 busy 返回），消费方禁跨层直读在飞登记私有字典。
- 车道豁免边界：豁免只护在飞期间——车道收尾（在飞登记清理完成）后恢复空闲判定为真，连续空闲时长自车道收尾起重新累计，达阈值后按既有机制正常触发；车道有硬超时不会无限占用，豁免不构成对事后自愈的永久抑制。
- 自愈触发：陈旧状态为真、`stale_code_selfheal.enabled` 为真、项目存在活跃 supervisor 托管三条件齐备时判定空闲；连续空闲达 `idle_confirm_seconds`（缺省 600 秒）后写入 `.fenix/restart_request`（复用既有 supervisor 优雅重启协议，不引入新信号、不改协议语义），日志记录触发原因与等待时长。合批语义：重启加载的是触盘时点的全部代码，确认窗内相继落地的多批代码由同一轮重启一次收编；仅连续空闲超过 600 秒的独立批次才各得一轮重启。空闲计时在任一非空闲信号出现时立即清零；`.fenix/restart_request` 已存在时不重复写入、不产生重复日志。
- 边界：托管态 `unmanaged`（daemon 在跑但无 supervisor）不自愈——不写 restart_request（写了无人消费），陈旧告警维持，等待经 Dashboard「安装托管」或 `/fenix-setup` 恢复托管；`enabled: false` 时不写 restart_request，但陈旧状态与告警仍产生（escalation 级），日志明示自愈已被配置关闭。
- 配置节 `stale_code_selfheal`：`enabled`（布尔，缺省 true）与 `idle_confirm_seconds`（整数秒，缺省 600）；配置缺失或键非法回退缺省值、不使 daemon 启动失败；走既有 30s 配置热更新，改动下一检测周期生效、无需重启 daemon；项目级覆盖优先于缺省生效，热更新语义不变。
- 设置界面：Dashboard 设置页「自进化」页签下第一张卡片「代码陈旧自愈」，展示 `enabled` 与 `idle_confirm_seconds`（开关 + 连续空闲秒数输入），展示项与配置键一一对应；卡片不带独立保存按钮——保存入口为页签底部唯一保存按钮，一次提交同时覆盖本节两键（界面归属见 suggested-improvements-ui 能力页）。面板缺省回填值与后端缺省保持同源一致（600），未改动表单直接保存写回的也是缺省值，不产生「表单旧缺省经保存显式写回项目配置」的漂移。
- supervisor 启动失败熔断：`bin/fenixd_supervisor.py` 记录每次 daemon 启动后的存活时长；启动后 60 秒内退出判为启动失败并累计连续失败次数，连续 3 次即停止自动拉起 daemon、写入熔断标记、在 `.fenix/logs/supervisor.log` 落 critical 记录并经既有告警通道产出 critical 告警（描述含「daemon 连续启动失败，已停止自动拉起」与人工处置指引），不进入无限重启循环；存活超过 60 秒后退出则重置连续失败计数。熔断为人工可恢复：修复代码并清除熔断标记（或重启 supervisor 进程）后恢复自动拉起，旧计数不影响新进程。

## 溯源

- 2026-09-18 2026-09-18-add-framework-self-evolution（spec/archive/2026-09-18-add-framework-self-evolution） — 自愈设置界面迁入「自进化」页签第一张卡片、保存按钮上提合并为页签唯一保存按钮（配置键、缺省值与面板控件语义不变）
- 2026-09-18 2026-09-18-add-stale-code-selfheal（spec/archive/2026-09-18-add-stale-code-selfheal） — 新增陈旧持续状态与 stale_code 边沿告警、空闲感知自愈触发（restart_request 协议复用、空闲判定与托管前置）、配置节与设置界面、supervisor 启动失败熔断
- 2026-09-25 2026-09-25-fix-state-atomicity-and-selfheal-restart（spec/archive/2026-09-25-fix-state-atomicity-and-selfheal-restart） — 空闲判定纳入在飞评审 run 全形态（停滞/API 重试中的 run 不算空闲、不得被自愈重启打断），并防陈旧锚点永久占据非空闲
- 2026-09-28 2026-09-28-fix-fasttrack-implemented-deadstate（spec/archive/2026-09-28-fix-fasttrack-implemented-deadstate） — 空闲判定纳入在飞 impl-ocr 车道第四源（在飞全程不触发重启、收尾后重新累计、异常宁紧勿松），在飞登记经公开方法 `ocr_lane_busy` 封装、禁跨层直读
- 2026-10-05 2026-10-05-evo-reduce-stale-code-selfheal-noise（spec/archive/2026-10-05-evo-reduce-stale-code-selfheal-noise） — 陈旧告警按自愈健康度分流：健康路径降为 info 级留痕（kind=info 入 latest_signal 白名单、日计数以存储当日记录数跨重启计、自带 handled 落盘不经 mark_handled），自愈禁用/悬空超限/restart_request 写失败仍走 escalation；空闲确认缺省 120→600 秒（后端、设置页回填与生效配置 seed 同源同步），密集落地批次由同一轮重启收编
