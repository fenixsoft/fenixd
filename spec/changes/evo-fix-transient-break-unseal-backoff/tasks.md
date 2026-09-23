## Deliverables

```yaml
# ── 熔断器：解封次数记忆 + post-unseal hold + 探针态（A/B）──────
- path: core/agent_runner/provider_circuit.py
  kind: modify

# ── 派发闸门：hold 态消费 + 错峰放行（B/C）────────────────────
- path: core/pm_engine/dispatch/queue.py
  kind: modify

# ── 配置：transient_unseal_* 键规范化（D）────────────────────
- path: core/config.py
  kind: modify

# ── 测试 ──────────────────────────────────────────────────
- path: tests/test_transient_unseal_backoff.py
  kind: new
- path: tests/test_transient_backoff.py
  kind: modify
```

## 1. 解封渐进恢复

- [ ] 1.1 core/agent_runner/provider_circuit.py：同指纹解封次数记忆（per-fingerprint 字典，稳定观察窗后衰减复位；计数规则见 design D2——每次解封 +1、探针失败额外 +1、多指纹取最大），到期解封进入 post-unseal hold（基数×解封后次数、封顶），hold/观察窗期满以 threading.Timer 调度唤醒派发（复用 queue.py:1988 _schedule_backoff_retry 先例），hold 期满仅放行最高优先级单条探针
- [ ] 1.2 core/pm_engine/dispatch/queue.py：_process_queue 首道闸按 冻结 > post-unseal hold > 探针观察窗 态序扩展消费（短路顺序即优先级，冻结期重触发则 hold 作废重计）；探针观察窗内无同指纹新失败（复用 _append_transient_event 记账判定）才按 _run_queue 优先级+aging 顺序分批放行其余积压，MUST NOT 同拍全量放出
- [ ] 1.3 core/agent_runner/provider_circuit.py：探针再失败按现行规则重新熔断且解封次数+1，告警链路照常；解封/hold/探针/错峰四类事件各有日志
- [ ] 1.4 core/config.py：新增 agents.transient_unseal_* 键（hold 基数 60s/封顶 600s/探针观察窗 120s/稳定衰减窗 30m，缺省启用）并纳入 get_transient_config 规范化

## 2. 测试

- [ ] 2.1 tests/test_transient_unseal_backoff.py：覆盖解封不立即全量放行、首场解封 hold=基数而非 0、hold 随解封次数渐进且封顶、探针失败额外 +1（下场 hold 相应加长）、探针通过后按优先级分批放行、探针失败重熔断且次数+1、稳定窗后衰减复位、配置键热更新生效、无外部触发时 hold/观察窗到期仍能主动唤醒派发（回归 fix-provider-transient-backoff 之前的惰性停摆缺口）
- [ ] 2.2 tests/test_transient_backoff.py：修订 :780（test_break_expires_and_resets）与 :858/:872（解封立即唤醒）用例到新语义——清零语义保留、立即全量唤醒改为 hold+探针；原地退避与 per-spec 重派延迟既有用例回归不变
