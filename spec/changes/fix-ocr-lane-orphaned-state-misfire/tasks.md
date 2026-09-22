## Deliverables

```yaml
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: tests/test_impl_ocr_parallel_lane.py
  kind: modify
```

## 1. 车道运行中心跳（run_impl_ocr）

- [ ] 1.1 `core/agent_runner/maintenance_runs.py` 的 `run_impl_ocr` 增加运行中心跳：审查子进程启动后起后台线程（`threading.Thread(daemon=True)` + `threading.Event` 停跳位，循环 `Event.wait`），按模块常量间隔 ≤45 秒（须小于 `ORPHANED_RUN_GRACE_SECONDS`=120s 宽限，留调度抖动余量）经既有 `_write_impl_ocr_run_events` 向车道 run 转录追加 `progress` 事件；事件字段含 `spec`、`agent_type: "impl-ocr"`、`timestamp`（写入器既有）、`review_range: {from, to}` 与 `elapsed_seconds`（自子进程启动起 `time.monotonic` 差值）；函数 docstring 补心跳语义与设计依据（orphaned_state 条件①消费）
- [ ] 1.2 停跳顺序与全路径覆盖：子进程返回（完成/非零退出/车道硬超时）后 MUST 先 `stop_event.set()` + `join(有上限)` 停跳、再写终态事件（`result`/`error` 末行后置不变量）；try/finally 覆盖一切退出路径（含既有降级 unavailable 各分支与意外异常），停跳后不再有任何 `progress` 追加；心跳写失败静默（`_write_impl_ocr_run_events` 既有语义），MUST NOT 影响车道收尾、MUST NOT 抛未捕获异常（既有约束保持）
- [ ] 1.3 `tests/test_impl_ocr_parallel_lane.py` 新增心跳行为用例：a) 模拟长审查（子进程阻塞超过 2 个心跳间隔）期间转录持续追加 `progress` 且 mtime 刷新；b) 子进程收尾后停跳、终态事件是文件末行；c) 异常收尾路径（子进程抛错/硬超时）同样停跳且终态末行

## 2. 探针与分类器回归钉住（零改动验证）

- [ ] 2.1 `tests/test_impl_ocr_parallel_lane.py` 新增无驱动探针相容回归（直接调 `core.admin_monitor.spec_is_undriven`，不改动其实现）：a) spec 处于 testing、车道 run 转录 mtime 新鲜（心跳写入后）→ 返回 False（车道在跑不误报）；b) 转录 mtime 停滞超宽限窗且无其他驱动 → 返回 True（daemon 重启停跳后真孤儿仍上报，自愈链不遮蔽）
- [ ] 2.2 `tests/test_impl_ocr_parallel_lane.py` 新增终态分类回归：a) `core.dashboard.data.runs.classify_run` 末行为 `progress` → 返回 `running`；b) `AdminMonitor._run_terminal_status` 末行为 `progress` → 返回 `running`；二者实现 MUST 保持零改动（缺省兜底即契约），测试注释注明「防未来终态映射表扩张时把心跳误判终态」
- [ ] 2.3 定向测试全绿：`pytest tests/test_impl_ocr_parallel_lane.py`（及既有涉及 `spec_is_undriven` 的存量用例）通过，无回归
