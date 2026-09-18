## Context

Fenixd 的进程拥有一份**启动时刻的代码副本**（Python import 后不重载磁盘文件），而本项目是自我开发的——agent 持续修改 `/root/fenixd` 自身的代码。于是「daemon 陈旧」在本项目中是常态而非异常。

既有机制呈现出一种不对称：

- **检测侧完备**：`fenixd.py` 自 `improve-hot-reload-robustness` D4（2026-09-05）起在每 30s 的配置热更新检测点做 mtime 比对，指纹覆盖 `fenixd.py` + `core/**/*.py`，且明确选择了 mtime 而非 git rev-parse（以覆盖未提交修改，worktree 友好）。其灵敏度已被验证——09-12 事故中，消费逻辑提交后 2 分 27 秒即命中。
- **动作侧缺失**：命中后只落一行 WARNING，且 `_CODE_STALE_WARNED` 是模块级旗标，每进程生命周期**只提示一次**。此后永久静默，直到人工去看日志。

- **自愈能力其实已存在，但接错了线**：`.fenix/hooks/restart-daemon-when-idle.py`（2026-09-08）实现了完整的空闲感知重启——双轮空闲确认（连续 120s）、`fcntl` 防重入、150 分钟上限、探测失败按「有活跃」处理的 fail-safe。但它挂在 `hooks.specs.add-judge-artifact-gate` 的 `done` 事件上，只为那一个 SPEC 的收口服务；且因运行在 hook 进程里，它看不到 daemon 内部的 `_active_runs`，只能靠 `ps` 扫描 `--output-format stream-json` + `--add-dir .../.claude/worktrees/` 反推活跃 run。

约束：改动必须保持「文件即状态」的架构性质；不改变 `restart_request` 文件信号协议（dashboard / hook / admin 三方共用）；不改变 daemon 排水与恢复语义。本 SPEC 依赖 `fix-supervisor-hosting-chain` 引入的 `supervisor_running(root)` / `hosting_state(root)`，经 STATE.md `depends_on` 排队，不重复定义。

## Goals / Non-Goals

**Goals:**

1. 让「代码陈旧」成为 dashboard 可见的**持续状态**，而不是日志里一次性的一行字。
2. 把「检测到陈旧」接到「空闲时重启」上，使「改代码 → 空闲 → 新代码生效」形成闭环，且不依赖外部脚本。
3. 用 daemon 自身的活跃度状态做空闲判定，取代外部 `ps` 反推。
4. 让自动重启**可控**（配置开关 + 界面）且**有安全边界**（未托管不自愈、启动失败熔断）。
5. 消除「空闲重启」的双实现路径。

**Non-Goals:**

- 不改变 `restart_request` 协议、不新增第三种文件信号。
- 不改变 daemon 排水窗口与 boot recovery 语义。
- 不做 supervisor 自身的自动升级（`fix-supervisor-hosting-chain` D7 已定论：显式操作 + 告警）。
- 不做「审批推送信号的消费确认 / 滞留超时」——那是信号链路的另一个议题，本 SPEC 不触碰。
- 不在实现阶段直接操作任何运行中的生产进程。

## Decisions

### D1. 陈旧状态由 daemon 自己维护，不做外部探测

**决策**：在 `fenixd.py` 内维护 `self._code_stale` 持续状态，每个检测周期（既有 30s 节拍）重算，并据此写告警、驱动自愈。移除「只提示一次」的模块级旗标语义。

**理由**：检测方本来就是 daemon（`_maybe_reload_config` 已在跑 mtime 比对），状态也天然属于进程自身——「我跑的是不是旧代码」只有进程自己能回答。把状态外置给脚本，就必然引入第二份判定逻辑与额外的进程探测。

**备选方案**：
- 扩展 `restart-daemon-when-idle.py` 加一个「陈旧检测」分支 → 需要在外部重复 mtime baseline 逻辑，且外部脚本无法知道 daemon 进程的启动时刻（只能猜）。
- 新增独立监视进程 → 引入第三个常驻进程与新的生命周期问题，收益不成比例。

### D2. 空闲判定用内部状态双源，不用 `ps` 扫描

**决策**：空闲 = `agent_runner` 无活跃 run（`_active_runs == 0`）**且** admin 处置 worker 池无在途任务。

**理由**：`ps` 扫描是外部进程的无奈之举，它有三个固有缺陷：① 只能看到已 spawn 的进程，看不到已入队未派发的 run；② 依赖命令行特征串（`--output-format stream-json` 等），特征一变判定即失效；③ 探测失败只能 fail-safe 地「按有活跃处理」，即永远不重启。daemon 内部状态没有这些问题。

**关于 admin 池**：只查 `_active_runs` 是不够的——admin 处置走的是独立的 `ThreadPoolExecutor`（`fix-admin-run-blocks-mainloop` 引入），在途处置不会反映在 `_active_runs` 上。判空闲必须覆盖它，否则会在 admin 干活时重启。语义与既有 `reclaim_stale_autostash_if_idle` 同源，并补齐 admin 池维度。

**备选方案**：复用 `reclaim_stale_autostash_if_idle` 直接调它 → 语义耦合（那个函数会真的执行回收动作），不适合当作纯判定使用。

### D3. 删除 when-idle 脚本，而不是泛化它

**决策**：删除 `.fenix/hooks/restart-daemon-when-idle.py` 与 `config.yaml` 中挂载它的 hook 项。

**理由**：daemon 内建后，该脚本对「空闲重启」这一职责完全冗余，且它的触发源绑死在单个 SPEC 的 `done` 上——即便是 one-shot 语义下的一次性用途，也意味着「新代码何时生效」取决于某个特定 SPEC 何时收口，这在语义上是错的。保留它会让「空闲重启」长期存在两条实现路径，而两条路径的空闲判定口径不同（内部状态 vs `ps` 特征串），未来必然产生「脚本说要等、daemon 说可以重启」这类分歧。

**备选方案**：泛化为「任意 SPEC done 都触发」→ 会让每个 SPEC 收口都试图重启 daemon，与 `_active_runs` 判定叠加后行为难以预测，且与本 SPEC 的内建路径功能重叠。

### D4. 熔断阈值：60 秒存活 / 连续 3 次

**决策**：daemon 启动后在 60 秒内退出计为一次启动失败；连续 3 次失败则停止自动拉起，写熔断标记 + critical 告警；存活超过 60 秒重置计数。

**理由**：60 秒足以覆盖正常启动（载入配置、STATE、注册事件总线、worktree 清理）而不误伤；30 秒过于激进，启动慢的机器会误判。连续 3 次而非 1 次，是为了容忍偶发的单次启动抖动（如 `daemon.lock` 竞态）。阈值比既有 `SUPERVISOR_KILL_MARGIN_SECONDS`(120) 更短是刻意的——那些常数约束的是**停止**路径的宽限，而这里的判定目标是**启动是否成功**，两者语义相反，不应复用同一常数。

**备选方案**：
- 熔断后自动 half-open 重试（隔 N 分钟再试一次）→ 复杂度明显上升，且「坏代码」不会自愈，自动重试只会延长故障展示时间；人工修复 + 清标记是更诚实的行为。
- 不做熔断，靠 supervisor 无尽拉起 → 这是把「可恢复的陈旧」变成「CPU 空转 + 日志刷屏 + 无人可用的项目」，正是本 SPEC 要避免的。

### D5. 配置默认开启，且必须带界面

**决策**：`stale_code_selfheal.enabled` 默认 `true`，`idle_confirm_seconds` 默认 `120`，并在 Dashboard 设置页提供可读写界面。

**理由**：默认 `120` 是对齐 `restart-daemon-when-idle.py` 的既有取值——该值已在实践中验证过（双轮确认防零活跃窗口竞态）。默认开启是因为本项目的陈旧是常态，默认关闭等于把问题留给用户发现；而风险由熔断兜底、由开关提供退出通道。界面是项目既有硬约束（新增配置项必须带界面），不是为了完整性而加的装饰。

**备选方案**：默认关闭 → 主树与 fenix-server 这类最需要它的项目反而要人工开启，与「自愈优先」的诉求相悖。

### D6. 未托管项目不自愈

**决策**：`hosting_state != "managed"` 时不写 `restart_request`，仅维持陈旧告警。

**理由**：`restart_request` 的消费者是 supervisor。在 `unmanaged` 项目上写它，等于制造一封死信，而陈旧状态会被误认为「已安排自愈」——这恰恰是 09-12 事故的形态（`restart_request` 挂了 12 小时无人消费）。自愈的前提是**消费链完整**；断链场景由 `fix-supervisor-hosting-chain` 的安装托管路径负责修复，本 SPEC 只负责不在断链时制造假象。

## Risks / Trade-offs

- **[自动重启把坏代码引入运行中的系统]** → 这正是新增熔断的原因（D4）；同时提供配置开关供人工关闭。残余风险：新代码能启动但行为错误——这类问题熔断无法覆盖，属于「自动化的固有代价」，由陈旧告警 + 项目日志提供事后追溯。

- **[空闲判定与重启之间存在竞态：写入 `restart_request` 后、supervisor SIGTERM 到达前，可能有新 run 被派发]** → 窗口极小（自愈前已确认连续 120s 无活跃），且 daemon 收到 SIGTERM 后走既有排水路径（`drain>0` 项目等待在跑 run 终态）。`drain=0` 项目（如 fenix-server）会快速停机，理论上可能打断刚派发的 run——这是既有语义的一部分，本 SPEC 不改变它，但值得在落地后观察是否出现。

- **[熔断标记残留导致项目永久不拉起]** → 熔断标记语义明确（人工处置信号），且告警文案必须给出清除指引；同时「重启 supervisor 进程」这条既有路径天然清除熔断状态（计数与标记都在 supervisor 进程生命周期内）。

- **[陈旧告警在自我开发期间长期占据告警面板]** → 告警按未处置去重，且自愈会在空闲时消除根因。若用户关闭自愈，则陈旧告警会长期存在——这是**正确的**，因为此时陈旧确实是持续缺陷。

- **[删除 when-idle 脚本可能影响 `add-judge-artifact-gate` 的既有 hook 行为]** → 该 SPEC 已归档，且 hook 为 one-shot 语义（触发一次即摘除）；删除的是配置文件中的挂载项与脚本文件本身，不触碰已归档 SPEC 的产物。落地时需确认该 hook 当前未被其他 SPEC 引用。

## Migration Plan

1. **代码先行**：本 SPEC 只改代码、配置与文档，不操作运行中的生产进程。
2. **前置依赖**：等待 `fix-supervisor-hosting-chain` 落地（`depends_on` 排队），确保 `supervisor_running()` / `hosting_state()` 已存在。
3. **落地后观察**：主树（`/root/fenixd`）是首个验证对象——daemon 当前持旧代码，自愈启用后应在下一个空闲窗口自动重启并加载新代码；观察 `stale_code` 告警是否随重启自动消失。
4. **回滚**：改动集中在 `fenixd.py` 主循环、supervisor 与配置读侧；旧配置无 `stale_code_selfheal` 节时回退缺省值（即行为等同本项目落地前）。紧急关闭走配置开关，无需回滚代码。

## Open Questions

- **熔断标记的具体承载形式**：独立文件（如 `.fenix/supervisor_fused`）还是写入既有 `supervisor_runtime.json` 的字段？倾向前者——独立文件便于用户手工删除，语义也更直白，且不污染既有 runtime 自报结构。
- **`idle_confirm_seconds` 是否需要上界**：用户若配置为极大值（如 86400），自愈将形同虚设。是否需要在配置校验时给出建议上界或警告（不强制拒绝）？倾向给出警告而非拒绝，保持配置读取的宽容语义。
- **陈旧告警的 `severity` 取值**：参照 `fix-supervisor-hosting-chain` 中 `supervisor_missing` 定为 `major` 的讨论——「陈旧」同样是持续性缺陷而非瞬时故障，需与该 SPEC 落地后的告警降噪口径保持一致，避免自我开发期间告警面板被长期占满。
  - **已决（2026-09-13，用户降噪决策）**：定为 `warning` 级——`major` 会让告警长期占据人工待处理队列与横幅，而陈旧本就可经空闲自愈收敛、`recommended_action` 亦声明「无需人工干预」。按既有分级语义（`core/admin_store.py` `HUMAN_SEVERITIES`），`warning` 写入即自动标记已处理，不进人工队列，仅留历史记录；告警写入由状态边沿（假→真）触发，单周期内不重复堆积。
