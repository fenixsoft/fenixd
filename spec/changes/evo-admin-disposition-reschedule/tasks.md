## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: tests/test_admin_disposition_reschedule.py
  kind: new
```

## 1. 底层信号回溯能力

- [ ] 1.1 core/admin_store.py：新增 `unhandled_signal_for(spec: Optional[str], signal_type: str) -> Optional[dict]`——遍历 read_all()，匹配 kind=SIGNAL ∧ 非 handled ∧ signal_type 相等 ∧ spec 严格相等 ∧ escalated 为真；返回最新一条命中记录，未找到返回 None；与 unhandled_for 同结构、紧随 admin_store.py:502 之后（MUST NOT 做 spec=None 宽松匹配：实测信号记录 spec 恒非 None）
- [ ] 1.2 core/admin_store.py：unhandled_for 增加注释说明仅匹配 kind=ESCALATION（不匹配 kind=signal），澄清两函数分工
- [ ] 1.3 tests/test_admin_disposition_reschedule.py：覆盖 unhandled_signal_for——未处理且 escalated 的信号返回记录、escalated=False 的节流沉淀记录不返回、spec 不等不返回、handled=true 返回 None、多 signal_type 互不影响

## 2. 重派闭环

- [ ] 2.1 core/admin_monitor.py：新增 `_has_active_admin_run_for(spec, signal_type) -> bool`——存在 kind=DISPOSITION ∧ 同 signal_type ∧ 同 spec ∧ `(status or result) == "pending"` 的记录即真（**该辅助方法当前不存在，必须新增**，不得写作「复用既有」；判据对齐 _recover_orphaned_dispositions 的 by_run 归并口径，admin_monitor.py:1575-1577）
- [ ] 2.2 core/admin_monitor.py：_recover_orphaned_dispositions 的已知中断分支（1600）前置回溯——`sig_rec = unhandled_signal_for(spec, sig_type)` 命中且 `_has_active_admin_run_for(spec, sig_type)` 为假 → `signal = self._rebuild_dispatch_signal(sig_rec)`（2125）；signal 非 None → 调 `_invoke_administrator(signal, sig_rec)` 重新入队（**不经 _handle_signal**，避免 1376 _throttled 吞掉重派）；signal 为 None → 回落原终结逻辑
- [ ] 2.3 core/admin_monitor.py：重派计数——读同 (spec, signal_type) 的 DISPOSITION 记录 `reschedule_count` 最大值（缺省 0）；旧值 + 1 > MAX_RESCHEDULE（默认 2，模块常量，config `admin.reschedule_max` 覆盖，非法值回落 2）时不再重派，转升级（kind=escalation，severity=critical，description 注明中断/重派次数）
- [ ] 2.4 core/admin_monitor.py：重派留痕——原 pending disposition 追加 status=superseded 记录（同 admin_run_id），actions_taken 注明 `superseded by rescheduled disposition (signal <sig_id> still unhandled)`，并携带 `reschedule_count = 旧值 + 1`；**MUST NOT 写 status=dispatched 的新 disposition**（同 admin_run_id 的非 pending 记录会令 by_run 归并把新 run 判为 final，孤儿检测对该 run 永久失效）
- [ ] 2.5 core/admin_monitor.py：升级分支（超限）与「未找到信号」分支均须为该 run 追加非 pending 终结 disposition（超限用 status=escalated，沿用 1643-1660 既有实现），防同一孤儿每轮巡检重复升级
- [ ] 2.6 core/admin_monitor.py：unhandled_signal_for 未命中（无未处理信号记录）时，维持现「终结为 interrupted」行为不变——确保回归兼容

## 3. 测试

- [ ] 3.1 tests/test_admin_disposition_reschedule.py：信号未处理 + 中断 run 超时 → 断言发生重派（新 run 的 pending disposition 生成，admin_run_id 变更）且原 disposition 追加 status=superseded 记录（非 interrupted）
- [ ] 3.2 同文件：无未处理信号记录（unhandled_signal_for 返回 None）→ 断言仍终结 interrupted 不重派
- [ ] 3.3 同文件：连续重派超限（模拟 3 次中断，reschedule_count 依次 0→1→2）→ 第 3 次产生 escalation（kind=escalation，severity=critical）且不再重派，同时该 run 获非 pending 终结记录
- [ ] 3.4 同文件：已有在飞 admin run（存在同 (spec, signal_type) 的 pending disposition）→ 断言去重跳过，不产生新 run
- [ ] 3.5 同文件：重派后的新 run 再次中断（新 run 的 pending disposition 超时 + interrupted 标记）→ 断言再次进入重派判定（计数递增而非被跳过），验证 by_run 归并未把新 run 误判为 final
- [ ] 3.6 回归：`pytest tests/test_admin.py tests/test_admin_store_corruption.py tests/test_admin_dispatch_escalation.py -q` 通过
