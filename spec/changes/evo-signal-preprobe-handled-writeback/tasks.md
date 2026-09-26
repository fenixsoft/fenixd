## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: tests/test_signal_preprobe_handled_writeback.py
  kind: new
```

## 1. 落地校验

- [x] 1.1 core/admin_monitor.py：_detect_family_explosion 在 mark_escalated/唤起 Administrator 之前，对白名单 signal_type（verify_regression_missing、verify_contract_missing、build_artifact_paths_missing）执行只读探测；探测通过则调 AdminStore.mark_signal_handled **并同步 mark_escalated**（摄取过滤只看 escalated，防下一 tick 重捞重复留痕）闭环，并追加 result=resolved 的处置留痕（注明探测通过、免唤起），跳过唤起；探测异常时按原路径继续唤起（fail-open）
- [x] 1.2 core/admin_monitor.py：_invoke_administrator 落最终 DISPOSITION（终态）后，disp.result 非 pending、disp.escalate 为假且 signal_rec 非 None 时回写对应信号 handled=true（AdminStore.mark_signal_handled(signal_rec["id"])；escalate=true 属升级人工不自动回写；人工显式触发 signal_rec=None 跳过），回写失败仅记警告日志、不阻塞处置结果落盘。注意落点不是 maintenance_runs.py——该文件只写 pending 记录与构造 AdminDisposition，终态 DISPOSITION 由 _invoke_administrator 落盘

## 2. 测试

- [x] 2.1 tests/test_signal_preprobe_handled_writeback.py：覆盖探测通过免唤起且留痕 resolved、诉求未满足照常唤起、探测异常 fail-open 照常唤起、处置终态回写 handled=true，另加白名单外信号行为不变一例；探测通过例须断言记录 escalated=true（下一 tick 摄取循环不再重捞），处置终态回写例须覆盖 escalate=true 不回写与 signal_rec=None 跳过两分支