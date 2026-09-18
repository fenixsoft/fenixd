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

- [ ] 1.1 core/admin_store.py：新增 `unhandled_signal_for(spec: Optional[str], signal_type: str) -> Optional[dict]`——遍历 read_all()，匹配 kind=signal 且 handled=false；spec=None 宽松匹配（disposition spec 为项目名时不因字段差异漏匹配）；找到返回记录、未找到返回 None；与现有 unhandled_for 同结构同文件位点
- [ ] 1.2 tests/test_admin_disposition_reschedule.py：覆盖 unhandled_signal_for——信号未处理返回记录、已处理返回 None、spec=None 与具体值均能匹配、多 signal_type 互不影响

## 2. 重派闭环

- [ ] 2.1 core/admin_monitor.py：_recover_orphaned_dispositions 的已知中断分支（1474 行）前置回溯——找到 handled=false 的底层信号且该信号无在飞/待派发 run（复用既有去重判定）时，调用 _invoke_administrator 重新入队（新 admin_run_id，actions_taken 注明 rescheduled from <old_id>）；原 pending disposition status=superseded，actions_taken 注明 superseded by rescheduled disposition <new_id>
- [ ] 2.2 core/admin_monitor.py：重派计数——沿 disposition 链累计 reschedule_count（admin_store 新增字段），达到 MAX_RESCHEDULE（默认 2，模块常量，可由 config `admin.reschedule_max` 覆盖）后转升级分支（kind=escalation，severity=critical，description 注明中断/重派次数）
- [ ] 2.3 core/admin_monitor.py：信号已处理（handled=true）或无信号记录时，维持现「终结为 interrupted」行为不变——确保回归兼容
- [ ] 2.4 core/admin_store.py：unhandled_for 增加注释说明仅匹配 kind=ESCALATION（不匹配 kind=signal），澄清两函数分工

## 3. 测试

- [ ] 3.1 tests/test_admin_disposition_reschedule.py：信号未处理 + 中断 run 超时 → 断言生成新 dispatched disposition（status=dispatched，admin_run_id 变更）且原 disposition status=superseded
- [ ] 3.2 同文件：信号已处理（handled=true）→ 断言仍终结 interrupted 不重派
- [ ] 3.3 同文件：连续重派超限（模拟 3 次中断）→ 第 3 次产生 escalation（kind=escalation，severity=critical）且不再派
- [ ] 3.4 同文件：已有在飞 admin run → 断言去重跳过，不产生新 disposition
- [ ] 3.5 回归：`pytest tests/test_admin.py tests/test_admin_store_corruption.py tests/test_admin_dispatch_escalation.py -q` 通过
