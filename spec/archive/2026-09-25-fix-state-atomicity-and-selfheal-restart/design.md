## Context

`.fenix/STATE.md` 是 daemon 的 SPEC 状态机存储，唯一写入者是 `core/state_machine.py:StateMachine`。

**当前写入形态**：`update_spec`（:701）执行 `specs = self.read_all()` → `specs[name].update(updates)` → `self.write_all(specs)`。其中 **read 与 write 之间不持锁**——`write_all` / `_write_all_locked`（:566）自身才加 `.STATE.md.lock` 的 flock。并发的两个 `update_spec`（daemon 的多个 worker 线程 + dashboard 独立进程）会各自读到同一份快照、各自改一处、各自整体写回，后写者用陈旧快照覆盖先写者的改动（丢失更新）。

**既有正例**：`_bump_counter`（:596）已采用「锁内 read→改→`_write_all_locked`→回读校验」范式（fix-budget-counting-semantics D2），证明该修法在本代码库可行且已被验证。

**2026-09-21 实证（本 SPEC 的触发事故）**：
- 解冻 3 个 spec 后 daemon 并发派发 3 个评审 run；`add-timeline-gate-failure-display` 的 `reviewer_run` 于 `04:45:49.938` 被写入，但 STATE.md 落定值来自 `04:45:49.186` 的旧快照（`updated` 字段可证），`reviewer_run` 回退 `null` → `consume_review_result` 开头 `if not run_id: return False` 静默早退 → 评审 run 已收工、结果文件已合法落盘，spec 永停 `reviewing`。
- 同一竞态在冻结路径上表现为：`freeze_for_human` 写入的 `error`（内嵌「原状态 reviewing」，是 `parse_orig_status` 解冻目标解析的唯一来源）在后续被清为 `null`；实测 STATE.md 全部 277 条 spec 的 `error` 均为 `null`，`grep -c "用户指令冻结"` = 0。解冻只能回退 `ready`（而非原状态）。

**当前 `_is_idle`（fenixd.py:979）**：`pm_engine._active_runs == 0` 且 admin 池无在途。2026-09-21 事故：评审 run `spec-review-add-code-review-auto-fix-1789964873` 在 API 520 长重试期转录不增长，被判为空闲，连续 120s 后 `stale_code_selfheal`（fenixd.py:1001 `_maybe_stale_selfheal_tick`）写入 `restart_request`，supervisor SIGTERM 杀掉该在跑 run。

## Goals / Non-Goals

**Goals:**
- STATE.md 的所有 read-modify-write 写入在并发下 MUST NOT 丢失更新（消除 `update_spec` 竞态）。
- 冻结写入的 `error`（含「原状态 X」）MUST 可靠持久化，直至解冻被正确读取。
- `stale_code_selfheal` MUST NOT 在存在未收口在飞 run（含停滞/API 重试中）时触发重启。

**Non-Goals:**
- 不改 STATE.md 的文件格式、字段集合与序列化形态。
- 不改 supervisor 的 `restart_request` 协议语义（自愈仍复用该协议）。
- 不重写状态机整体（仅收敛写入原子性 + 加强空闲判定）。
- 不处理模型链 failover（`maomaoai/deepseek-v4.1-flash` 无效模型名导致评审 `Exit code:1` 冻结）——那是配置侧问题，另行处置，不在本 SPEC。

## Decisions

### D1: `update_spec` 收进 `.STATE.md.lock` 内的 read-modify-write
把 `read_all` → mutate → 持久化 三段收进同一把 `.STATE.md.lock` 的 `flock(LOCK_EX)` 内，采用 `_bump_counter` 同款范式。**备选**：乐观 CAS 重试（改动面更大、需给 STATE.md 加版本号）；全进程单例锁（不适用——dashboard 是独立进程，必须跨进程文件锁）。**约束**：同进程对同一文件重复 `flock` 会自阻塞（`_write_all_locked` 注释已载明），故锁内 MUST 调 `_write_all_locked` 而 MUST NOT 再调 `write_all`。

### D2: 同源收敛所有 STATE.md 写入路径
`add_spec` / `remove_spec` / `update_spec` / `_bump_counter` 统一走 D1 的锁内原子路径。三条路径的 read-modify-write 均非原子（`state_machine.py:703-731` / `:969-987` / `:993-1006`），须一并收敛；`remove_spec` 的 docstring（`:991-1000`）现声称「a concurrent writer cannot resurrect the entry」——该不变式在现状下**不成立**（并发写者持陈旧快照整体回写即可复活条目），收敛后 MUST 同步订正该注释，MUST NOT 留下与实现不符的不变式声明。

**「无日志写入」的调用者已定位（取代草案的待查项）**：生产代码中对 `write_all` 的直接调用仅 3 处，全部在 `core/state_machine.py`（`:731` / `:987` / `:1006`）且均有日志——静默来源不是写入路径缺失日志，而是**写入者未获注入 logger**：`StateMachine.__init__`（`:498-502`）在 `logger=None` 时兜底为 `_NullLogger`（`:473-489`，全部方法空实现），而 dashboard 侧多处以无 logger 形态构造：

- `core/dashboard/data/spec_archive.py:145` — `StateMachine(proot / ".fenix" / "STATE.md")`（归档/删除路径，会走 `remove_spec`）；
- `core/dashboard/routes/evolution_routes.py:30` — `StateMachine(..., None)`；
- `core/dashboard/routes/code_review_routes.py:243` — `StateMachine(..., None)`。

这三处正是 2026-09-21 观测到的「`updated` 变了但 `fenixd.log` 无 "Updated SPEC" 记录」的成因（dashboard 为独立进程，与 daemon 的 `update_spec` 并发 → 同时满足「无日志」与「跨进程丢失更新」两个特征）。故 tasks 1.3 的「写入必留痕」MUST 覆盖这三处构造点的 logger 注入，仅改 `core/state_machine.py` 无法达成该 Requirement。

### D3: 空闲判定纳入「未收口的在飞 run」——缺口在评审车道，不在 `_active_runs` 递减

**根因（实现期已核实，取代本 SPEC 草案的 `_active_runs` 误减假设）**：`_is_idle()`（`fenixd.py:979-999`）只读 `pm_engine._active_runs` 与 admin 池在途数。而**评审 run 从不计入 `_active_runs`**——`DispatchQueue` 的派发分支对 `agent_type == "spec-review"` 显式 `MUST NOT 增减 _active_runs / _active_priorities`（`core/pm_engine/dispatch/queue.py:556-564`），只把 spec 记入独立的 `_active_reviews` 集合。因此**只要在飞的是评审 run，`_active_runs` 恒为 0**——`_is_idle()` 判空闲与「run 是否停滞」无关，`_active_runs` 的递减时机本身没有缺陷。故本 SPEC 的修法 MUST NOT 以「核对 `_active_runs` 递减时机」为实现路径（照此核对会得出「无需修改」的错误结论，目标落空）。

**MUST 复用的既有判据（不得新造在飞判定）**：评审在飞判定的唯一既有权威是双判据合取，已用于派发守卫（`core/pm_engine/engine.py:750-773`）：

1. `PMEngine.is_review_in_flight(spec_name)`（`core/pm_engine/engine.py:3522`，只读查询 `_active_reviews`）——覆盖「条目已出队、`reviewer_run` 锚点尚未落盘」的窗口；
2. `LivenessSupervisor.reviewer_in_flight(spec_name, reviewer_run)`（`core/agent_runner/liveness.py:454`）——分层判据为 `_active_reviews` → **进程表 `running_run_ids()`** → 流文件新鲜度 → 陈旧锚点。**判据 2（进程表）正是「停滞 run 仍算在飞」的成立依据**：评审 run 以子进程形态全程登记在 `_running_agents`，API 长重试期间转录不增长但进程仍存活 → `(True, "process")`。MUST NOT 仅用流文件新鲜度（`_run_stream_alive`）作在飞依据——停滞 run 的流本就不增长，会退化为判据 4 的 `stale`，缺陷原样复现。

**MUST NOT 只加 `_active_reviews` 一个维度**：`_active_reviews` 的释放时点**早于** `dispatch_review`（`queue.py:2129`，`MUST NOT 晚于四步链锚点 reviewer_run 落盘`），锚点落盘后该登记即消失，`_active_reviews` 单独判据会漏掉评审 run 的绝大部分生命周期。必须以「`reviewer_run` 锚点 + `reviewer_in_flight`」接力。

**实现形态**：`_is_idle()` 在既有两维度之外，增补「STATE 中 `reviewer_run` 非空的 spec 逐个经上述双判据复核」。为免 1s 粒度轮询（`fenixd.py:586` `time.sleep(1)` → `:597` `_maybe_stale_selfheal_tick` → `:1067` `_is_idle()`）引入每 tick 全量扫描开销，MUST 以「短路 + 候选收窄」约束：候选仅取 `reviewer_run` 非空的条目（拒绝全量 `read_all()` 逐条判），命中任一在飞即立即返回 False，不做其余条目判定；多 spec 复核可加短 TTL 缓存（TTL MUST 显著小于 `idle_confirm_seconds`）。

**反向约束**：对确已死亡/收口的 run MUST NOT 永久占位（否则自愈永不触发）——`reviewer_in_flight` 判据 4 已对「run 已终态但锚点残留」返回 `(False, "stale")`，即天然不占位；以该判据为界，MUST NOT 引入新的永真条件。

### D4: 回归以「并发交错」与「停滞 run」两个契约为锚
新增测试 MUST 能复现原缺陷：① 两线程/两路径并发 `update_spec` 不同字段，断言两个字段的改动都保留（当前实现会丢一个）；② 冻结 error 在一次并发写入后仍可被 `parse_orig_status` 读出原状态。③ 构造一个「登记在册但转录停滞」的 run，断言 `_is_idle()` 返回 False、`restart_request` 不被写入。

## Risks / Trade-offs

- **[加锁引入死锁]** → 严格遵循「锁内只用 `_write_all_locked`」，禁止锁内再 `write_all`；沿用 `_bump_counter` 已验证的调用结构。
- **[锁粒度变粗致写放大]** → 单进程内写入本已串行；跨进程（dashboard）写入频率低，可接受。
- **[空闲判定加强致自愈永不触发]** → 以「run 是否收口/进程是否存活」为界，不用转录新鲜度作唯一依据（停滞 run 转录本就不增长）；确保死亡 run 会被正常清理出在册集合。
- **[error 清理路径未定位]** → **已关闭**：静默写入者即 dashboard 侧无 logger 构造的三处（D2）。`error` 丢失机理确认为跨进程丢失更新（dashboard 持陈旧快照整体回写覆盖 daemon 写入的冻结 `error`），由 D1/D2 的锁内原子化消除根本成因；测试固化「冻结后任意并发写不丢 error」。
- **[dashboard 侧注入 logger 的跨进程可达性]** → 三处构造点分布在不同 dashboard 路由/数据模块，实现期 MUST 逐个核对实际写入路径（`spec_archive.py` 走 `remove_spec`；两条 route 的写入面在实现期确认），MUST NOT 只改其中一处便宣称「写入必留痕」已达成。
- **[改写 MODIFIED Requirement 时遗漏同能力互斥条款]** → 本变更改的是 `stale-code-selfheal` 的「空闲感知的陈旧自愈触发」，而该能力另有「空闲判定语义」Requirement（`spec/archive/2026-09-18-add-stale-code-selfheal/specs/stale-code-selfheal/spec.md`）把「空闲」定义为 `_active_runs == 0` + admin 池空、并声明 MUST NOT 扫描外部进程列表；若不同步改写，两条 MUST 会指向相反方向。本 SPEC 已在 `specs/stale-code-selfheal/spec.md` 同步 MODIFIED 该条（并改写其「MUST NOT 扫描外部进程列表」为「MUST NOT 以外部 `ps`/`/proc` 扫描反推」，以容纳进程表判据 `running_run_ids()`——该判据读的是 daemon 进程内注册表，非外部进程列表）。实现期 MUST 同批落地，MUST NOT 只改其一。

## Migration Plan

纯代码修复，无数据迁移。上线即通过 daemon 优雅重启（`restart_request`）载入新代码生效。回滚 = 回退代码版本。

## Open Questions

（草案的两项均已由评审期取证关闭，实现期按 D2/D3 的结论推进即可。）

- ~~2026-09-21 `updated=03:43:24` 那次「无日志写入」的确切调用者~~ → **已定位**：非 `write_all` 路径缺失日志，而是 dashboard 侧以 `logger=None` 构造 `StateMachine` 触发 `_NullLogger` 兜底（D2 列出的三处构造点）。
- ~~停滞 run 的「在册未收口」判据具体字段（`_active_runs` vs registry vs run 流文件末行终态）~~ → **已定**：`_active_runs` 不覆盖评审车道（评审 run 从不递增它），MUST 复用 `PMEngine.is_review_in_flight` + `LivenessSupervisor.reviewer_in_flight` 的双判据合取；进程表判据（判据 2）负责覆盖停滞 run，流文件新鲜度 MUST NOT 单独作在飞依据（D3）。
- **待实现期确认的唯一残留项**：`_is_idle()` 增补评审维度后的每 tick 开销实测（候选收窄 + 短路 + 可选短 TTL 缓存，见 D3）——若在 1s 粒度下开销可观，以缓存方案收敛，不得放弃该维度。