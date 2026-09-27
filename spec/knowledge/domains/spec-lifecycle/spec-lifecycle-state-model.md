<!-- knowledge: capability=spec-lifecycle-state-model rev=1 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

# SPEC 生命周期状态模型

SPEC 生命周期由 `core/state_machine.py` 的有限状态机管理，`STATE.md` 是唯一事实源。

## 现行规则

- 主链状态：`drafted → [reviewing →] ready → implementing → implemented → testing → verified → done → pushed`。
- 打回分支：`testing → bug-found → implementing`，缺陷原地回到实现车道重做。
- 合法转移集合 `VALID_TRANSITIONS` 约束人工路径；`GATE_TRANSITIONS` 是门禁自动路径额外放行的逃生门白名单，人工调用 `transition` 不得绕过 `VALID_TRANSITIONS`。
- 伴随字段与状态并列存储，不单独立状态：
  - `blocked`：守卫拦截、环境阻塞或冻结期间的状态修饰；
  - `frozen` + `frozen_until` + `_frozen_hold`：冻结终止后现场保全，解冻时清除并置 `_recovery_resume` 续做；冻结期间 `frozen` 字段挡住一切派发；
  - `start_after`：定时拾取锚点，未到期不进入调度。
- 终态集合为 `done` 与 `pushed`；`error`、优先级等元数据随 entry 一并存储。
- `STATE.md` 读写以 `fcntl` 文件锁串行化，写入为原子替换：并发读者任一时刻读到的 entry 要么完整旧值要么完整新值。
- `update_spec` 以落盘完成为返回前提，调用方可依赖「返回即已持久化」语义。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
