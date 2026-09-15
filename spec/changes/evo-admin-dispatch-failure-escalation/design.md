# design — admin-dispatch-failure-escalation

## 现状

- _invoke_administrator except 分支（admin_monitor.py:1214-1230）：logger.error + attach_trigger ESCALATION（action_taken=「Administrator 唤起失败: {e}」，signal_type 沿用原信号）——升级记录存在但无专用类型、无结构化归因、无重试。
- prompt_builder.py:196-197 已走 _str_field（def :40），为未提交工作树改动；tests/test_agent_prompt_files.py:110-112 防回退单测已就位（同未提交）。
- 2026-09-14 20:26 实证：4079b0d022a3（kind=escalation、action_taken=「Administrator 唤起失败: replace() argument 2 must be str, not dict」）；13:51:32 孤儿检测升级 critical（055d12d47892）、13:55 人工处置（9b41f365f1e0）。

## D1 专用升级信号

- _invoke_administrator except 分支按异常类型分流：TypeError/AttributeError/NameError/ValueError → signal_type=admin_dispatch_programming_error、severity=critical、evidence={exception_type, message, callsite（traceback 提取 core/ 内最深帧：文件:行 函数名）, original_signal:{signal_type, spec, severity}}；其余异常维持原 signal_type 升级记录（同样附带 D2 的 next_retry_at/retry_count，参与重试——proposal 目标③「派发失败不重试、单点即断」针对的是派发链本身，不限于编程错误，且瞬态失败恰是重试高价值场景）。
- 写入前 unhandled_for(spec, admin_dispatch_programming_error) 去重（同 admin_reset_programming_error 模式，admin_monitor.py:1403-1411）：重试再失败走既有记录 bump（见 D2），不重复落盘。
- ValueError 分类注记：JSONDecodeError/UnicodeDecodeError 属 ValueError 子类，数据类瞬时问题会被归为编程错误——保守可见方向（升级总比静默原类型好），evidence 保留完整异常消息供甄别。
- SIGNAL_SEVERITY / SIGNAL_RECOMMENDATION 登记 admin_dispatch_programming_error（critical；代码缺陷、Administrator 无法修复、须工程侧定位、勿派子 fix 重跑——沿用 add-control-plane-silent-failure-guards 3.3 的文案模式）。

## D2 重试语义

- 两条分流路径（编程错误 / 原类型）的升级记录均附带 next_retry_at（now + escalation_cooldown_minutes）与 retry_count=0。
- 新方法 _retry_due_dispatch_failures() 挂 run_once 巡检（_force_escalate_stalled 之后、_run_alert_lifecycle 之前，不新增线程/定时器）：扫描 kind=escalation ∧ next_retry_at ≤ now ∧ retry_count<1 ∧ 未 handled 的记录 → 重试派发一次原信号（信号重建自 evidence.original_signal）。
- 重试 MUST 直接调 _invoke_administrator（携带 _dispatch_retry_id 标记），MUST NOT 经 _handle_signal——否则 _throttled（latest_signal/unhandled_for，admin_monitor.py:890-896）命中刚写的升级记录把重试吞掉；同时 MUST 尊重 frozen 门（spec frozen → 跳过重试，同 _handle_signal:866-878 的冻结语义）。
- 重试仍失败 → 对既有记录 bump retry_count（上限 1），不追加新记录；agent_runner 不可用时同样 bump 后结束，不重复落盘。
- 重试或后续任何派发成功（_invoke_administrator 正常返回）→ 把该 spec 未 handled 的派发失败升级记录（admin_dispatch_programming_error + 带 next_retry_at 的原类型记录）标记 handled，resolve_note=「后续派发成功」。闭环发生在 dispatch 时刻，不扩 alert_lifecycle._SIGNAL_CONDITIONS——其 spec_terminal_or_unblocked 语义（spec 到终态/离开 blocked）不适用于派发失败，保持保守默认不改写。
- manual 派发（invoke_manual，signal_rec=None）失败只落升级不重试：重试判定以自动巡检来源（signal_rec 非 None）为限。

## D3 版本化

- 提交 prompt_builder.py _str_field + tests/test_agent_prompt_files.py 防回退单测（现有工作树改动纳入本 SPEC 交付）；补派发链用例（evidence dict → 正常构建、不抛 replace）。