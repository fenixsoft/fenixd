# 模型网关与配置
> 最后更新：2026-09-30 10:13 UTC+8

模型网关与配置域：LLM provider 注册表与角色模型分配、候选链与 failover、瞬断治理与熔断、计费配置，以及分级配置与设置界面的配置体系。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [llm-model-assignment](llm-model-assignment.md) | 各 agent 角色的模型分配 | 2026-09-29 11:27 |
| [chain-model-mapping](chain-model-mapping.md) | 链模型映射（元素级模型解析） | 2026-09-29 11:27 |
| [dashboard-chain-editor](dashboard-chain-editor.md) | 链模型映射编辑器 | 2026-09-29 11:27 |
| [provider-chain-config](provider-chain-config.md) | provider 候选链配置 | 2026-09-29 11:27 |
| [failover-dispatch](failover-dispatch.md) | provider 故障切换派发（链推进/限流冷却/被 429 打死 run 自动重派） | 2026-09-29 11:27 |
| [provider-fault-fuse](provider-fault-fuse.md) | provider 故障熔断 | 2026-09-29 11:27 |
| [provider-transient-backoff](provider-transient-backoff.md) | 瞬时故障原地退避 | 2026-09-29 11:27 |
| [transient-dispatch-gating](transient-dispatch-gating.md) | 瞬断终态重派与全局熔断 | 2026-09-29 11:27 |
| [transient-unseal-recovery](transient-unseal-recovery.md) | 熔断解封渐进恢复（hold/探针/错峰） | 2026-09-29 11:27 |
| [transient-controls-ui](transient-controls-ui.md) | 瞬断治理配置界面 | 2026-09-29 11:27 |
| [provider-circuit-observability](provider-circuit-observability.md) | 瞬断风暴可观测与告警核销 | 2026-09-29 11:27 |
| [model-chain-health-probe](model-chain-health-probe.md) | 模型链健康探测（拒模型快速 failover） | 2026-09-29 11:27 |
| [model-billing-config](model-billing-config.md) | 模型计费单价与成本口径 | 2026-09-29 11:27 |
| [provider-billing-config](provider-billing-config.md) | provider 计费配置 | 2026-09-29 11:27 |
| [hierarchical-config](hierarchical-config.md) | 分级配置（用户级+项目级合并） | 2026-09-29 11:27 |
| [hot-reload-unknown-key-tolerance](hot-reload-unknown-key-tolerance.md) | 配置热更新未知键容错 | 2026-09-29 11:27 |
| [config-tabs](config-tabs.md) | 配置页页签 | 2026-09-29 11:27 |
| [settings-system-tab](settings-system-tab.md) | 设置页系统页签 | 2026-09-29 11:27 |
