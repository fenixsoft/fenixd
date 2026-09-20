# 保障机制

框架不可能永远正常运行：模型可能写错文件路径、验证场景可能被环境问题污染、实现 Agent 可能陷入无效重试。Fenix 为此构建了一套纵深防御体系：从 SPEC 注册那一刻起，每一类可能出事的环节都被多层机制覆盖，内层拦截确定性错误、外层兜住意外情况，机制之间以失效模式而非正常流程衔接，当上一层漏过时，下一层一定接住。本章按防御层次讲述五类机制：声明 lint 在提交前拦截格式与路径错误；状态机转移门与产物硬门在关键节点做确定性校验；运行时守卫在 Agent 执行期间实时拦截越权操作；自愈链路在异常中断后自动恢复到可调度状态；告警系统在自愈无法覆盖时升级人工。每类机制都讲清它防御哪类真实事故、怎么工作、在哪拦截以及违规后果。需要了解具体预算数值、退避秒数、告警阈值等运维口径时，请参阅[调度与治理规则](06-governance.md)。

## 声明 lint：在错误进入流水线之前拦截

SPEC 进入 `drafted` 状态后、被晋升为 `ready` 之前，框架执行一轮声明 lint，这是纵深防御的第一道门。这道门要拦住的不是代码 bug，而是「SPEC 自身的交付声明写错了」：路径用了占位符、`kind: modify` 指向了一个不存在的文件、或者写的是仓库外的绝对路径。这类错误如果放过，后续整个实现 run 都会在收工守卫对账时白白失败，浪费一轮 Agent 运行预算。

声明 lint 的核心逻辑在 `core/deliverables.py` 的 `lint_declared()` 函数中，它解析 tasks.md 的 `## Deliverables` 段，逐条校验六个确定性规则：路径含 `<`/`>` 模板占位符（守卫会静默跳过该条目，形同虚设）、`kind: modify` 指向主树目录而非具体文件（目录无法按 blob 精确对账）、`kind: modify`/`kind: reference` 指向的路径在主树不存在（modify 语义即修改既有文件、reference 即引用既有文件，不存在即声明有错）、`kind: new` 在仓库内有唯一 basename 命中时判疑似笔误（零或多命中 fail-open 交由后续层兜底）、`kind: modify`/`kind: new` 的路径被 `.gitignore` 排除（在任何分支均不可交付），以及路径解析后不在项目根内（仓库外路径不可交付）。六条规则都只拦确定性无效形态，lint 自身故障一律 fail-open，不因 lint 本身的 bug 阻塞流水线。

除了交付路径 lint，`lint_tasks_parseable()` 还校验 tasks.md 的分组标题是否符合 `## <编号>. <标题>` 格式。这不是死板的格式要求，而是因为下游的任务进度跟踪器依赖分组正则解析（与 `core/dashboard/data.py:parse_tasks`、`bin/fenix_process.py:parse_tasks` 同源），无法解析的 tasks.md 意味着整条流水线的任务进度会丢失。

两道 lint 的编排由 `core/pm_engine/promotion.py` 的 `promote_drafted()` 统一完成：先执行晋升前软化（把 gitignored/仓库外路径的声明自动降级为 `kind: reference`，消除不可满足条目），再依次跑声明 lint 和 tasks 格式 lint，最后做出晋升判定。软化的目的是减少误拦：有些路径确实是不可交付的（比如 `.fenix/config.yaml` 被 gitignore），但它们在 tasks.md 中的原意是「引用」而非「新建」，自动修正 kind 比阻塞晋升更合理。软化结果写入 `DisputeAuditStore` 供事后审计。

最后，PreToolUse hook `planner-scenario-batching.py` 在出题阶段实施一道特殊的落盘守卫：验证场景首次写入 test_scenarios.json 时，所有场景的 steps 和 assertions 必须为空数组（纯骨架形态）。这个守卫解决的是 LLM 违反提示词指令、一次性写入全量带肉场景导致出题进度条长时间卡在 0% 的问题：迫使 Agent 先落骨架，再分批补全，让前端进度条能实时反映推进。

## 门禁：在关键节点做确定性校验

如果说声明 lint 是「提交前拦截格式错误」，那门禁就是在 SPEC 生命周期的每个关键节点上做结构化的确定性校验，不依赖 LLM 判断，只读数据结构是否合规。门禁覆盖三个维度：状态机转移门控制状态流转的合法性、产物硬门校验验证报告的分类与证据完整性、环境门在验证环境异常时阻止误判。

### 状态机转移门

SPEC 的十状态生命周期（`drafted` → `ready` → `implementing` → `implemented` → `testing` → `verified`/`bug-found` → `done` → `pushed`，以及 `blocked`）由 `core/state_machine.py` 中的 `SpecStatus` 枚举和 `transition()` 方法管理。每一次状态转换都是一个门禁点：非法转移（比如从 `done` 直接跳回 `ready`）会被状态机拒绝，STATE.md 不会写入不一致的状态。人工冻结是状态机的另一道门：当管理员在 Dashboard 或 CLI 中冻结一个 SPEC 时，`FROZEN_FIELD` 被写入 STATE.md 的 entry 中，此后所有自动链路对 status 的改写在 `update_spec()` 内被统一拦截（82 个调用点一次性收口），冻结期间 SPEC 稳定在 `blocked` 状态，不参与调度，不被自动恢复。冻结还支持定时解冻（`frozen_until` 字段），超时后自动解除。

**冻结即停在跑 agent（add-freeze-stop-inflight-agents）**：冻结不仅挡住派发边界，还终止该 SPEC 名下**已经在跑**的 agent（评审 reviewer、实现 implementer、验证 verifier、修复 repair、fast-track 等全部经 dispatch 收口的角色）。runner 轮询环（1 秒粒度）在人工取消旗标检查旁直接读 STATE 的 `frozen` 字段，命中即：先对当前 worktree 做一次 WIP checkpoint（锚点 `freeze-hold`）保全未提交现场 → `terminate()` → 最长 10 秒宽限 → 存活则 `kill()` → 向 run 产物追加 `frozen-terminated` 终态行 → 走独立 `FrozenTerminatedError` 通道（与人工取消 `RunCancelledError` 并列、互不干扰）。被冻结终止的 run 不重试、不重派、不翻转 status；STATE 写入 `_frozen_hold` 标记（与 `_cancelled_hold` 并列、互不读写），保留 `branch` / `implementer_run` 锚点。

**解冻自动续做**：解冻（`unfreeze_spec`）时若检测到 `_frozen_hold` 且保留分支相对 main 有未合并提交，走与 daemon 重启恢复（`interrupt-recovery-preserve`）**同源**的保留判定——保留 `branch` / `implementer_run`、置 `_recovery_resume: True`，dispatch 拾取后在保留分支的 worktree 上 resume 续做（而非从零新建分支）。无分支/零提交/载体不可用时清 `_frozen_hold` 走普通重派（从零），并 WARNING 留痕。

**删除先停后删**：删除（软删除）一个 SPEC 前，框架先请求终止其名下全部在跑 run，并有界等待终态（每 run 宽限 10 秒 + 总上限），终态齐备后才移动目录/剔除 STATE 条目；等待超时仍返回失败且**不产生半删状态**。API 侧为异步受理：有在跑 agent 时写 `.fenix/spec_delete_request.json` 信号返回受理结果（`stopping: N`），由 daemon 主循环消费完成停止+删除；无在跑 agent 时保持同步软删除。daemon 未受 supervisor 托管时拒绝受理（信号无人消费）。

### 产物硬门

验证引擎完成场景执行后，planner-judge 对报告做增强（为每个非 PASS 场景补 classification 与 evidence），然后 `core/verdict_check.py` 的 `validate_report()` 对增强后的报告做硬校验：每个非 PASS 场景必须有合法的四分类（`product-bug`/`test-defect`/`flaky`/`env`）、至少一个证据维度（失败断言列表 / 截图路径 / 首个失败步骤），以及完整的 `assertion_triage` 数组：每条失败断言必须被单独归类并附非空证据。`assertion_triage` 是逐断言归因的核心数据结构：一个场景有 3 条失败断言，就必须有 3 条归因条目，缺一不可。这是为了防止「一条产品缺陷被淹没在整体豁免里」的假阴性事故。

归因后的强制状态映射（`enforce_status_mapping()`）是产物硬门的第二道防线：`product-bug`/`test-defect` 分类的场景，如果 status 不是 `failed`，框架会强制改写为 `failed` 并在报告中标注「已修正」。这条规则不信任 LLM 输出的状态值，分类为产品缺陷却标注为 warning 的报告会被机械纠正，确保产品缺陷不会以 warning 状态逃逸到后续环节。

洗白不变量检查（`whitewash_violations()`）是产物硬门的第三道防线：如果全部场景都失败（0 通过）却要判 `verified`，或者 env 分类的失败场景要被当作豁免理由放行，这两类操作都会被拒绝。前者拦住的是「全部失败却声称验证通过」的自相矛盾报告，后者拦住的是「遇到环境问题就不测了」的逃避行为。

Fast-track 模式下，`validate_fast_track_result()` 对 `.fenix-run-result.json` 做三要素校验：结构完整（场景/结果/判定字段齐全）、场景全量执行（设计集 ID 与执行集 ID 逐字一致，防止静默遗漏）、逐场景证据存在（每个非 PASS 场景必须带 classification 和 evidence）。设计集与执行集的一致性校验确保 Agent 不会悄悄删掉失败场景来美化结果。

与产物硬门并列的还有两道读侧门禁：planner 裁决结果（`plan-ready`/`verified`/`bug-found`/`scenario-repaired`）的读取按状态白名单校验（`core/pm_engine/verification.py`），白名单外或不可解析的结果一律 fail-closed 视为失败，不当作推进依据，这是「读侧不信任、宁可阻断也不虚假推进」的同一原则。验证报告写回侧同样 fail-closed（`core/verify_report.py`）：结构化数据不可用时不写空报告，而是阻止状态推进。

归因级别由框架侧机械计算（`compute_attribution_level()`），不依赖 LLM 模型的判断能力：有算法标签（blank_screenshot/low_contrast）或有截图加失败断言归因时判为 evidence-backed，涉及视觉现象但无截图佐证时判为 pending-visual，其余判为 speculative。当全部驱动打回的场景归因级别均为 speculative 时，`should_suppress_bug_found()` 会抑制 bug-found 打回：框架拒绝带推测信号的修复派发，宁可转重验或写 error 待人工复核。批量归因查重（`check_batch_attribution_dedup()`）则防止多个场景被套用完全相同的硬编码归因文本。

### 环境门

`core/verify_engine/env_gate.py` 解决的是另一类问题：验证场景失败了，但失败原因不是产品缺陷，而是验证环境本身的问题，比如 mock 步骤斩断了 SSE 推流导致页面 DOM 永不更新、被测实例失联、或者 CSR 应用冷启动白屏。这类失败如果被当作产品缺陷处理，会触发不必要的 fix 子 SPEC，白白消耗实现预算。

环境门在场景结算后做后置分类：对每个失败场景检查其步骤序列，如果步骤含 `mock_api` 操作且失败项是纯等待超时（Playwright 统一超时文案），同时环境探针（`probe_http_health()` 依次探测根路径、`/api/state`、`/api/overview`，任一返回 2xx/3xx 即视为连通）确认实例失联，场景状态被降级为 `blocked-env` 而非 `fail`。对于连接失败（API/SSE 步骤的 `error_type` 为 `connection_failed`），同样走探针确认路径降级。白屏是客户端渲染维度的证据，即便服务探针正常，`first_frame_ok is False` 的步骤也会直接降级为 `blocked-env`，因为白屏的事实不因服务端健康而被推翻。

降级为 `blocked-env` 的场景不进入产品归因管道，而是由 pm_engine 的 `_escalate_env_blocked()` 通道升级送人工复核。这确保了环境问题不会被静默当作产品缺陷处理，也不会因为简单放行而掩盖前端渲染崩溃等需要人工诊断的问题。

## 运行时守卫：Agent 执行期间的实时拦截

门禁在 SPEC 状态转换的关键节点拦截，运行时守卫则在 Agent 执行期间持续守卫。守卫分两类：工具层面的 PreToolUse hook 在 Agent 每次调用文件操作工具时检查，流水线层面的收工守卫在实现 run 结束时对账。

### PreToolUse hook 拦截

`core/agent_runner/runner.py` 在启动 Agent 子进程时，通过环境变量注入与 settings 注入构建两层运行时守卫。

第一层是 worktree 隔离守卫（`block-main-tree-write.py`）。当 Agent 在 worktree 中运行时，`FENIX_RUN_PROJECT_ROOT` 和 `FENIX_RUN_WORKTREE` 环境变量被注入（`core/agent_runner/runner.py:2520`），PreToolUse hook 在 Agent 调用 Write/Edit/NotebookEdit 工具时拦截：如果目标文件路径解析后指向主树（而非 worktree），hook 返回 `deny` 并在纠偏提示中给出 worktree 内的相对路径。路径穿越逃逸（用 `..` 逃逸出 worktree）同样被拦截。这个守卫防住的是一类真实事故：Agent 被 skill 注入文本锚定为项目根的绝对路径后，39 次写盘全部落主树、worktree 零改动。没有这道守卫，这类事故完全无感，直到用户发现主树被改。

第二层是图片读取守卫。`.fenix/agent-settings.json`（在 `runner.py:1424-1428` 构造）注入 PreToolUse hook `block-image-read`，阻止 verifier/planner 读取 PNG/JPG 文件。当模型不支持图像输入时，读截图会把图片送进对话导致 400 错误整轮失败。

第三层是场景出题分批守卫（`planner-scenario-batching.py`，前文已述）。这三层 hook 各自独立，互不耦合，任一触发都不影响其他两层的守卫行为。

### 收工守卫

实现 Agent 完成代码编写后、提交前，收工守卫对账三件事：零变更守卫检查 run 内是否产生了新提交，声称成功但既无新提交也无 Edit/Write 工具调用的 run 被判定为失败并重新派发；交付物守卫提取 tasks.md 的 Deliverables 声明（`core/deliverables.py:extract_paths()`），逐条检查声明路径是否在分支上真实存在，缺件阻塞收工；修复预算（`agents.impl_run_budget`）跟踪 run 内修复轮次，预算用尽仍有缺陷则自动升级 full 模式。三道对账都是确定性机械检查，不依赖 LLM 判断。

## 自愈链路：异常中断后的自动恢复

即使有 lint、门禁和守卫，运行时仍会出现 Agent 崩溃、daemon 异常退出、worktree 残留等情况。自愈链路的目标是在不丢失状态、不烧浪费钱的前提下，把这些异常自动修复到可继续调度的状态。

### Boot recovery：daemon 重启后的状态回退

daemon 由 `fenixd_supervisor.py` 托管，异常退出后自动拉起。重启时，`core/pm_engine/engine.py` 的 boot recovery 逻辑（`recover_interrupted`）把所有处于 `implementing`/`testing` 中断状态的 SPEC 自动回退为 `ready`，同时清空陈旧的 run 字段、重置重试计数，重新进入调度池。这个回退是设计行为而非数据丢失：中断状态的 SPEC 本来就没有完成的 run，继续停留 `implementing` 只会卡死调度。回退后，`full_scan` 自动发现这些 SPEC 并重新派发。停留 `drafted` 的存量 SPEC 也会在 `full_scan` 时被自动晋升（前提是 `promote_mode` 为 `auto`）。

### 恢复闭环复查

`core/pm_engine/recovery.py` 的 `RecoveryWatch` 组件为每次自动恢复注册观察项，在可配置的复查间隔后复查该 SPEC 是否真实恢复推进。观察项持久化到 `.fenix/recovery_watch.json`，daemon 重启后续查。如果复查发现 SPEC 仍然停滞（同一指纹的信号在冷却期外再次出现），则上报 `dispatch_stalled` 信号。这个机制防住的是「自动恢复成功但 SPEC 实际卡在别的地方」的静默故障：恢复不是终点，恢复后的推进才是。

### Run sweeper：清理悬空 run

`core/event_bus.py` 的运行期扫除器定期检查 `.fenix/runs/` 目录中的 run 状态：如果一个 run 的进程已退出但状态字段仍显示「运行中」，sweeper 把它标记为超时终止，释放调度锁。这防止了 Agent 进程崩溃后残留的 run 状态卡死整个调度循环。

### Worktree 遗产清理与 autostash 回收

`core/worktree_manager.py` 管理实现 run 的 worktree 生命周期。每个 worktree 在创建时登记到活动集，run 结束后进入遗留宽限期，宽限期内 worktree 保留供参考，超时后由 sweeper 回收。派发前的 autostash（`fix-autostash-orphans` 机制）在主树有未暂存修改时自动 `git stash`，确保 worktree 创建和分支操作的原子性。滞留的 autostash 条目由 `reclaim_stale_autostash()` 定期兜底回收：先合并到主树（`stash → merge → pop`），冲突时自动解决（UU → add），最终 drop 原条目。`reclaim_stale_autostash_if_idle()` 只在调度器空闲时触发，不与正常派发竞争。

### 重启协议

daemon 由 `fenixd_supervisor.py` 托管的完整重启协议是自愈链路的最后一环：daemon 进程崩溃时 supervisor 自动拉起，启动后执行 boot recovery，将中断状态的 SPEC 回退 `ready`、续查恢复观察项、启动 sweeper。项目的启停通过 `/fenix-dashboard` 或 `/fenix-setup` 操作，跨项目的统一管理由 `/fenix-dashboard` 负责。这个协议保证了 daemon 异常退出不会导致整个系统停摆。

**唯一托管启动路径与托管态**：daemon 的唯一合法启动路径是经 supervisor 托管——`/fenix-setup` 第 7 步与 Dashboard 项目页「启动」均在项目唯一 tmux session 内拉起 `fenixd_supervisor.py --project-root <根>`，tmux 仅承担脱离终端，daemon 是 supervisor 的子进程。停止语义为「写 `.fenix/stop` → SIGTERM daemon → supervisor 收口退出」。daemon 运行状态分三态：`managed`（受托管）、`unmanaged`（裸 daemon——进程在跑但无 supervisor，restart_request 无人消费，需经 Dashboard「安装托管」或 `/fenix-setup` 恢复）、`stopped`（未运行）。daemon 启动自检在托管缺失时落 `supervisor_missing` 告警并升级人工。

### 代码陈旧自愈与启动失败熔断

daemon 进程持有的是启动时刻的代码副本（Python import 后不重载磁盘文件），在自我开发场景下「代码陈旧」是常态而非异常。陈旧检测（`fenixd.py` 每 30s 检测点比对 `fenixd.py` + `core/**/*.py` mtime 与启动 baseline）是持续状态而非一次性事件：命中后保持 `self._code_stale` 为真、落一条 `signal_type: stale_code`、`severity: warning` 的 escalation 告警，直到重启刷新 baseline 或磁盘代码回退才解除。该告警为 `warning` 级——陈旧属可经空闲自愈收敛的持续状态，无需人工介入，故写入即自动标记已处理：**不进**人工告警横幅与待处理队列，仅在运维记录页/历史区可见；告警写入由状态边沿（假→真）触发，单个陈旧周期内不重复堆积。

陈旧自愈的触发条件是**同时**满足：陈旧为真、`stale_code_selfheal.enabled` 为真（缺省开启）、项目受 supervisor 托管（`managed`）、`.fenix/restart_request` 不在册。空闲判定口径是**同时**满足：`agent_runner` 无活跃 run（planner / implementer / verifier / judge 全部形态均在 `_active_runs` 内）且 admin 处置 worker 池无在途任务（worker 池未启用时该维度视为空闲），任一非零即判非空闲，倒逼计时清零。连续空闲达到 `stale_code_selfheal.idle_confirm_seconds`（缺省 120s）后 daemon touch `.fenix/restart_request`，supervisor 执行的仍是既有优雅重启协议（restart_request 协议本身不变）。未托管项目（`unmanaged`）不自愈——`restart_request` 无人消费，写了即死信，此时仅维持陈旧告警，交由 Dashboard「安装托管」或 `/fenix-setup` 的安装托管路径处置。

自动重启会把新代码引入运行中的系统：若新代码无法启动，supervisor 的启动失败熔断兜底——daemon 启动后 60 秒内退出计为一次启动失败，连续 3 次失败时停止自动拉起，写熔断标记 `.fenix/supervisor_fused`（独立文件，含时间戳/失败次数/自身 pid，便于手工删除），在 `supervisor.log` 落 critical 记录并经既有告警通道产出 `severity: critical` 的 `supervisor_fused` 告警。人工恢复路径：修复代码 → 删除 `.fenix/supervisor_fused` → 重启 supervisor；或直接重启 supervisor 进程（计数与熔断不被新进程继承）。daemon 存活超过 60 秒重置连续失败计数为 0，容忍偶发的单次启动抖动。配置关停（`stale_code_selfheal.enabled: false`）是另一个退出通道：此时陈旧状态与告警仍产生（正确的长期提醒，因为陈旧确实是持续缺陷），只是不再自动触发重启。

## 告警系统：自愈无法覆盖时升级人工

前四类机制覆盖了大多数异常，但有些情况无法自动化处理：merge 冲突的根因是 git 历史分歧、SPEC 卡在 `blocked` 状态且自动恢复无效、同一 SPEC 反复失败但每次失败原因不同。这些场景需要人工介入，告警系统就是把框架无法解决的问题升级给人的通道。

### 告警检测

`core/admin_monitor.py` 的 `AdminMonitor` 在每个调度周期执行一次巡检（间隔可配置），检测多类困境信号：`repeated_failures`（同一 SPEC 连续失败）、`flapping`（状态机空转回路 `ready↔implementing`）、`stuck`（run 卡死停滞）、`merge_streak`（合并反复失败）、`blocked_stuck`（`blocked` 滞留）、`daemon_errors`（守护进程异常）、`family_explosion`（fix 族爆炸），以及 `dispatch_stalled`（派发停滞）等。每个信号都有独立的检测逻辑和判定阈值，检测结果通过 `_handle_signal()` 进入处置流程。

### 分级流向与冷却

困境信号按严重度分流：`critical` 和 `major` 级别的信号唤起 Administrator（`_invoke_administrator()`），`minor` 和 `auto-resolve` 级别走自动解决。Administrator 的唤起有冷却期：同一信号在冷却期内只记日志不重复唤起，防止反复触发导致的告警风暴。冷却期的配置键是 `admin.escalation_cooldown_minutes`，具体默认值参见[调度与治理规则](06-governance.md)。

### 告警生命周期闭环

`core/alert_lifecycle.py` 解决的是告警与 spec 状态脱钩的问题：升级告警产生后，spec 的后续状态变化（恢复、验证通过、到达终态）不会自动回写告警，导致管理员视图被历史噪音淹没。模块提供纯函数判定逻辑：关联 spec 状态到达终态（`done`/`pushed`）或离开 `blocked` 即视为条件解除，告警被标记为已自动闭环。结构化触发条件（`trigger` 字段）在告警写入时埋点（`build_trigger()` + `attach_trigger()`），使闭环判定有明确的依据而非猜测。无 `trigger` 字段的存量告警按 `signal_type` 推断 condition 做存量回填。

`_send_human_escalation_alert()` 和 `_escalate_env_blocked()` 分别处理常规升级告警和环境阻塞告警：前者在 Dashboard 红色横幅展示，后者在 SPEC 详情页标记 `blocked-env` 状态。两种告警最终都写入 `admin_alerts.json`，运维记录页统一展示，每条告警带信号类型、严重度、证据与处置建议。

## 机制衔接：纵深防御的完整链条

回顾五类机制的衔接：声明 lint 在 SPEC 撰写阶段拦截格式与路径错误（零成本拦截，不消耗 Agent run）；门禁在状态转换和报告校验时做结构化硬校验（只信数据结构，不信 LLM 判断）；运行时守卫在 Agent 执行期间拦截越权操作（worktree 隔离 + 图片读取禁止 + 场景分批）；自愈链路在异常中断后自动恢复到可调度状态（boot recovery + 恢复复查 + sweeper + autostash 回收）；告警系统在自愈无法覆盖时升级人工。每一层都为下一层兜底，每一层的失效模式都被下一层覆盖。需要了解具体阈值与运维参数时，参见[调度与治理规则](06-governance.md)；需要了解配置项的完整清单，参见[配置参考](09-config.md)。
