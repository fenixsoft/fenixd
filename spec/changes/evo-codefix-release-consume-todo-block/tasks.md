## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_codefix_failure_registration_closeout.py
  kind: modify
```

## 1. 解除路径对齐

- [x] 1.1 core/code_fix.py：release_failed_batch（约 :1135-1194）整批删除注册表记录成功后的同一调用序列内 best-effort 核销 todo.md 对应登记块——复用 _rewrite_todo_entry_consumed（:1289-1346）重写式核销，注记写明解除时刻与 fix-failed-release.jsonl 留痕行；仅整批删除（released 计数分支）触发核销，部分解除（收缩 :1177-1180）不核销（剩余条目仍在册仍跳过，留待既有 consume 闭环）；核销 needle 整行精确匹配（行尾锚，防同批子集/他批前缀扩展误命中，对齐 _close_retry_exhausted_alerts :1258 后缀锚先例）；不嵌套 .fix-failed.json.lock 与 .todo.md.lock，OSError 容错同 _append_todo_entry 口径；登记块已损毁成裸标题壳时复用既有 :1336-1337 兜底移除，不波及他批登记块
- [x] 1.2 core/code_fix.py：release_retryable_failed_batches（:1084-1132）预算内自动释放经 _append_release_trace 写留痕（released_by=auto-budget）；不接 todo 核销动作——墓碑机制下记录保留在册、既有 consume 闭环已覆盖（design 决策 3），预算内记录未达登记阈值本无登记块
- [x] 1.3 core/code_fix.py：_append_release_trace（:1214-1242）留痕行增补 todo 块处理结果字段（consumed / not_found），使「解除未核销」可从留痕审计

## 2. 测试

- [x] 2.1 tests/test_codefix_failure_registration_closeout.py：覆盖人工整批解除→登记块同步核销（注记含解除时刻）、部分解除（收缩）→登记块不核销且他批块原样保留、核销 needle 对前缀扩展清单（他批块 ids 为本批 ids 的前缀扩展）不误命中、预算内自动释放→留痕（released_by=auto-budget）且不触 todo 登记块、todo 写失败不阻断解除且留痕记 not_found、登记块已损毁成裸标题壳时兜底移除且他批块原样保留、带外无 logger 调用留痕照写（含 todo 处理结果字段）