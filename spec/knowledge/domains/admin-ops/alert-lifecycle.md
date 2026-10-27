# 告警生命周期自动闭环

<!-- knowledge: capability=alert-lifecycle rev=3
     sources=spec/archive/2026-09-06-add-alert-auto-resolve,spec/archive/2026-10-25-add-alert-self-heal-marking,spec/archive/2026-10-27-evo-add-signal-subject-terminal-close -->

告警条目与底层 spec 状态的状态联动收口机制：spec 附着族（升级条目与信号条目皆然）按条件解除自动消解，基础设施瞬态族按签名安静自愈标注；自动收口只作用于人工甄别面的告警条目，不触碰 disposition 台账。

## 规则

**总则（两类收口共用）**

- 告警条目写入时附带结构化 `trigger` 字段（经 `alert_lifecycle.attach_trigger` 统一埋点）：包含可判定闭环的类型标识与关联对象，闭环判定不解析自然语言 description。signal_type → condition 映射表之外的类型不写 trigger、永不自动闭环（保守缺省）。
- 自动闭环不覆盖人工处理记录：`handled=True` 的条目一律跳过，字段与时间戳逐位不变。
- 闭环判定证据只取告警条目自身时间戳（`last_seen` 缺失回落 `created`），判定输入（告警列表、当前时刻、spec 状态表）全部由调用方注入；`alert_lifecycle` 模块保持纯函数，不读写文件、不读日志、不依赖锁。
- 自动收口只作用于人工甄别面的告警条目本身，MUST NOT 改写 disposition 记录本体（result/status 逐位不变）——处置台账不被旁路改写是 AdminMonitor 生效核查 fail-closed 契约的前提。

**spec 附着族：条件解除自动消解（auto-resolve）**

- 条件枚举四族：verify_fail_escalation / blocked_stuck / spec_content_missing 挂 `spec_terminal_or_unblocked`（关联 spec 到达终态或离开 blocked 即解除）；spec_delivered_no_content 挂独立条件，仅当关联 spec 到达终态才自动闭环（信号产生时 SPEC 停在 ready 等待人工裁决，宽松解除条件会被下一轮立即消解、使人工无从看见）。
- 收口通道按 kind×条件族双重界定：kind=escalation 一律走本判定；kind=signal 仅当属 spec 附着条件族（trigger 条件已识别，或存量回填口径下 signal_type ∈ {verify_fail_escalation, blocked_stuck}）才进入。签名安静自愈族与未登记族的 signal 条目不进本通道，仍归自愈判定或人工闭环——收口面按条件族白名单而非全部 kind=signal，防「主体终态但仍需人工关注的信号」被误收口。族判定为单源谓词，判定端 kind 门与盘点通道 pending 过滤共用。
- 闭环判定以关联 spec 为锚：主体 spec 仍处 blocked 时信号保持原状，升级与派发行为不变；处置组形态的升级滞留（主体非 spec）不在自动解除覆盖面，须人工闭环。
- 收口注记附主体终态/解除时刻（取 specs 状态表 entry 的 `updated` 字段，即最后状态变更时刻，非精确终态时间戳；字段缺失时保持既有表述、不硬造时刻）。spec 未达终态而解除（如已回 ready/implementing）时注记用中性表述（「当前状态 X，已非 blocked（视为解除）」），不断言该 spec 的历史 blocked 路径。
- 写回形态：`handled=True`、`handled_at` 为解除时刻、`handled_by="auto-resolve"`、`resolve_note` 由判定端生成并经写回端透传（写回端不另造内容），信号本体字段（description/escalated 等）原样保留。写回 kind 门为 escalation+signal，其余 kind（disposition 等）不经本路径写回。有 spec 字段且命中条件枚举的条目只走本判定，不与自愈判定双重判定。

**基础设施瞬态族：签名安静自愈（auto-self-heal）**

- 覆盖族注册表 `SELF_HEAL_SIGNAL_TYPES`：daemon_errors（日志指纹风暴）、run_infra_failure（链路 infra 熔断）、self-evolution（evo 分析 run 失败）；注册表外 signal_type 永不自愈闭环。
- 安静判定：最近复现时刻距当前 ≥ `admin.self_heal_quiet_minutes`（默认 1440 分钟，可配；非正整数/类型错误回退默认）即视为已自愈——窗口须盖过一次完整复发周期，避免收口后立即重开。
- 收敛升级条目（`kind=escalation`、spec 为空、带 `admin_run_id`）的最近复现时刻取双源锚点：「admin_run_id 名下 disposition 条目」与「同 signal_type 的未收口 signal 条目」两者的最新时间戳；MUST NOT 只锚 disposition created——底层风暴仍在复现（signal `last_seen` 持续刷新）时升级条目会被提前收口。裸升级条目（无 `admin_run_id`，如 evo 族）按条目自身 `last_seen` 判定。
- 写回形态：`handled_by="auto-self-heal"`、`resolve_note` 以「已自愈：」前缀并附安静证据（安静时长与最近复现时刻）；可关闭 `kind ∈ {escalation, signal}` 的条目，写回在排他锁内单次读改写，零写回时文件 mtime 不变。
- `inconclusive_loop`（env 豁免握手族）刻意不在注册表，无论安静多久永不自愈闭环，仍须人工裁决收口。
- 自愈收口后底层故障复发的，由信号冷却/去重机制自然产生新条目，不重开已收口条目。

**扫描、回填与视图**

- 闭环扫描内联于周期巡检执行（spec 附着条件判定与 spec-less 自愈判定双通道），不引入独立线程或定时器；通道一 pending 集为「未 handled 的 kind=escalation ∪ 未 handled 且属 spec 附着条件族的 kind=signal」，两通道互斥不双重判定；单轮扫描复杂度为 O(未闭环告警数)，无可闭环条目时零 IO 开销（不写回 admin_alerts.json，mtime 不变）。
- 存量回填双轨（daemon 启动首轮一次性，异常路径不消耗回填标志、下轮重试）：spec 附着条目按 signal_type ∈ {verify_fail_escalation, blocked_stuck} ＋ spec 字段推断条件闭环；无 trigger 字段的 spec-less 条目按 signal_type ∈ 自愈覆盖族推断参与自愈判定，resolve_note 注明存量回填。无法关联或条件无法判定的保持原状，保留「历史遗留」语义。
- 管理员视图按处理状态区分：待处理（handled=False）置顶显著展示，已处理折叠或分区展示、可展开查看 resolve_note 与 handled_at，不与待处理项混排；`handled_by=auto-self-heal` 渲染「已自愈」徽标（与「自动解决」徽标可辨），已自愈条目自然落入已处理视图。安静窗口在 Dashboard 设置页「系统」页签可调（非法值服务端拒绝不落盘）。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：告警写入时埋点结构化 trigger 字段，周期扫描按闭环判定自动解决；已解决告警折叠展示
- 2026-09-06 add-alert-auto-resolve（spec/archive/2026-09-06-add-alert-auto-resolve） — 固化闭环契约：trigger 结构化埋点、auto-resolve 标注与人工记录保护、巡检内联零开销扫描、启动回填与视图三分组
- 2026-10-25 add-alert-self-heal-marking（spec/archive/2026-10-25-add-alert-self-heal-marking） — 覆盖面从 spec 附着族扩至基础设施瞬态族：签名安静自愈判定（SELF_HEAL_SIGNAL_TYPES 注册表、双源安静锚点、1440 分钟可配窗口）、auto-self-heal 独立写回标识与「已自愈」徽标、spec-less 存量回填推断；收口面限定人工甄别面、不触 disposition 台账
- 2026-10-27 evo-add-signal-subject-terminal-close（spec/archive/2026-10-27-evo-add-signal-subject-terminal-close） — spec 附着条件族的 kind=signal 记录（blocked_stuck 等）纳入主体终态自动收口：判定端 kind 门按条件族白名单放宽、盘点通道 pending 纳入该族信号、写回端 auto_resolve kind 门开至 escalation+signal，收口注记附主体终态/解除时刻；签名安静族、escalation 既有闭环与 stuck 检测卫生逻辑不回归
