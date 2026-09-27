# 模型网关与配置

模型网关与配置域：LLM provider 注册表与角色模型分配、候选链与 failover、瞬断治理与熔断、计费配置，以及分级配置与设置界面的配置体系。

## 能力页

- [llm-model-assignment](llm-model-assignment.md) — 各 agent 角色的模型分配
- [chain-model-mapping](chain-model-mapping.md) — 链模型映射（元素级模型解析）
- [dashboard-chain-editor](dashboard-chain-editor.md) — 链模型映射编辑器
- [provider-chain-config](provider-chain-config.md) — provider 候选链配置
- [failover-dispatch](failover-dispatch.md) — provider 故障切换派发
- [provider-fault-fuse](provider-fault-fuse.md) — provider 故障熔断
- [provider-transient-backoff](provider-transient-backoff.md) — 瞬时故障原地退避
- [transient-dispatch-gating](transient-dispatch-gating.md) — 瞬断终态重派与全局熔断
- [transient-controls-ui](transient-controls-ui.md) — 瞬断治理配置界面
- [provider-circuit-observability](provider-circuit-observability.md) — 瞬断风暴可观测与告警核销
- [model-chain-health-probe](model-chain-health-probe.md) — 模型链健康探测（拒模型快速 failover）
- [model-billing-config](model-billing-config.md) — 模型计费单价与成本口径
- [provider-billing-config](provider-billing-config.md) — provider 计费配置
- [hierarchical-config](hierarchical-config.md) — 分级配置（用户级+项目级合并）
- [hot-reload-unknown-key-tolerance](hot-reload-unknown-key-tolerance.md) — 配置热更新未知键容错
- [config-tabs](config-tabs.md) — 配置页页签
- [settings-system-tab](settings-system-tab.md) — 设置页系统页签
