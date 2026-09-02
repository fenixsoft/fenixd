# tasks — add-done-duration-persist

## Deliverables

```yaml
- path: core/pm_engine/engine.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: tests/test_core.py
  kind: modify
- path: tests/test_dashboard_mode.py
  kind: modify
```

## 1. 序列化白名单与状态机侧

- [x] 1.1 `core/state_machine.py` `StateParser.serialize` 固定字段列表追加 `"total_duration"`（置于 `"depends_on"` 之后），确认含该字段的条目在 `write_all` 往返后字段不丢（design D3）
- [x] 1.2 `tests/test_core.py` 增加序列化往返测试：含 `total_duration: 150` 的条目经 `serialize`/`parse` 往返后字段值保持；不含该字段的条目序列化为 `- total_duration: null`

## 2. done 转换写入耗时

- [ ] 2.1 `core/pm_engine/engine.py` verified→done 转换处（`transition(spec_name, "done")` 之后），用 `get_runs(project_root, spec_name, include_archive=True)` 求和并以 `update_spec(spec_name, {"total_duration": <int>})` 写入（design D1/D2）
- [ ] 2.2 无 run 产物时写入 0（同一路径自然覆盖，测试断言）
- [ ] 2.3 确认求和口径与 `spec_summary` 现有实现一致（`duration_seconds` 求和、含归档），保证 done 时刻写入值等于当时列表页显示值

## 3. dashboard 读取优先级

- [ ] 3.1 `core/dashboard/data.py` `spec_summary`：status ∈ {done, pushed} 且 `total_duration` 字段可 int 解析时直接返回该值；解析失败或字段缺失回退现有 run 求和（design D4）
- [ ] 3.2 非完成状态忽略字段，仍走实时求和（design D5）
- [ ] 3.3 `tests/test_dashboard_mode.py` 增加测试：① done spec 有字段时返回字段值（run 产物缺失也返回）；② done spec 缺字段回退求和；③ pushed spec 同 ①；④ implementing spec 忽略字段走求和；⑤ 字段为脏值（非数字）时回退求和不报错

## 4. 收尾验证

- [ ] 4.1 全量 pytest 通过（环境性 daemon 端口占用失败可豁免，与既有基线一致）
- [ ] 4.2 手动构造/复用 fixture 验证：done spec 在 run 产物被移走后 /api/specs 仍返回 STATE.md 中的耗时值
