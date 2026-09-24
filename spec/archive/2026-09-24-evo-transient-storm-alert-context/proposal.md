# Proposal: transient-storm-alert-context

## 问题

SDK 瞬断风暴（600s 窗口内 5 次失败）触发全局熔断时，升级告警（transient_break_storm）的上下文只有被 `<model>` 占位符归一化的错误指纹——设计使不同模型变体收敛为一指纹，故无法定位具体模型/provider；且告警无自动核销，每次风暴留 1 条未处理升级记录（2026-09-18T13:19:26Z 实证、handled=False）。熔断机制本身按 fix-provider-transient-backoff D4 正常工作，缺口在观测面：归因难 + 人工核销负担。

## 证据

- fenixd.log：13:19:26Z Global transient break TRIGGERED（fingerprint 含 `<model>` 占位、无 run 清单）→ 13:32:32Z expired、dispatch resumed
- core/agent_runner/provider_circuit.py:380-383：模型名统一替换为 <model>（指纹归一化设计）
- .fenix/admin_alerts.json：signal_type=transient_break_storm 的 escalation（13:19:26.407Z、handled=False），evidence 无失败 attempt 清单

## 设计思路

1. **失败 attempt 聚合附加**：provider_circuit 的瞬断记账（record_transient_error）除指纹时间戳外，同时记录每次 attempt 的元信息（spec、run_id、provider、时间戳）；触发全局熔断时把窗口内 attempt 聚合列表（run_id/时间/provider）与 fingerprint 并列注入告警上下文（ERROR 日志与 transient_break_storm 升级信号）。
2. **熔断自然过期自动核销**：全局熔断过期（dispatch resumed）时，自动核销对应 transient_break_storm 告警（handled=True + 核销原因=熔断自然过期），留审计；幂等（无对应告警/已核销零操作）。

## 范围

- 覆盖 provider_circuit 熔断触发/过期的观测面（上下文 + 告警生命周期）
- 不改变熔断阈值、冻结时长、退避行为（整理 fix-provider-transient-backoff 既有语义）