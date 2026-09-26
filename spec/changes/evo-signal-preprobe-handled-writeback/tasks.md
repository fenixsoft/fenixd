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

- [ ] 1.1 core/admin_monitor.py：_detect_family_explosion 在 mark_escalated/唤起 Administrator 之前，对白名单 signal_type（verify_regression_missing、verify_contract_missing、build_artifact_paths_missing）执行只读探测；探测通过则调 AdminStore.mark_signal_handled 闭环并追加 result=resolved 的处置留痕（注明探测通过、免唤起），跳过唤起；探测异常时按原路径继续唤起（fail-open）
- [ ] 1.2 core/agent_runner/maintenance_runs.py：处置 run 写入非 pending 终态结果时回写对应信号 handled=true（AdminStore.mark_signal_handled），回写失败仅记警告日志、不阻塞处置结果落盘

## 2. 测试

- [ ] 2.1 tests/test_signal_preprobe_handled_writeback.py：覆盖探测通过免唤起且留痕 resolved、诉求未满足照常唤起、探测异常 fail-open 照常唤起、处置终态回写 handled=true，另加白名单外信号行为不变一例