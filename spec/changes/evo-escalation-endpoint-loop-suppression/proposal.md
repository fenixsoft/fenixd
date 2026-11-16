# Proposal: escalation-endpoint-loop-suppression

## Why

升级链的终点件（Arbiter 产出的裁决包升级告警）落告警后会被升级咽喉原路再派回 Arbiter 车道：core/pm_engine/family.py:1620 `_send_human_escalation_alert` 中 chain_context 只在链头派发段消费，store.append 成功后的直派段（约 :1788-1832）经 narrative_yielded_to_arbiter（core/adjudication_narrative.py:82-117，不感知链终点）为真即无条件 submit_for_alert（core/pm_engine/arbiter.py:550，入口也无链终点去重）。链终点注入点（core/pm_engine/escalation_chain.py:1668-1677）携 chain_context 调本咽喉，恰好触发该直派段。

后果已量化： Arbiter 每次升级都多派一轮同证据调查，唯一停止机制是 arbiter_rulings 配额（=2）耗尽。本签名（client-ux-and-input-latency::warning_stale_triage）2 轮回派分别消耗 436.4s/≈15.0 万 tokens 与 213.2s/≈10.5 万 tokens 且再产一次裁决包；日志统计 source=escalation-alert 的 arbiter 入队共 9 次、涉及 9 个不同签名（cloud-phone 6 个、fenixd 仓 3 个），系咽喉级系统缺口，占用单飞串行队列并推迟真正新信号的裁决。在途 harden-arbiter-lane-resilience 的非目标已明写此缺口「arbiter todo 自理」——无人承接。

## What Changes

- **升级咽喉守卫（core/pm_engine/family.py）**：直派段对 chain_context 非空的链终点件跳过 submit_for_alert，只保留 narrative（或零补叙）——升级件语义回归「给人类的裁决包」。
- **车道入口兜底（core/pm_engine/arbiter.py submit_for_alert）**：入口对携带链上下文（entry['chain'] 存在）的提交短路，双保险防未来新调用点绕过咽喉。
- **单测**：覆盖「链终点件不产生新的 arbiter 触发」与「链队列满回落件（chain_context=None）不受影响」。

## Capabilities

### escalation-endpoint-routing

见 specs/escalation-endpoint-routing/spec.md。

## Impact

- core/pm_engine/family.py 升级告警路径增加一个分支（链终点件不再直派 arbiter）。
- core/pm_engine/arbiter.py submit_for_alert 入口增加守卫。
- 不改变升级告警本身的生成、台账与人工消费流程；不影响链头防自环逻辑。