## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_codefix_failure_registration_closeout.py
  kind: modify
```

## 1. 解除路径对齐

- [ ] 1.1 core/code_fix.py：release_failed_batch（约 :1135-1194）删除/收缩注册表记录成功后的同一调用序列内 best-effort 核销 todo.md 对应登记块——复用 _rewrite_todo_entry_consumed（:1289-1346）重写式核销，注记写明解除时刻与 fix-failed-release.jsonl 留痕行；不嵌套 .fix-failed.json.lock 与 .todo.md.lock，OSError 容错同 _append_todo_entry 口径；登记块已损毁成裸标题壳时复用既有 :1336-1337 兜底移除，不波及他批登记块
- [ ] 1.2 core/code_fix.py：release_retryable_failed_batches（约 :1097 一带）预算内自动释放接入同一核销动作，并经 _append_release_trace 写留痕（released_by=auto-budget）
- [ ] 1.3 core/code_fix.py：_append_release_trace（:1214-1242）留痕行增补 todo 块处理结果字段（consumed / not_found），使「解除未核销」可从留痕审计

## 2. 测试

- [ ] 2.1 tests/test_codefix_failure_registration_closeout.py：覆盖人工解除→登记块同步核销（注记含解除时刻）、预算内自动释放→留痕（released_by=auto-budget）+核销同权、todo 写失败不阻断解除且留痕记 not_found、登记块已损毁成裸标题壳时兜底移除且他批块原样保留、带外无 logger 调用留痕照写（含 todo 处理结果字段）