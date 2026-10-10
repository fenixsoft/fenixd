# daemon 错误跨日同刻复发检测
<!-- knowledge: capability=crossday-recurrence-detection rev=1 sources=spec/archive/2026-10-07-evo-add-codefix-conn-error-cooldown,spec/archive/2026-10-11-evo-fix-crossday-recurrence-fingerprint-normalization -->

AdminMonitor 对 daemon_errors 指纹记账的跨日聚合维度：同签名失败终态时刻跨日差 ≈24h 即升级 escalation 告警，让「上游瞬态窗口连续多夜同刻击杀在跑批」这类慢性复发在告警层可见（单夜一次的死亡在第一维度 10 分钟窗口径下不可见）。

## 规则

- 触发口径：同签名（错误指纹）失败终态时刻跨日差 ≈24h（容差 ±5 分钟，模块常量）即升级 escalation 告警；跨日升级绕过 30 分钟已知指纹重启冷却（该冷却只约束第一维度，见 [daemon-error-escalation](daemon-error-escalation.md)）。
- 签名一致性：指纹归一化把「数字.数字+单位字母」形态（延迟数值如 23.4s/5.3s）整体归一为占位符，仅延迟数值不同的同形死亡 ERROR 行产出相同指纹、进入连发判定；非延迟数值部分不同（不同根因）的行指纹不同，不误聚。整数+单位形态（如 4s）不在归一范围，同形不同值的整数延迟行指纹依旧不等。
- 记忆持久化：「签名→上次失败时刻」映射持久化到 `.fenix/` 下状态文件（原子写+锁，仿 fix-progress.json 形态），daemon 重启后加载续用；文件缺失或不可解析时降级为日志回退路径，观测不中断、不抛错影响主扫描。
- 回退检索：无持久化记忆可用时，以本轮扫描得到的同签名最新失败时刻为锚，构造「锚−24h±容差」窄时间窗，先按日志轮转文件与行前缀缩小范围再检索同签名死亡 ERROR 行，覆盖能力 ≥24h、不受 256KB 日志尾读窗限制；仅重启后首轮扫描触发一次，检索成本与命中留 debug 痕。
- 只读边界：本能力仅产出 escalation 告警与留痕，不触发重派、熔断、冷却、salvage 等任何自动干预；daemon_errors 第一维度（10 分钟窗计数）判定规则不动；指纹归一化放宽只改变计数分组输入，同形行聚合计数只增不减、不减少既有告警（见 [ADR-265](../../adr/ADR-265-crossday-recurrence-observability-readonly-escalation-only.md)）。

## 关键行为

- 跨日记忆状态文件是观测私有记忆，不是告警台账：告警 store 无结构化指纹字段的现状不变，跨日对账以状态文件与日志为源。

## 溯源

- 2026-10-07 evo-add-codefix-conn-error-cooldown（spec/archive/2026-10-07-evo-add-codefix-conn-error-cooldown） — daemon_errors 指纹记账新增跨日同刻复发维度：24h±5 分钟连发即升级 escalation，不被 30 分钟已知指纹冷却压制
- 2026-10-11 evo-fix-crossday-recurrence-fingerprint-normalization（spec/archive/2026-10-11-evo-fix-crossday-recurrence-fingerprint-normalization） — 指纹归一化补「数字.数字+单位字母」形态使同形夜间死亡行签名一致；跨日记忆持久化到状态文件跨重启存活；回退对账改定向检索覆盖 ≥24h；固化只读边界
