# design — admin-dispatch-failure-escalation

## 现状

- _invoke_administrator except 分支（admin_monitor.py:1049-1065）：logger.error + attach_trigger ESCALATION（action_taken=「Administrator 唤起失败: {e}」，signal_type 沿用原信号）——升级记录存在但无专用类型、无结构化归因、无重试。
- prompt_builder.py:196-197 已走 _str_field（def :40），为未提交工作树改动；tests/test_agent_prompt_files.py:110-112 防回退单测已就位（同未提交）。
- 2026-09-14 20:26 实证：4079b0d022a3（kind=escalation、action_taken=「Administrator 唤起失败: replace() argument 2 must be str, not dict」）；13:51:32 孤儿检测升级 critical（055d12d47892）、13:55 人工处置（9b41f365f1e0）。

## D1 专用升级信号

- _invoke_administrator except 分支按异常类型分流：TypeError/AttributeError/NameError/ValueError → signal_type=admin_dispatch_programming_error、severity=critical、evidence={exception_type, message, callsite（traceback 提取 core/ 内最深帧：文件:行 函数名）, original_signal:{signal_type, spec, severity}}；其余异常维持原行为（原 signal_type 升级记录）。
- SIGNAL_SEVERITY / SIGNAL_RECOMMENDATION 登记 admin_dispatch_programming_error（critical；代码缺陷、Administrator 无法修复、须工程侧定位、勿派子 fix 重跑——沿用 add-control-plane-silent-failure-guards 3.3 的文案模式）。

## D2 重试语义

- 升级记录附带 next_retry_at（now + escalation_cooldown_minutes）；孤儿检测/下一巡检发现到期且原信号未处置 → 重试派发一次；仍失败 → 更新升级记录（retry_count+1，上限 1 次自动重试），保持升级。

## D3 版本化

- 提交 prompt_builder.py _str_field + tests/test_agent_prompt_files.py 防回退单测（现有工作树改动纳入本 SPEC 交付）；补派发链用例（evidence dict → 正常构建、不抛 replace）。