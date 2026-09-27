# ADR-082：门禁证据 per-spec 寻址持久化，缺失 fail-closed

date: 2026-09-13
status: accepted

## Context

verified→done 完成度门禁是无状态重复评估，证据却存放在共享 run-result 文件中，会被任何后续 run 的 merge-back 覆盖——「重复评估 × 证据蒸发」使恢复巡检在证据被覆盖后自动放行，静默推送。框架已有正确形态先例：verifier 结果落 `.fenix/verify-progress/<spec>/`，fix 上下文注入时把共享文件快照为 prev-impl-result.json 并注明「根文件会被后续 run 覆盖」。

## Decision

- 重复评估的门禁读「这个 spec 自己的」持久证据，不读「最新的那个」共享事件：implementer 成功收口点（merge-back 前）把已解析结果原样落盘 `.fenix/verify-progress/<spec>/impl-result.json`，tempfile + 原子 replace，重派后新成功覆盖旧快照；写侧 fail-open（失败仅 WARNING，不阻塞派发），快照缺失由门禁 fail-closed 兜底。
- 门禁证据优先级：per-spec 快照 > 共享文件（stamp=本 spec，存量在飞兼容）> 皆缺失时按 `implementer_run` 分流——legacy/手工 spec（无 implementer_run）放行，框架 run 在场则 fail-closed 拦截（防御误删/磁盘异常）。
- 证据彻底缺失 fail-closed：停在 verified + 结构化 error，不静默放行；error 前缀常量（`task-gap:`）单点定义，写侧（error 字段）与读侧（恢复巡检、门禁自清除）共用，杜绝字面量漂移。
- 恢复机制尊重门禁结论：带 task-gap 标记的 verified spec 不触发 auto-recover，持续出现在 blocker 清单即人工告警通道；周期 re-trigger 保留——快照落地后重评是确定性的（有缺口幂等再拦，人工补勾后放行 + 清 error + 走完 auto-approve），re-trigger 是人工修复的感知心跳而非危害源。

## Consequences

- 静默完整性漏洞关闭：拦截在任何 re-trigger 时序下确定性成立；带未勾验证类任务的 spec 可靠停 verified 等人工，吞吐回退是有意接受的取舍。
- 共享 run-result 文件写侧不动（fast-track/repair 相对路径契约保留），仅读者地位降级为兼容兜底；重派期间读旧快照的误拦方向安全（重评自愈）。
