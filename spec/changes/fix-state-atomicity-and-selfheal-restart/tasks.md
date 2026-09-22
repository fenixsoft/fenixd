# Tasks: fix-state-atomicity-and-selfheal-restart

## Deliverables

```yaml
- path: core/state_machine.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/dashboard/data/spec_archive.py
  kind: modify
- path: core/dashboard/routes/evolution_routes.py
  kind: modify
- path: core/dashboard/routes/code_review_routes.py
  kind: modify
- path: tests/test_state_write_atomicity.py
  kind: new
- path: tests/test_stale_selfheal_idle.py
  kind: new
```

> 只读依赖（MUST NOT 改其语义，仅复用既有判据）：`core/pm_engine/dispatch/queue.py`（`_active_reviews`、
> `is_review_in_flight` 的持有方）、`core/agent_runner/liveness.py`（`reviewer_in_flight` 分层判据）。
> 若复用中发现确需在其内改动，MUST 先回到 SPEC 补交付清单，MUST NOT 隐式扩面。

## 1. STATE.md 写入原子化

- [x] 1.1 将 `StateMachine.update_spec` 的「读 STATE.md → 内存改目标字段 → 持久化」三段收进单次 `.STATE.md.lock` 的 `flock(LOCK_EX)` 内（对齐 `_bump_counter` 既有范式）；锁内 MUST 调 `_write_all_locked`，MUST NOT 再调 `write_all`（同进程重复 flock 会自阻塞）
- [x] 1.2 收敛其余 STATE.md 写入路径至同一锁内原子路径：`add_spec`（`state_machine.py:969-987`）、`remove_spec`（`:993-1006`）均为非原子 read-modify-write，与 `update_spec` 同源改造；`_bump_counter` 已是正例，仅核对无需改动。同步订正 `remove_spec` docstring（`:991-1000`）中与实现不符的「a concurrent writer cannot resurrect the entry」声明
- [x] 1.3 消除无日志的静默写入路径：静默成因**不是**写入路径缺日志，而是写入者未获注入 logger——`StateMachine.__init__`（`:498-502`）在 `logger=None` 时兜底 `_NullLogger`（`:473-489`）。MUST 为 dashboard 三处无 logger 构造点注入真实 logger：`core/dashboard/data/spec_archive.py:145`、`core/dashboard/routes/evolution_routes.py:30`、`core/dashboard/routes/code_review_routes.py:243`；并保持 `update_spec` 的「含 spec 名与本次所改字段键」日志在原子写成功后输出（MUST NOT 因加锁漏掉日志）

## 2. 冻结 error 的可靠持久化

- [x] 2.1 「无日志写入」的调用者**已定位**（见 1.3，dashboard 无 logger 构造点），本任务不再作开放式排查：核对三处构造点的实际写入面（`spec_archive.py` 走 `remove_spec`；两条 route 的具体写点实现期确认），确保注入 logger 后每条写入路径均有留痕。**有界收口**：若某构造点实际不产生写入，记录判定依据后从清单移除即可，MUST NOT 为穷尽可能性而无界扩大排查
- [x] 2.2 核对 `freeze_for_human` / `freeze_spec` / 解冻 / `consume_review_result` 四条路径对 `error` 的写入与清除时机，保证冻结写入的 `error`（含「原状态 X」）在并发下不被清除、解冻时 `parse_orig_status` 读出真实原状态

## 3. 自愈空闲判定加强

- [x] 3.1 修正 `fenixd.py:_is_idle`：增补**评审车道**在飞维度。根因不是 `_active_runs` 递减有误——评审 run 从不计入 `_active_runs`（`core/pm_engine/dispatch/queue.py:556-564` 显式 `MUST NOT 增减 _active_runs`，只记 `_active_reviews`），故 `_active_runs == 0` 与评审 run 是否在飞无关，**MUST NOT 以「核对 `_active_runs` 递减时机」为实现路径**。MUST 复用既有双判据合取（同 `core/pm_engine/engine.py:750-773` 派发守卫口径）：① `PMEngine.is_review_in_flight(spec_name)`（`engine.py:3522`）② `LivenessSupervisor.reviewer_in_flight(spec_name, reviewer_run)`（`core/agent_runner/liveness.py:454`，其**判据 2「进程表 `running_run_ids()`」**才是「停滞 run 仍算在飞」的成立依据，MUST NOT 退化为仅用流文件新鲜度）。MUST NOT 只加 `_active_reviews` 一个维度——其释放时点早于 `dispatch_review`（`queue.py:2129`），锚点落盘后登记即消失，须以 `reviewer_run` 锚点 + `reviewer_in_flight` 接力覆盖全程。`core/pm_engine/engine.py` 的改动即为此提供只读门面（如需按 `reviewer_run` 非空枚举候选，以只读查询暴露，MUST NOT 改 `_active_runs`/`_active_reviews` 语义）
- [x] 3.2 确保「非空闲」不引入永真条件：已收口或进程已死亡的 run MUST 正常移出在册集合、不再占据空闲判定，使自愈在真正空闲时仍能触发。**依据**：`reviewer_in_flight` 判据 4 对「run 已终态但锚点残留」返回 `(False, "stale")`，天然不占位——实现期 MUST 以该判据行为为界，MUST NOT 新增自己的「锚点非空即非空闲」判断（那才是永真条件）
- [x] 3.3 收敛每 tick 开销：`_is_idle()` 经 `fenixd.py:586 time.sleep(1)` → `:597 _maybe_stale_selfheal_tick` → `:1067` **每 1 秒调用一次**，新增评审维度 MUST 以「候选收窄（仅取 `reviewer_run` 非空条目）+ 命中即短路返回 False」实现，MUST NOT 每 tick 全量 `read_all()` 逐条判定；若实测开销可观，加短 TTL 缓存（TTL MUST 显著小于 `idle_confirm_seconds`，避免延迟在飞识别）
- [x] 3.4 同步改写 `specs/stale-code-selfheal/spec.md` 中「空闲判定语义」Requirement（本 SPEC 已随附 MODIFIED 段）：该条原把「空闲」定义为 `_active_runs == 0` + admin 池空，若不改写会与本变更的「空闲感知的陈旧自愈触发」形成两条互斥 MUST。实现期 MUST 同批落地两条 Requirement，MUST NOT 只改其一

## 4. 测试与回归

- [x] 4.1 新增 `tests/test_state_write_atomicity.py`：① 两路径并发对同一 spec 写不同字段，断言两字段改动均保留（当前实现会丢其一）；② 冻结写入 error 后触发并发写入，断言 error 仍可读、`parse_orig_status` 返回原状态
- [x] 4.2 新增 `tests/test_stale_selfheal_idle.py`：①构造「**评审车道**在飞且转录停滞」的 run——`_active_runs == 0`（评审 run 从不递增它）、`reviewer_run` 锚点非空、run 在 `running_run_ids()` 中、流文件停止增长——断言 `_is_idle()` 为 False 且 `_maybe_stale_selfheal_tick` 不写入 `restart_request`；**该用例 MUST 在未修补实现上失败**（修补前 `_active_runs == 0` 即判空闲），否则不构成回归锚点；②断言死亡/收口 run（进程表无、流文件末行终态）经 `reviewer_in_flight` 判 `stale`，不阻碍空闲判定、自愈仍可触发；③断言 `_active_reviews` 已释放但 `reviewer_run` 锚点仍在飞的窗口内仍判非空闲（防只加 `_active_reviews` 一维的退化实现）
- [x] 4.3 运行状态机与调度相关既有测试子集，确认零回归（新增失败 MUST 为 0）
- [x] 4.4 运行全量回归并与 `main` baseline 比对，确认无本次引入的新增失败