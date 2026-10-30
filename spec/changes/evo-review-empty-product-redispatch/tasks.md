## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: agents/code-review.md
  kind: modify
- path: tests/test_code_review.py
  kind: modify
```

## 1. 零产物止损

- [x] 1.1 core/admin_monitor.py：_run_code_review_checkpoint（:1720）在产物硬门拦截（零有效行/产物缺失）后自动重派审查 run 至多 1 次（限次常量仿 provider_circuit.py:76 的 RATELIMIT_REDISPATCH_MAX 先例，限次口径为 monitor 生命周期合计、与 429 重派通道同款），重派仍零有效行则经既有 admin 升级记录通道（admin-dispatch-failure-escalation D1/D2 先例）发升级信号并停止重派；与 429 重派通道互不叠加调度同一 run 链
- [x] 1.2 core/agent_runner/result_gate.py：_check_repo_code_review_artifact（:1141-:1232）拦截时透出失败面摘要（run id、manifest 计数、零有效行/产物缺失变体），供完成行与升级告警消费；调用方 core/agent_runner/maintenance_runs.py gate_err 分支（:2131）同步消费新结构

## 2. 提示词自救指引

- [x] 2.1 agents/code-review.md：预注工具自救指引段（6dc7 并入的完整纪律）——① ToolSearch 仅索引延迟加载工具，对 Bash/Read/Write/Grep 等基础工具返回 No matches 属按设计，直接调用即可；② 工具存在性以 select: 精确名探测；③ 工具面确认缺失时按 TOOLFACE-MISSING fail-fast；禁止凭「检索不到」推断工具缺失并放弃审查

## 3. 测试

- [x] 3.1 tests/test_code_review.py：钉住「零有效行拦截→自动重派恰 1 次→重派仍失败→admin 升级信号且不再重派」链路（stub run 函数，不真实派发），并钉住零产物与 429 两通道限次合计语义、互不叠加调度
- [x] 3.2 tests/test_code_review.py：断言审查提示词含自救指引关键句（按 tests/test_prompt_lane_efficiency_sections.py 先例做契约测试，钉住纪律三要素：基础工具直调 / select: 精确名探测 / TOOLFACE-MISSING fail-fast）、升级告警携带失败面摘要字段
- [x] 3.3 tests/test_code_review.py：钉住「error 收场终局结论行抢救不触发全仓快照核销与 code-fix 检查点」红线、工具预检与 run_metrics 工具面字段

## 4. spawn 后写工具预检（6dc7 并入增量①）

- [x] 4.1 core/agent_runner/runner.py：spawn 后写工具预检——agent_runner 全仓现无 allowedTools 预检（grep 零命中，2026-10-30 人工核查），spawn 装配（claude CLI 子进程装配点）后做一次工具面预检并留痕，预检结果进失败面摘要与 run_metrics 收尾

## 5. 终局消息结论行抢救（6dc7 并入增量②）

- [x] 5.1 core/agent_runner/maintenance_runs.py：error 收场段（:2330-:2356）现只读 shard_paths/主产物文件，终局消息结论行丢失——补终局消息结论行抢救，红线与既有抢救一致：MUST NOT 触发全仓快照核销与 code-fix 检查点

## 6. run_metrics 工具面留痕（6dc7 并入增量③）

- [x] 6.1 core/agent_runner/runner.py：run_metrics 收尾（_log_run_metrics，:1400）补工具面字段留痕（预检结果、TOOLFACE-MISSING 分类等），供事后取证

## 验证修复（原地打回第 1 轮）

- [x] 先复核失败有效性：逐条核对 `spec/changes/evo-review-empty-product-redispatch/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码（复核结论=5 项产品 Bug 全部属实：result_gate 缺 variant_label 且缺失/零行变体同文、admin_monitor 零产物通道升级不带链头 run id、_read_terminal_message 仅读 result 事件（429 error 收场无文本可抢救）、_log_run_metrics 无登记时整体省略工具面键；场景断言与 spec/design 条款相符，非场景缺陷）
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码（修复落点：result_gate 三变体中文标注 variant_label+缺失文案独立成段「全部缺失（未落盘）」；admin_monitor._escalate_code_review_empty_product 增 original_run_id 形参、零产物重派 worker 升级透出链头（redispatch_of）；maintenance_runs._read_terminal_message assistant 末轮回退+_persist_terminal_message_trace 原文落 .fenix/code-review/terminal-salvage-<run_id>.txt；runner._log_run_metrics 工具面四键恒落+登记键归一 getattr 回退防最小替身击穿指标落盘）
- [x] 修复后重跑验证确认通过（tests/test_code_review.py 146 项全绿；触面回归 test_run_metrics_persistence/test_admin_dispatch_escalation/test_admin_dispatch_dedup/test_self_review_terminal_crosscheck/test_run_stall_accounting 合计 218 项通过；6 失败场景映射 12 项测试逐条重跑 PASSED，证据 .fenix/verify-evidence/evo-review-empty-product-redispatch/verifyfix-rerun-scenarios.txt）
