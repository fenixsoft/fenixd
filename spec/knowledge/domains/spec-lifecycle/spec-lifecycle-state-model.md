<!-- knowledge: capability=spec-lifecycle-state-model rev=3 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

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
- 冻结现场字段保全：冻结 entry 的 error 字段随冻结现场一并保全，解冻前不得被任何写路径置空。已知开放缺口：daemon 重启后存在冻结 entry 的 error 被清空的观测（frozen 保持 True、error 变 null），写入方疑似 dashboard admin 侧以无 logger 的 StateMachine 实例直写，尚未定位修复——凡依赖冻结 error 做判读，先核对字段实际在位。
- 人工解冻纪律：`unfreeze_spec` MUST 显式传 `status=<原状态>`——缺省兜底 ready 是陷阱（reviewing 等原状态会被压平）；官方通道经 `parse_orig_status` 从冻结 error 文案解析原状态回传。半死态直修：结构化冻结的 error 被 cancel 等路径清掉后残留 `frozen: True` 时，`is_spec_frozen` 失效、API unfreeze no-op——须以 `StateMachine.unfreeze_spec(spec, status=<原状态>)` 直修；先删除引发冻结的问题文件再解冻（解冻后拾取仅约 1 秒，不留修复窗口）。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
- 2026-11-04 memory-distill-open-gaps-hazards（spec/knowledge/_inbox/done/memory-distill-open-gaps-hazards.md） — 折叠冻结现场字段保全规则与其已知开放缺口（daemon 重启后冻结 error 被清空、写入方疑似 NullLogger StateMachine 直写、未定位修复）
- 2026-11-04 memory-distill-ops-runbook（spec/knowledge/_inbox/done/memory-distill-ops-runbook.md） — 折叠人工解冻纪律：unfreeze 显式传 status（缺省 ready 兜底陷阱）、frozen 残留半死态以 unfreeze_spec(status=原状态) 直修、先删问题文件再解冻
