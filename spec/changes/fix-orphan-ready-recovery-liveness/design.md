## Context

Fenix daemon 里「一个 SPEC 该不该被派发实现」由两条独立链路回答，二者共用同一个存活判据：

- **派发闸门**：`PMEngine._on_spec_ready()` —— `has_active_worktree` / `_dispatch_backoffed` / `start_after_pending` / `_dependencies_satisfied` / 冷却与单飞去重。
- **恢复链路**：`EventBus._recover_ready()` —— 由 `full_scan()` 逐条驱动，对 `ready` 态孤儿 SPEC 判存活后重触发 `spec_ready`。

两条链路在**「这个 SPEC 是否还有活着的 attempt 子进程」**这一点上必须给出一致答案，但它们各自独立求值，且都落到同一个探针：`AgentRunner.has_live_attempt(spec)`（`core/agent_runner/liveness.py:240`）。

该探针的判定顺序是：

1. `_pgrep_live_attempt(spec)` —— `pgrep -f "worktrees/{impl,verify}-<spec>-"`（`liveness.py:264`）
2. **未命中时回退** `_stream_recent(spec, LIVE_ATTEMPT_STREAM_WINDOW_SECONDS=120)`（`liveness.py:284`）—— glob `.fenix/runs/{impl,verify}-<spec>-*.jsonl`，**只看 mtime**，任一落在 120 秒内即返回 True。

第 2 条回退是本次事故的根因所在。它的设计意图是「resume 孤儿进程通常持续写流，所以流新鲜 ≈ 进程还在」（`liveness.py:245-247` 原文注释）；但**框架自己主动杀死的 run 也会留下新鲜的流**——而且留下的还是一行**明确的终态**。

### 事故取证（2026-09-17）

```
03:26:26  Sent SIGTERM to running agent: impl-fix-observability-gaps-1789605764-a1-r1
03:26:27  append_run_error(...) → r1.jsonl 末行 {"type":"error","exit_code":143}
          STATE: status=ready, _retry_count=1，预算回退 used 0/6
03:26:35  daemon 重启；启动终态补写扫描检查该文件 → 末行已终态 → 不改动
03:26:40  首轮 full_scan → _recover_ready → _ready_has_live_child
              ├─ _pgrep_live_attempt        → 无进程        → False
              └─ _stream_recent(120s)       → mtime 距今 13s → **True**
          → "Recovery: skip 'fix-observability-gaps' — live child present"
03:52:55  SPEC 才被派发（靠一次无关的自愈重启，而非恢复链路）
```

三处证据共同确认这是**假阳性**而非真实存活：

- run 流末行是 `{"type": "error", "error": "Exit code: 143", "exit_code": 143}` —— `RUN_TERMINAL_EVENT_TYPES` 成员，写侧语义就是「run 已明确终结」；
- 同一文件在 03:26:35 的启动终态补写扫描中被跳过（`_file_has_terminal_event` 判 True）——**框架自己在另一个地方已经承认它死了**；
- `_pgrep_live_attempt` 未命中，进程确实不存在。

也就是说：**恢复链路上有两个函数读同一个文件，一个判定它已终结、另一个判定它仍有生命。**

### 第二处缺陷：孤儿 ready 没有短周期事件源

`_recover_ready()` 的唯一调用方是 `full_scan()`。`full_scan()` 的触发源只有三个：daemon 启动、`.fenix/STATE.md` 变化、`schedule.poll_interval_minutes`（缺省 30）周期扫描。

第二个触发源对本场景**结构性失效**：`_dispatch_changes()` 只为 `old_status != new_status` 的 SPEC 产出事件（`event_bus.py:467`），而孤儿 ready 的特征恰恰是「status 一直不动」。于是这类 SPEC 的恢复延迟被硬编码为「最坏一个扫描周期」。

两处缺陷是**叠加**关系，而非二选一：修好存活判据后，本轮恢复确实会立刻成立；但只要恢复时机仍绑在 30 分钟扫描上，任何**其他**形式的「首轮恢复没成功」（例如首轮恰逢并发满槽、或首轮被闸门拦下）都还要再等 30 分钟。反之，只加短周期精触发而不修判据，每个 60 秒 tick 都会被同一个假阳性挡住，毫无收益。

## Goals / Non-Goals

**Goals:**

- **判据修正**：`has_live_attempt()` 的流新鲜度回退 MUST 区分「有写活动」与「有生命」——末行已成终态的流文件代表该 run 已终结，不得再作为存活依据。判据口径 MUST 复用框架既有单源，不得另立集合。
- **时机补齐**：孤儿 `ready` 的恢复在 daemon 主循环既有的 60 秒计时段中获得精触发，恢复延迟从「最坏 30 分钟」降到「最坏 60 秒」。
- **零语义漂移**：精触发与 `full_scan` 恢复走**完全同源**的处理路径与闸门；不缩短 `poll_interval_minutes`、不放宽任何派发闸门、不新增判据、不新建线程。

**Non-Goals:**

- 不修改 `admin_monitor` 的 `orphaned_state` 信号及其 5 分钟监视周期（覆盖 `implementing`/`testing`，与本次 `ready` 形态互补且已足够快）。
- 不修改 `post-recovery-patrol` 的闭环复查语义（`recovery_watch` 仍为 15 分钟量级的兜底告警通道）。
- 不缩短 `schedule.poll_interval_minutes`，不改动 `full_scan()` 的触发源与语义。
- 不重构派发队列、优先级/并发/预算闸门、状态机合法转移表。
- 不做存活探针的三处同型点中的另外两处（见 D5 的显式处置）。

## Decisions

### D1：终态口径复用 `RUN_TERMINAL_EVENT_TYPES`，且**不含** `superseded`

回退路径的排除集合**直接复用** `core/agent_runner/liveness.RUN_TERMINAL_EVENT_TYPES`（`result` / `error` / `interrupted` / `cancelled`），不新增常量、不写字面量列表。理由：该集合已是框架的单一真源（读侧 `_RUN_TERMINAL_STATUS_MAP` 有防漂移测试 `tests/test_dashboard_data.py:488` 锁定必须覆盖它全集），存活判据再引入第二套口径必然重演 `fix-robustness-edge-cases` 记录的「多口径互相漂移」事故。

**`superseded` MUST NOT 纳入**——这是本设计最容易出错的一点，必须显式禁止：

`superseded` 由原地重试通道在**弃置旧产物文件**前补写（`runner.py:2063` / `runner.py:2228`），语义是「本文件被弃置，run 在新 sub_run_id 文件继续」——**run 并没有死**。若把 superseded 也算作终结，则 artifact-gate 原地重试的退避窗口内（`transient_backoff_schedule` 缺省 `30,60,120` 秒，最长 120s，恰好落在流新鲜度窗口内）：

1. 旧文件末行 = `superseded` → 回退路径判「不存活」；
2. 新文件此刻可能尚未产生（退避 sleep 中）；
3. → 恢复链路判孤儿 → 重派 → 与退避期结束后的原地重试**双跑同一 SPEC**。

故终态集合取 `RUN_TERMINAL_EVENT_TYPES` 四类，**显式排除 superseded**，并以此写回归用例（D6/T4）。

### D2：新增尾部终态判定助手，与 `_file_has_terminal_event` 并列而非复用

`liveness.py:77` 已有 `_file_has_terminal_event(run_file)`，但它**全文件逐行扫描**且语义是「文件里**出现过**终态事件」——直接拿来做存活判据有两个错误：

- **语义错**：出现终态后 run 仍可能继续（`interrupted` 之后 `error` 追加、`transient_retry` 之后新 sub_run_id 继续写别的文件不涉及本文件，但同文件内的 `result` → `superseded` 序列真实存在）。存活判据要的是「**末行**是否为终态」，即 `dashboard/data/runs.py:classify_run` 已确立的「终态后置不变量 ⇒ 只看末行」口径。
- **成本错**：`_stream_recent` 在派发热路径上被反复调用，而 9.9 MB 的 run 流（本次事故文件确实是这个量级）全量逐行扫描不可接受。

故新增 `liveness._file_tail_is_terminal(run_file)`：**从文件尾部按字节窗口 seek 读取**，解析末条非空行，判定其 `type` 是否属于 `RUN_TERMINAL_EVENT_TYPES`。窗口读取 MUST 复用 `core/dashboard/data/runs.py:293` `_read_run_lines` / `_READ_RUN_TAIL_WINDOW`（`:258`）既有的「按字节窗口 seek + 首行残段丢弃 + 不足则回退全量」范式（该函数把「窗口首行是上一行残段必须丢弃」的坑写在注释里，直接照抄可避免重蹈 `overview 活跃 Agent 数虚高` 事故）。**复用形式为「照范式自实现」，不是 import**：`core/agent_runner/` 包内现无 `core.dashboard.*` 反引先例（`core/event_bus.py:370`、`core/pm_engine/engine.py:21` 有先例但不在本包），liveness 又在派发热路径上，新增跨层 import 不值得。窗口/回退常量与解析容错（损坏行 → 视为非终态，fail-open 保持既有行为）在实现处固化。

**注意方向**：解析失败 MUST fail-open 到「非终态」= 仍视为存活。判据的保守侧是**不误杀在跑的 run**——把活 run 判死会导致双派发（烧钱且可能污染分支），把死 run 判活只损失一个恢复周期（本就有的兜底，且被 D3 缩短）。这与 `worktree_manager.STALE_LOCK_IDLE_SECONDS` 分支「进程扫描未命中但流仍在增长：保守视为持锁」是同一条保守原则。

### D3：精触发挂在主循环既有 60 秒计时段，逐条复用 `_recover_ready`

在 `fenixd.py` 主循环既有的计时段模式（`config_check_ts` 30s / `recovery_watch_ts` 60s / `scheduling_check_ts` 60s / `orphan_clean_ts` 600s）中新增一段 60 秒计时段，调用 `EventBus` 上的新入口；该入口**逐条复用既有 `_recover_ready()`**，不复制判据：

```
recover_orphan_ready():
    for name, entry in state_machine.read_all().items():
        if entry.get("status") != "ready": continue
        if entry.get("_cancelled_hold"): continue                # 有意等待：人工取消保持
        if self.pm_engine._dispatch_backoffed(entry): continue    # 有意等待：派发退避期
        self._recover_ready(name, entry)      # ← 既有方法，判据一字不改
```

**两道有意等待早退的落点与依据（核对结论，2026-09-17）**：

- `_recover_ready()` 现有闸门只有两道：`start_after_pending`（`event_bus.py:268-277`）与 `_ready_has_live_child`（`event_bus.py:282`）。它**没有** `_dispatch_backoffed` 判定，`_on_spec_ready()`（`core/pm_engine/engine.py:316-425`）内也**没有** `_cancelled_hold` 读取点——恢复链路对这两种「有意等待」不设防。
- 缺这两道闸门的后果（60 秒粒度才暴露）：`_handle_dispatch_lock_conflict` 会把 `error` 写成「worktree already active (lock conflict); backoff until <ISO>」并落 `_dispatch_backoff_until`（`dispatch.py:108-116`）；退避期内精触发仍会走完 `_recover_ready` 的「清 error → 重触发」，于是每个 60 秒 tick 产生一次 STATE.md 全量重写 + 一条误导性 INFO「Recovery: re-triggering implement for orphan ready …」，同时抹掉 Dashboard 应按既有能力读到的退避原因。
- 早退复用既有判据而非新判据：`_dispatch_backoffed` 读 `_dispatch_backoff_until`（`dispatch.py:1427-1439`），`_cancelled_hold` 是框架既有的取消保持标记（`core/state_machine.py:305/659/1023-1032`、`core/agent_runner/runner.py:3168`）。故 D3「不另立判据」的约束未被违反。
- 落点选在**精触发入口**而非 `_recover_ready` 内部：`full_scan` 兜底路径的既有行为不因此改变（本次不扩大改动面），而恢复主体仍是同一个 `_recover_ready`，两条路径的恢复语义依旧同源。
- `_cancelled_hold` 现状由 `state_machine.recover_interrupted`（重启恢复）与 runner 复查消费；**所有写入点都保持 implementing/testing 原状**（`dispatch.py:1241-1262`、`2551-2567`、`3132-3142`，`pm_engine/verification/pipeline.py:740-753`、`1237-1244`），故 `ready + _cancelled_hold` 当前不可达——本闸门属**防御性收紧**，防止未来出现「保持态 + ready」写入点后精触发把人工取消的 SPEC 重新派发。

选择「复用整个 `_recover_ready`」而非「另写一份轻量探测」的理由：恢复语义（`start_after_pending` 未到期 / 存活子进程 / 清 error 后重触发）只能有一个实现点。若精触发另写一份，两条路径必然在某次修改后分叉，出现「30 分钟扫描说该派、60 秒精触发说不该派」的双口径——这正是 `fix-dispatch-wakeup-gap` D2/D3 已经踩过并立规反对的模式。

不新建线程、不新建 Timer：`full_scan()` 的周期扫描线程仍每 30 分钟兜底，精触发只是一次额外的同步调用（百量级 SPEC 的内存字典遍历 + 每 spec 一次 `read_one`/`has_active_worktree`，`full_scan` 实测中位 26.7 ms 为其上界参考）。

### D4：稳态零 STATE 写入——空的 error 清空 MUST NOT 回写

这是让 60 秒精触发**不会**变成自激/噪声源的关键。

`_recover_ready()` 当前**无条件**执行 `state_machine.update_spec(name, {"error": None})`（`event_bus.py:297`）。该写回在 30 分钟粒度下无伤，但按 60 秒执行会让**每一个**健康 ready SPEC（例如正排队等并发槽的）每 60 秒产生一次 STATE.md 全量重写 + 一条 `Updated SPEC` 日志。

故：**error 清空写回改为仅在 `entry.get("error")` 非空时执行**。语义完全等价（对已是 None 的字段写 None 本就是空操作），且顺带消除了 `full_scan` 路径上的同类噪声。写回的必要性论证保留在注释中（`event_bus.py:288-293` 已写明「error 清空必须写回 STATE.md，否则下轮 full_scan 仍读到此 error」——该论证针对的就是 error 非空的情形）。

有界性论证（无需额外节流阀）：

- 稳态（error 为空、无存活子进程）→ **零 STATE 写入**；
- 重复触发被既有闸门吸收，**吸收点是队列去重而非冷却窗口**（代码核对结论）：`_enqueue` 按 `(spec_name, agent_type)` 去重（`core/pm_engine/dispatch.py:269-275`），已入队等待并发槽的 SPEC 不会被 60 秒重试重复入队。注意 `_pending_dispatches` 单飞与 `_last_dispatch_at` 10 秒冷却（`DISPATCH_COOLDOWN_SECONDS = 10`，`core/pm_engine/engine.py:81/327-333`）只吸收**秒级**重复触发，**不足以**吸收 60 秒间隔的重试——有界性依赖队列去重与 D3 的两道有意等待早退闸门，不得依赖冷却窗口；
- `_on_spec_ready()` 内既有闸门（冷却/单飞/`has_active_worktree`/`_dispatch_backoffed`/`start_after`/依赖）精触发不绕过。**方位校正**：`_instant_fail_cooled`（秒挂冷却）与并发闸 `max_concurrent` 在 `_process_queue` 的候选筛选与调度处（`dispatch.py:437`、`503`、`378-393`），**不在** `_on_spec_ready()` 内——它们经 `_on_spec_ready → _enqueue → _process_queue` 链路同样生效，不会被精触发绕过；
- 唯一的自激路径是「清 error → STATE 变 → watcher 事件」。`_dispatch_changes()` 只为 **status 变化**（及新 SPEC 首次出现）产出事件，孤儿 ready 的 status 不变，故**不产生任何事件**，无自激。

### D5：存活探针三处同型点——本 SPEC 只修 1 处，另 2 处书面 defer

「mtime 新鲜 ⇒ 过程仍活着」这一谬误在框架里有三处同型实现，本次取证**只确认第 1 处是本次事故的直接成因**，另两处按证据与归属分别处置：

| # | 实现点 | 本次是否命中 | 处置 |
|---|---|---|---|
| 1 | `liveness._stream_recent`（→ `has_live_attempt`，`_ready_has_live_child` / `_attempt_still_alive` / `_sibling_has_live_agent` 共用） | **是**（直接挡住恢复） | **纳入本 SPEC**（D1/D2） |
| 2 | `worktree_manager._latest_stream_mtime`（→ `has_active_worktree` / `refresh_locks` 的「无进程但流新鲜 → 保守持锁」） | 否 | **书面 defer**（承接方：worktree 活性） |
| 3 | `admin_monitor._has_recent_spec_run`（→ `spec_is_undriven` → `orphaned_state` 信号） | 否 | **书面 defer**（承接方：`evo-orphaned-state-probe-calibration`，该 SPEC 在飞且正在改这一判定口径） |

第 2 处的 defer 理由：本次事故中 daemon 重启后内存锁表为空，`has_active_worktree` 走的是**进程表分支**并正确返回 False——同型谬误存在但**未在此次被触发**；且该分支的保守语义直接防的是「误释放锁 → 双派发」，收紧它对锁释放时序的影响面远超本次事故证据支持的范围。第 3 处的 defer 理由：判定口径已被在飞的 `evo-orphaned-state-probe-calibration` 占用，同批修改会造成两个 SPEC 撞同一函数，下游合并必然冲突。

defer MUST 以**注释 + `findings`/tasks 登记**双落地（对齐 `fix-robustness-edge-cases` 1.1 的「纳入本 SPEC 或书面 defer 并注明承接方」约定），不得静默忽略。

### D6：回归用例锁定「末行」语义与 superseded 边界

三组用例必须有，且第三组直指 D1 的风险点：

1. **末行终态 ⇒ 不存活**：run 流末行为 `error` / `interrupted` / `cancelled` / `result`，mtime 落在 120s 窗口内，`_pgrep_live_attempt` 判否 → `has_live_attempt` MUST 返回 **False**（复现本次事故形态）。
2. **末行非终态 ⇒ 仍存活**（fail-open 方向）：末行为普通事件（如 `assistant`）且 mtime 新鲜 → MUST 返回 **True**（活 run 不被误杀）。
3. **`superseded` 末行 ⇒ 仍存活**：末行为 `superseded` 且 mtime 新鲜 → MUST 返回 **True**（原地重试窗口内不得判死，D1）。

再加一组**精触发**用例：孤儿 ready（error 非空 + 无存活子进程 + 无 `start_after`）在精触发下被重派；稳态 ready（error 为空）在精触发下**零 STATE 写入**（D4），以此把「60 秒零写」变成可执行断言而非口头承诺。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| **判据收紧误杀在跑的 run**（把活 run 的流判成终态 → 双派发） | fail-open 方向固定：解析失败/末行非终态/窗口不足 → 一律视为存活（D2）。且 `_pgrep_live_attempt` 是**第一判据**，只有进程表确实无命中才走回退；真实在跑的 run 会被 pgrep 直接命中，回退路径根本不会被求值 |
| **`superseded` 误纳入终态集合**，在 artifact-gate 原地重试退避窗（最长 120s，与流窗口同量级）内造成双跑 | D1 显式排除 + D6 用例 3 锁定；用户确认拒绝「顺手加进去」 |
| **60 秒精触发放大 recove ry 副作用半径**（`event_bus.py:266` 注释记载的历史顾虑：`add-spec-status-modal-budget` 曾每小时重验 9 轮） | 精触发**不新增判据**、不绕过任何闸门；稳态零 STATE 写入（D4）；有界性论证见 D4；`full_scan` 仍为兜底、间隔不变 |
| **精触发与 `full_scan` 恢复行为分叉** | 精触发直接调用同一个 `_recover_ready()`，无第二实现点（D3） |
| **两处同型点未修留下同类事故** | D5 的书面 defer + 承接方登记 + 注释交叉引用；第 3 处已有在飞 SPEC 承接 |
| 等待 `start_after` / 派发退避 / `_cancelled_hold` 的有意等待被精触发误派或误写 | `start_after` 为 `_recover_ready` **既有**门（`event_bus.py:268-277`）；`_dispatch_backoffed`（`_dispatch_backoff_until` 未到期）与 `_cancelled_hold` **在恢复链路上并无既有守卫**（`_recover_ready` 与 `_on_spec_ready` 均不读 `_cancelled_hold`，`_recover_ready` 不读 `_dispatch_backoff_until`），故按 D3 在精触发入口显式早退——复用既有判据，不新增判据，且 `full_scan` 路径语义不变 |
| `_cancelled_hold` 与 `ready` 组合当前不可达（所有写入点保持 implementing/testing 原状），早退闸门暂无实际拦截对象 | 仍按 D3 落地为防御性收紧并补用例（3.10），避免未来新增写入点后精触发把人工取消的 SPEC 重新派发 |

## Migration

无数据/配置迁移。`schedule.poll_interval_minutes` 等既有配置键语义与缺省值均不变；本次不新增配置键（故不触发「新增配置项必须带 Dashboard 界面」约束）。
