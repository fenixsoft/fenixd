## Deliverables

```yaml
- path: core/agent_runner/provider_circuit.py
  kind: modify
- path: core/alert_lifecycle.py
  kind: reference
  # 核销通道的名义归属（纯函数判定器，find_resolvable 对 global-transient
  # 永不命中）。核销入口实现于 ProviderCircuit 内（design D3「落点归属」），
  # 本文件零改动且已存在 → 声明已按本注释指示由 modify 改为 reference
  # （软校验、不参与缺件判定）——"可选交付物"在本仓库语义中只能表达为
  # reference（core/deliverables.py:158-161 的 kind 闭集：new/modify/delete
  # 一律硬校验）。
- path: tests/test_transient_storm_observability.py
  kind: new
```

## 1. 失败 attempt 元信息记账

- [x] 1.1 core/agent_runner/provider_circuit.py：瞬断记账（record_transient_error）在指纹时间戳列表基础上，同时记录每次 attempt 的 spec、run_id、provider、时间戳（窗口剔除仍按时间，行为不变）。两处记账点 MUST 经同一内部助手写入（如 _append_transient_event(fingerprint, now, spec, run_id, provider)），任一处的元素结构偏离都会让滑窗剔除与 D2 聚合对混合元素取值失败（见 design D1）
- [x] 1.2 同一改造同步覆盖**已冻结早退分支**（provider_circuit.py:404-407「已在熔断中：只记账不触发」）——该分支直接 append 时间戳，MUST 同样经该助手写入 TransientAttempt（含同一份元信息），否则混合元素让滑窗剔除 `now - t` 报错
- [x] 1.3 元信息传参链打通（缺一则 D2 清单为空）：record_transient_error 增**可选关键字** spec/run_id/provider 且 `now` MUST 保持第二位置参数（既有调用形态 `("…", now=…)` 与 `("x", 1)`，见 tests/test_transient_backoff.py:761-826、tests/test_facade_delegation_contract.py:747；缺省 None，既有调用点与既有测试零改动）→ 门面转发 record_transient_break（runner.py:403 注册表）透传 → _record_4xx_or_transient 增参 spec_name/run_id（provider_name 已有）→ runner.py:2123 调用点传入（spec_name / attempt_run_id，均在该作用域内，attempt_run_id 见 runner.py:1819）。元信息缺省为 None 时置空串占位并正常记账，MUST NOT 阻断熔断记账

## 2. 触发时聚合注入

- [x] 2.1 达阈值触发全局熔断时，构建窗口内 attempt 聚合列表（run_id/spec/provider/ISO 时间）
- [x] 2.2 ERROR 日志在 fingerprint 后追加 failed attempts 聚合清单；升级信号（transient_break_storm）上下文携带聚合清单（对指纹归一化免疫）
- [x] 2.3 清单有界（N=20，超出追加 truncated=<n>）：冻结期内事件仍持续累积，避免 description/evidence 与 admin_alerts.json 无界增长

## 3. 熔断自然过期自动核销

- [x] 3.1 全局熔断自然过期自动核销：核销动作内联在 provider_circuit.py:449-466 的过期分支（`now >= _transient_break_until` → 清零 + WARNING 'dispatch resumed'）内、紧邻 WARNING 之后；实现于 ProviderCircuit 内（与 _alert_transient_break 同组），core/alert_lifecycle.py 无需修改（纯函数判定器；Deliverables 中的该文件仅为核销通道的名义归属）
- [x] 3.2 核销写回通道：`AdminStore.latest_signal("global-transient", "transient_break_storm", <锚点窗口分钟数>)` 定位**当前未处理**告警 → `AdminStore.auto_resolve([{"id", "spec", "resolve_note"}])` 标记 handled=True + handled_by="auto-resolve" + 核销原因「熔断自然过期」+ 聚合清单摘要留审计。锚点与窗口口径 MUST 按 design D3（锚点 = created；窗口下限 ≥ 冻结时长 + 时钟域偏差裕量，缺省不小于 60 分钟——冻结时长按 record_transient_error 记账处同一 `_get_config("agents.transient_break_cooldown_seconds", …)` 取用，MUST NOT 照抄既有 15 分钟节流口径）。候选 MUST 先判 `handled is not True` 再核销：latest_signal 不做 handled 过滤，窗口内更新的已处理条目会抢先命中，auto_resolve 对其恒跳过 → 核销永不生效；候选已处理或返回 None → 零操作返回。不引入新告警 kind；MUST NOT 复用 alert_lifecycle.find_resolvable（其输入为 spec 状态表，global-transient 不在表中 → 永不命中）
- [x] 3.3 核销幂等 + 不影响闸门：无对应告警（latest_signal 返回 None）或已核销（auto_resolve 跳过 handled）→ 零操作、零写回；核销异常 MUST 静默（try/except，沿用告警写入风格），MUST NOT 阻断 is_global_transient_break 的闸门/fail-open 语义（该方法是 dispatch 闸门查询路径，core/pm_engine/dispatch/queue.py:172）

## 4. 测试

- [x] 4.1 tests/test_transient_storm_observability.py：覆盖触发时聚合注入（含 run_id/provider 清单；夹具 MUST 带临时 project_root——既有 _FakePM 的 project_root=None 会让告警写入即抛异常被吞，断言空转）、过期自动核销（handled + handled_by + 审计）、重复过期幂等、无对应告警零写回（mtime 不变）、候选已 handled 时零操作
- [x] 4.2 回归：既有的瞬断熔断语义（阈值/冻结 600s/退避）测试保持全绿；既有 record_transient_error 单参调用点（tests/test_transient_backoff.py TestGlobalTransientBreak）保持通过
- [x] 4.3 回归：延迟过期解除（冻结到期后无人查询熔断态，例如 queue.py:167-175 的两条前置早退分支 shutting_down / 已抑制条目先返回，使闸门查询被跳过）→ 不产生核销动作（本方案不做轮询/异步扫描，MUST NOT 为该场景引入后台线程；配注释说明该路径漏核销由 admin_alerts.json 的 MAX_RECORDS=150 环形裁剪（core/admin_store.py:34,193-194）与人工/Dashboard 处置承接——本仓库不存在按时间的告警清理机制）