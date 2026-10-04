## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: tests/test_admin_orphan_disposition_effect_check.py
  kind: new
```

## 1. 孤儿处置收敛的生效核查补记（主）

- [ ] 1.1 core/admin_monitor.py：_recover_orphaned_dispositions 对「终态记录 handled=False 或组内仍有滞留 pending」的处置组不再直接 continue——增加只读生效核查分支：依据 STATE.md 的 frozen 标记与 status 推进、fenixd.log 的 Transition 留痕（真实状态证据，禁止以处置记录文本自证）判断动作是否已实际生效
- [ ] 1.2 core/admin_monitor.py：核查确认生效时，按 _close_signal_preprobed 先例 append 一条注明「补记」与依据的 result=resolved 处置记录，并对关联信号 mark_signal_handled 收口；核查不通过时不补记、维持滞留并走既有孤儿升级路径（保持 evo-fix-global-signal-choice-execution 2.2 的 fail-closed 语义）
- [ ] 1.3 core/admin_store.py：为补记提供 append 形态的处置事件写入支持（不就地改写既有 pending/终态记录），并以「组内已存在补记记录即跳过」保证幂等、不破坏 _merge_admin_runs 的 final 归并语义

## 2. 结构化 choice 通道小步落账（辅）

- [ ] 2.1 core/admin_monitor.py：_worker 内 _apply_choice_execution 单个动作成功返回后立即 append 一条逐动作 DISPOSITION 事件（含 action_taken 与结果），并在动作证据充分时提前 mark_signal_handled(action_taken, result="resolved")；任一动作执行失败不得预写 resolved

## 3. 测试

- [ ] 3.1 tests/test_admin_orphan_disposition_effect_check.py：构造「终态记录 partially-resolved + handled=False + 目标 spec 在 STATE 已解冻推进 + 日志有 Transition 留痕」的现场，断言孤儿扫描补记 resolved（注明补记）并收口关联信号；再构造「spec 仍 frozen」的未生效现场，断言不补记、维持滞留升级
- [ ] 3.2 tests/test_admin_orphan_disposition_effect_check.py：断言同一处置组补记一次后后续扫描轮次幂等跳过；断言 choice 动作成功后逐动作事件即已落账（模拟 run 在 final 落账前死亡）、动作失败场景不出现 resolved 预写