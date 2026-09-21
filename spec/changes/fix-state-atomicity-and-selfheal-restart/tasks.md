# Tasks: fix-state-atomicity-and-selfheal-restart

## Deliverables

```yaml
- path: core/state_machine.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_state_write_atomicity.py
  kind: new
- path: tests/test_stale_selfheal_idle.py
  kind: new
```

## 1. STATE.md 写入原子化

- [ ] 1.1 将 `StateMachine.update_spec` 的「读 STATE.md → 内存改目标字段 → 持久化」三段收进单次 `.STATE.md.lock` 的 `flock(LOCK_EX)` 内（对齐 `_bump_counter` 既有范式）；锁内 MUST 调 `_write_all_locked`，MUST NOT 再调 `write_all`（同进程重复 flock 会自阻塞）
- [ ] 1.2 核查并收敛其余 STATE.md 写入路径（`add_spec` / `remove_spec` / `_bump_counter` 及任何直接 `write_all` 调用点）至同一锁内原子路径，确保并发读-改-写不再以陈旧快照整体覆盖
- [ ] 1.3 为原子写入补齐可观测日志（含 spec 名与本次所改字段键），使任何 STATE.md 写入均可在 `fenixd.log` 留痕，消除无日志的静默写入路径

## 2. 冻结 error 的可靠持久化

- [ ] 2.1 排查 2026-09-21 观测到的「`updated=03:43:24` 但 `fenixd.log` 无对应 Updated SPEC 记录」的写入路径，定位其调用者并纳入 1.1/1.2 的锁内原子路径；若确为直接 `write_all`，改为原子入口
- [ ] 2.2 核对 `freeze_for_human` / `freeze_spec` / 解冻 / `consume_review_result` 四条路径对 `error` 的写入与清除时机，保证冻结写入的 `error`（含「原状态 X」）在并发下不被清除、解冻时 `parse_orig_status` 读出真实原状态

## 3. 自愈空闲判定加强

- [ ] 3.1 核对 `pm_engine._active_runs` 的递减时机与在飞 run 登记语义，修正 `fenixd.py:_is_idle`：存在未收口的在飞 run（含转录因 API 重试/停滞暂不增长者）时 MUST 返回 False
- [ ] 3.2 确保「非空闲」不引入永真条件：已收口或进程已死亡的 run MUST 正常移出在册集合、不再占据空闲判定，使自愈在真正空闲时仍能触发

## 4. 测试与回归

- [ ] 4.1 新增 `tests/test_state_write_atomicity.py`：① 两路径并发对同一 spec 写不同字段，断言两字段改动均保留（当前实现会丢其一）；② 冻结写入 error 后触发并发写入，断言 error 仍可读、`parse_orig_status` 返回原状态
- [ ] 4.2 新增 `tests/test_stale_selfheal_idle.py`：构造「登记在册但转录停滞」的在飞 run，断言 `_is_idle()` 为 False 且 `_maybe_stale_selfheal_tick` 不写入 `restart_request`；另断言死亡/收口 run 不阻碍空闲判定
- [ ] 4.3 运行状态机与调度相关既有测试子集，确认零回归（新增失败 MUST 为 0）
- [ ] 4.4 运行全量回归并与 `main` baseline 比对，确认无本次引入的新增失败