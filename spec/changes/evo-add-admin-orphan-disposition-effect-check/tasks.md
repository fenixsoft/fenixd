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

- [ ] 1.1 core/admin_monitor.py：_recover_orphaned_dispositions 对「final 组 ∧ 关联底层 SIGNAL 仍未收口（unhandled_signal_for 命中，escalated=true 口径；spec 匹配按 None↔"global" 归一化）」的处置组不再直接 continue——增加只读生效核查分支：依据 STATE.md 的 frozen 标记与 status 推进、fenixd.log 的 Transition 留痕（组 spec=global/None 时用 created 时间窗+解冻族迁移+channel/note 对账；真实状态证据，禁止以处置记录文本自证）判断动作是否已实际生效。健康组（信号已收口）与组内已有 escalate=true 终结记录的组不进入该分支
- [ ] 1.2 core/admin_monitor.py：核查确认生效时，按 _close_signal_preprobed 先例 append 一条注明「补记」与依据的 result=resolved 处置记录，并对关联信号 mark_signal_handled 收口；核查与补记前须以 _spec_has_active_admin_run(spec, exclude_run_id=本组 rid) 排除在飞 run（在飞组的信号归在飞 run 认领，不得抢先收口）；核查不通过时不补记、维持滞留并走既有孤儿升级路径（复用 unhandled_for 已升级去重，保持 evo-fix-global-signal-choice-execution 2.2 的 fail-closed 语义）
- [ ] 1.3 core/admin_store.py：为补记提供 append 形态的处置事件写入支持（补记记录以独立标记字段如 source="orphan-backfill" 落痕，不就地改写既有 pending/终态记录），并以「组内已存在补记记录即跳过」保证幂等、不破坏 _merge_admin_runs 的 final 归并语义

## 2. 结构化 choice 通道小步落账（辅）

- [ ] 2.1 core/admin_monitor.py：_worker 内 _apply_choice_execution 执行期间逐动作 append 一条 DISPOSITION 事件（含 action_taken 与结果；MUST NOT 携带 admin_run_id——防 _merge_admin_runs 提前 final 破坏「在飞 = has_pending 且非 final」护栏）；choice 整体执行 ok 时立即提前 mark_signal_handled(action_taken, result="resolved")；choice 任一步骤失败（整体非 ok）不得提前收口、不得预写 resolved（保 2.2 fail-closed）

## 3. 测试

- [ ] 3.1 tests/test_admin_orphan_disposition_effect_check.py：构造「final 组（partially-resolved 终态 + pending 占位）+ 关联 SIGNAL（spec=null、escalated=true、handled=false）+ 目标 spec 在 STATE 已解冻推进 + 日志有 Transition 留痕」的现场，断言孤儿扫描补记 resolved（注明补记）并收口关联信号；再构造「spec 仍 frozen」的未生效现场，断言不补记、维持滞留升级；构造「健康组（关联信号已 handled）」反例断言不进入收敛分支；构造「组内 escalate=true 终结记录」与「同 spec 在飞 run」现场断言跳过
- [ ] 3.2 tests/test_admin_orphan_disposition_effect_check.py：断言同一处置组补记一次后后续扫描轮次幂等跳过；断言 choice 动作成功后逐动作事件即已落账（模拟 run 在 final 落账前死亡）、逐动作事件不含 admin_run_id（归并后组不提前 final）、多步 choice 部分失败不出现提前收口与 resolved 预写