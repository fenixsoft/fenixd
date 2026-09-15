# 验证报告：evo-run-failure-classification-circuitbreaker

> ⚠️ 本报告由框架于 2026-09-15T10:00:43Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-15T10:00:43.748233+00:00

## 结论：✅ 通过（verified）

**状态：verified — 16/16 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 16/16 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 16 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.30M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| breaker-core-behavior | 熔断器核心判定：InfraCircuitBreaker 阈值触发（连续≥3 次 infra → broken）、冷却自动恢复（窗口滑动）、成功 run 清零计数（连续≥3 次语义）、半开探测失败立即重新熔断（spec D2/D4；tests/test_review_circuit_breaker.py:81-161） | pass | 0/5 | - |
| breaker-persistence | 熔断状态持久化：触发熔断后 .fenix/admin_infra_breaker.json 落盘、新实例（模拟 daemon 重启）读回恢复 broken、损坏文件 fail-open 不阻塞派发（spec D2 持久化 + tasks 4.3；tests/test_review_circuit_breaker.py:121-147） | pass | 0/3 | - |
| classify-infra-fingerprints | 失败分类 infra 指纹：403/402/429/quota/budget/余额/rate limit/provider circuit open/provider chain exhausted/Exit code 非 0\|1（CLI 进程级崩溃）均判 infra（spec D1 infra 指纹集；tests/test_review_circuit_breaker.py:187-232） | pass | 0/5 | - |
| classify-content-exit-code-1 | 失败分类 content 语义：Exit code: 1 不得一律判 infra（评审器内容失败同样 exit 1）→ content；普通失败文本/结果文件读取失败 → content（spec D1 content 分支；tests/test_review_circuit_breaker.py:234-245） | pass | 0/3 | - |
| classify-artifact-priority | 失败分类 artifact 优先级最高：产物已合法落盘即使 reason 含 infra 指纹也判 artifact（spec D1 artifact 分支 + design 优先级声明；tests/test_review_circuit_breaker.py:247-250） | pass | 0/2 | - |
| handle-infra-no-attempt-increment | infra 失败 STATE 副作用：清 reviewer_run、不递增 _review_attempts（熔断前与冷却期均不计入，防 MAX_REVIEW_ATTEMPTS=3 freeze 与冷却后锚点残留拒派双重死锁）+ 熔断计数递增（spec D2 副作用 + tasks 1.2；tests/test_review_circuit_breaker.py:275-285） | pass | 0/2 | - |
| handle-content-retry-semantics | content 失败维持既有重试语义：递增 _review_attempts（spec D2 content 维持重试；tests/test_review_circuit_breaker.py:301-306） | pass | 0/2 | - |
| handle-artifact-direct-consume | artifact 失败直接消费：产物已落盘合法时不重试，consume_review_result 被调用（spec D1 artifact 承接 run-failure-artifact-first；tests/test_review_circuit_breaker.py:308-312） | pass | 0/2 | - |
| handle-third-infra-triggers-alert | 连续第 3 次 infra 失败触发熔断告警：前两次不触发、第三次 _emit_infra_breaker_event(triggered) 恰好调用一次（spec 验收「1 条 critical 告警」+ D3；tests/test_review_circuit_breaker.py:287-299） | pass | 0/2 | - |
| dispatch-short-circuit-when-broken | 熔断窗口内 dispatch_review 短路：不派发评审 run 直接返回 False（spec D2 短路点 spec_review.py:46；tests/test_review_circuit_breaker.py:320-339） | pass | 0/2 | - |
| dispatch-recovers-after-cooldown | 冷却到期后 dispatch_review 恢复：不再短路、落恢复 SIGNAL 记录（spec D4 冷却到期自动恢复；tests/test_review_circuit_breaker.py:341-379） | pass | 0/2 | - |
| engine-on-reviewing-short-circuits | PMEngine 级短路：熔断窗口内 _on_spec_reviewing 不派发（reviewer_run 保持空），冷却到期自动恢复（spec D2 短路点 engine.py:263；tests/test_review_circuit_breaker.py:400-410） | pass | 0/2 | - |
| engine-emit-alert-traceability | 告警落盘可追溯：熔断触发恰好 1 条 critical ESCALATION（signal_type=run_infra_failure、evidence 含 count=3）、恢复落 SIGNAL 档且 spec=None 为链路级（spec D3 告警落盘/消费路径 + 防静默丢失；tests/test_review_circuit_breaker.py:412-449） | pass | 0/3 | - |
| signal-severity-and-stored-types-audit | ADMIN 信号登记审计：run_infra_failure 已登记 SIGNAL_SEVERITY=critical 且不在 STORED_SIGNAL_TYPES（不经 SIGNAL 摄取唤起，防 verify_uniform_failure 式静默丢失；spec D3 + admin_monitor.py:149-257） | pass | 0/2 | - |
| config-infra-breaker-defaults | 配置缺省与容错：admin.run_infra_breaker.threshold 缺省 3、cooldown_minutes 缺省 30；非法值（非正数/类型错误）回退缺省（spec D5 + config.py:1116-1140） | pass | 0/2 | - |
| full-cycle-e2e | 端到端完整链路（tasks 4.1 验收）：3 种不同 infra 失败 → 熔断触发 → 冷却窗口内 _on_spec_reviewing 不派发 → 恰好 1 条 critical ESCALATION → 冷却到期自动恢复 → 恢复后首次成功清零计数（tests/test_review_circuit_breaker.py:451-491） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 16 个（第 1 轮）。

- 首轮写入 16 个场景

