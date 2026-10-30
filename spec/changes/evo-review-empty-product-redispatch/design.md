# design

- 止损落点：core/admin_monitor.py _run_code_review_checkpoint（:1710）持有 run 完成与硬门结果上下文，重派判定放此处；限次常量仿 RATELIMIT_REDISPATCH_MAX（=1，core/agent_runner/provider_circuit.py:76）放同模块；重派复用既有 run_code_review 调用（:1864）。
- 变体透出：core/agent_runner/result_gate.py _check_repo_code_review_artifact（:1182-:1200）已区分「产物缺失/读取失败」与「零有效行」两变体，返回结构补 fail_face 摘要（run id、manifest 计数、变体），admin_monitor 组装进完成行与升级告警。
- 升级信号：复用 admin 信号通道，kind 建议 repo_code_review_empty_product；升级后不再自动重派（避免与 evo-add-review-night-defer-snapshot-writeoff 的顺延/抢救面叠加震荡）。
- 提示词：agents/code-review.md 追加自救指引段（映射关系在 core/agent_runner/prompt_builder.py:61），不改 prompt_builder 结构。
- 测试：tests/test_code_review.py 已有门聚合口径用例（:1220-1303），新增重派链路用例（stub run 函数，不真实派发）与提示词断言；升级信号断言携带失败面字段。