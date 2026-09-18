# Design: transient-storm-alert-context

## D1: attempt 元信息记账

core/agent_runner/provider_circuit.py `record_transient_error`：

```python
class TransientAttempt:
    spec: str
    run_id: str
    provider: str
    at: float

# 记账：self._transient_break_events[fingerprint] 现为时间戳列表，
# 扩展为 TransientAttempt 列表（时间用于滑窗剔除、元信息用于聚合）
```

窗口滑出仍按时间戳剔除（行为不变）；元信息随事件保留。

记账点**两处 MUST 同步**（结构必须一致，否则滑窗剔除 `now - t` 对混合元素类型报错）：

- 正常记账路径（追加事件 + 达阈值判定）；与
- 已冻结早退路径（`is_global_transient_break` 为真时「只记账不触发」，见
  provider_circuit.py:404-407）——该分支目前直接 `append(now)`，改造后 MUST 同样
  写入 TransientAttempt。

元信息经调用链传入（缺一不可，否则 D2 清单无从取值）：

- `ProviderCircuit.record_transient_error(error_text, *, spec=None, run_id=None,
  provider=None, now=None)` 新增**可选关键字**参数，缺省 None → 既有调用点与
  既有测试（tests/test_transient_backoff.py `record_transient_error("…", now=…)`）
  零改动；
- 门面转发 `record_transient_break` → `record_transient_error`（runner.py:404
  注册表）透传同名参数；
- `AgentRunner._record_4xx_or_transient` 增参 `spec_name` / `run_id`（provider 已
  有 `provider_name`），由 `_execute_agent_inner` 内的调用点
  （runner.py:2123，`spec_name` 与 `attempt_run_id` 均在该作用域内）传入。

元信息缺失（None，如未改造的调用点）时置空串占位并正常记账，MUST NOT 因缺元信息
阻断熔断记账。

## D2: 触发时聚合注入

达阈值触发全局熔断（provider_circuit.py 熔断触发处）时：

1. 构建窗口内 attempt 聚合列表：`[{"run_id": ..., "spec": ..., "provider": ..., "at": <ISO>}]`（滑窗保活事件）
2. ERROR 日志追加：`failed attempts: [...]`
3. 升级信号上下文（transient_break_storm）的 evidence/description 追加聚合列表

聚合对 fingerprint 归一化免疫：即使指纹只剩 `<model>`，清单仍列出真实 provider/run_id。

**清单有界**：冻结期内事件持续累积，窗口内事件数可能远超阈值，故清单 MUST 有界——
取最近 N=20 条，截断时追加 `truncated=<被略去条数>`，避免 description / evidence 与
admin_alerts.json 无界增长（人工可见性不受损：截断后仍能定位风暴来源 provider/run）。

## D3: 过期自动核销

全局熔断**自然过期**的处理位置是 `is_global_transient_break`
（core/agent_runner/provider_circuit.py:449-466，「`now >= self._transient_break_until`
→ 清零 `_transient_break_events` + WARNING 'Global transient break expired — dispatch
resumed'」分支），而非 `is_global_transient_break` 的「冷却清零处」之外的独立分发器——
本代码库无到期事件分发机制，核销动作 MUST 内联在：

1. **过期时点**：上述分支内，紧邻 WARNING 日志之后（此行即 proposal 所述
   「dispatch resumed」，实证：fenixd 日志 13:32:32Z expired / dispatch resumed）；
   MUST 在此**同步**执行核销（复用 expiry 分支是幂等且可测的路径；若改为异步扫描，
   仍需在此分支写入待核销标记）；
2. 核销入口（alert lifecycle）：定位 signal_type=transient_break_storm 且时间域匹配
   本次熔断的告警——实现口径为 `AdminStore.latest_signal("global-transient",
   "transient_break_storm", <本次冻结时长/60 分钟>)`（core/admin_store.py:410），
   命中即本次熔断产生的那一条；窗口锚点为 `created`（escalation 记录不带
   `last_seen`，见 core/admin_store.py:418-431）；
3. 标记 handled=True + `handled_by="auto-resolve"` + `resolve_note`（核销原因=熔断
   自然过期 + 聚合清单摘要），落审计——**复用既有通道**：向
   `AdminStore.auto_resolve([{"id": …, "spec": "global-transient", "resolve_note": …}])`
   （core/admin_store.py:345-378）传单元素列表即可，MUST NOT 新增告警 kind、
   MUST NOT 复用 `alert_lifecycle.find_resolvable`（其判定输入为 spec 状态表，
   `global-transient` 不在 STATE.md 状态表中 → 该路径永不命中，
   core/alert_lifecycle.py:132-137）；
4. 幂等：`auto_resolve` 对 `handled=True` 条目跳过
   （core/admin_store.py:369）、`latest_signal` 无命中返回 None（零操作）→
   重复过期/无对应告警天然零操作、零写回。
5. 调用边界：`is_global_transient_break` 同时被 dispatch 闸门
   （core/pm_engine/dispatch/queue.py:172）与本组件内部记账调用——核销实现 MUST
   在异常时静默（沿用告警写入的 try/except 风格，如
   provider_circuit.py:512-516），MUST NOT 让告警写失败阻断闸门判定/fail-open 语义。

**落点归属**：核销逻辑实现于 `ProviderCircuit` 内（provider_circuit.py，与
`_alert_transient_break` 同组），`core/alert_lifecycle.py` **无需修改**
（该模块为纯函数判定器、不读写文件，见其模块 docstring）；tasks Deliverables 中
列出的 `core/alert_lifecycle.py` 仅为核销通道的名义归属，实现时以
AdminStore.auto_resolve 为实际写回点。

## D4: 测试策略

tests/test_transient_storm_observability.py：
- 注入聚合：mock 窗口事件 → 断言触发日志与告警上下文含 run_id/provider 清单
- 自动核销：mock 过期 → 断言告警 handled=True + 审计记录；重复过期幂等
- 未达阈值不触发（既有语义回归）