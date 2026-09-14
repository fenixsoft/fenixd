## Deliverables

```yaml
- path: core/state_machine.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_cancel_holdstate_recovery.py
  kind: new
```

## 1. 取消收尾写入持久标记

- [x] 1.1 前置核对：grep 全库 `hold-state` 收尾写点，确认六处清单（dispatch.py implementer/fast-track/repair、verification.py planner-plan/planner-judge/legacy verifier）无遗漏的新 run 类型写点
- [x] 1.2 六处取消 hold-state 分支的既有 update_spec 调用各加同层键 `"_cancelled_hold": True`（不改 status/计数/入队语义，error 文案不变）
- [x] 1.3 单测（tests/test_cancel_holdstate_recovery.py）：夹具 run 取消收尾后 spec entry `_cancelled_hold` 为 true，status/error/`_retry_count`/`_merge_streak` 与现有取消行为逐字段一致

## 2. 重启恢复尊重保持

- [x] 2.1 `recover_interrupted`（core/state_machine.py 约 :751）循环体最前（状态分支判定之前）查 `entry.get("_cancelled_hold")`：命中即 log info「跳过重启恢复：人工取消保持 '<name>'」并 continue——不复位、不重派、不递增重启重验计数（implementing/testing 两分支统一覆盖）
- [x] 2.2 单测：取消保持 spec（implementing + 标记）重启恢复后 status/error/run 字段原样、无 Recovered 改写、无恢复重派、`_verify_redo_count` 不变；testing 态带标记同样跳过；无标记 implementing spec 恢复行为回归不变（复位 ready + error=Recovered + 重派触发）

## 3. 显式复位解锁

- [x] 3.1 `update_spec` 内 updates 显式含 `status` 键时同步写 `"_cancelled_hold": False`；仅 error 等隐式 updates 不清标记
- [x] 3.2 单测：对保持态 spec 显式复位（status=ready）后标记清除、后续恢复/调度恢复正常路径；仅写 error 的更新后标记保持 true

## 4. 监测豁免与回归

- [x] 4.1 `admin_monitor._detect_stuck` 循环内在 status 过滤后追加 `_cancelled_hold` 豁免（不产生 stuck 信号、不升级 Administrator）；核对 `_detect_blocked_stuck`（blocked 才命中，预期天然不命中）与 `_detect_repeated_failures`（hold 不新增失败计数，预期不命中），命中才加豁免并留注释
- [x] 4.2 单测：保持态 spec 超过 stuck 阈值且无 run 进度 → 无 stuck 信号；无标记 spec stuck 检测回归不变
- [x] 4.3 全量回归：既有恢复链路测试（test_pm_recovery、test_run_lifecycle_hardening、test_pm_engine_dispatch_fixes）与新增测试全绿
