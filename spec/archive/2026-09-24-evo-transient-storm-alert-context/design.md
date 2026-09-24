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
  写入 TransientAttempt，并取同一份元信息。

两处记账点 MUST 经**同一内部助手**写入（如
`_append_transient_event(fingerprint, now, spec, run_id, provider)`）：任一处保留
裸时间戳，都会让滑窗剔除 `now - t`（provider_circuit.py:420）与 D2 聚合对混合元素
类型报错/取值失败。早退分支的上游调用点与正常分支同源（`record_transient_break`，
runner.py:2422），MUST 一并透传。

元信息经调用链传入（缺一不可，否则 D2 清单无从取值）：

- `ProviderCircuit.record_transient_error(error_text, now=None, *, spec=None,
  run_id=None, provider=None)`：新增三个**可选关键字**参数，`now` MUST 保持
  第二位置参数（既有调用点以 `("…", now=…)` 与 `("x", 1)` 两种形态调用，见
  tests/test_transient_backoff.py:761-826、tests/test_facade_delegation_contract.py:747），
  缺省 None → 既有调用点与既有测试零改动；
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
2. 核销入口（alert lifecycle）：定位 signal_type=transient_break_storm 的**当前未处理**
   告警——实现口径为 `AdminStore.latest_signal("global-transient",
   "transient_break_storm", <锚点窗口分钟数>)`（core/admin_store.py:410，命中即
   `store.auto_resolve([{"id": <该条 id>, ...}])`；auto_resolve 自己重读当前记录集，
   本步只借它取锚点，见下）；
   **锚点口径**（MUST 按此实现，勿被既有调用点的 15 分钟节流口径复制误导）：窗口锚点
   取 `created`（escalation 记录不带 `last_seen`，见 core/admin_store.py:443-455），
   窗口下限时长 MUST ≥ 「冻结时长 + 两次时钟域间的偏差裕量」——冻结期
   `TRANSIENT_BREAK_COOLDOWN_SECONDS` 以 `_pm._now()`（**time.monotonic**，见
   core/agent_runner/runner.py:683-685）计，而告警 `created` 由 `_utcnow_iso()`
   （**实测墙钟**，core/admin_store.py:46）写入，二者非同源，用严格等长窗口会因偏差
   漏配（既有 15 分钟节流锚点仅用于「近 15 分钟内是否已发同类告警」的查重，语义不同，
   MUST NOT 照抄）。冻结时长的实际口径：`_transient_break_until` 由
   `record_transient_error` 记账处的 `cooldown = _get_config(
   "agents.transient_break_cooldown_seconds", TRANSIENT_BREAK_COOLDOWN_SECONDS)`
   决定（provider_circuit.py:431-436；`.fenix/config.yaml:123` 实配 600s）——
   锚点窗口取该实配值换算分钟数再加偏差裕量，缺省不小于 60 分钟；
3. 标记 handled=True + `handled_by="auto-resolve"` + `resolve_note`（核销原因=熔断
   自然过期 + 聚合清单摘要），落审计——**复用既有通道**：向
   `AdminStore.auto_resolve([{"id": …, "spec": "global-transient", "resolve_note": …}])`
   （core/admin_store.py:345-378）传单元素列表即可，MUST NOT 新增告警 kind、
   MUST NOT 复用 `alert_lifecycle.find_resolvable`（其判定输入为 spec 状态表，
   `global-transient` 不在 STATE.md 状态表中 → 该路径永不命中，
   core/alert_lifecycle.py:132-137）；
   - `latest_signal` 返回的候选 MUST 满足 `handled is not True` 再执行核销：该 API 不做
     handled 过滤（core/admin_store.py:432-436 无 handled 判定），窗口内若存在更新的
     已处理条目（如人工/Dashboard 标记、或上一轮熔断已自动核销的条目）会抢在真实未处理
     告警之前被命中，而 auto_resolve 对已处理条目恒跳过（core/admin_store.py:369）→
     每次过期都零写回、核销永不生效。候选已 handled / `latest_signal` 返回 None →
     零操作返回（不抛异常）；
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
- **元信息降级**：既有 `ProviderCircuit` 单测夹具的 `project_root=None`
  （tests/test_transient_backoff.py:739-756 的 `_FakePM`），告警写入本身即抛异常被
  provider_circuit.py:512-516 的 try/except 吞掉——故新增测试 MUST NOT 依赖该夹具
  断言告警落地：聚合清单断言放在「不经 ProviderCircuit 接线」的纯函数单测
  （传入事件列表 → 断言清单内容/截断），告警与核销断言用带临时 project_root 的夹具
- **候选已处理降级**：窗口内存在更新的 handled=True 条目时，核销 MUST 跳过该候选
  并返回零操作（不触发 auto_resolve 写回、mtime 不变）