<!-- knowledge: capability=verified-gate-evidence rev=1 sources=spec/archive/2026-09-13-fix-verified-gate-evidence-race -->

# verified 门证据持久化

verified→done 任务完成门禁的证据寻址、fail 方向与恢复机制约束：门禁证据不依赖易失的跨 spec 共享文件，任务缺口可靠停待人工裁决。

## 现行规则

- implementer run 成功时，dispatch 层把该 run 的结果 dict（与 `_read_implementer_result` 解析产物同 schema，含 spec stamp）原子快照到 `.fenix/verify-progress/<spec>/impl-result.json`：快照幂等（重派后新成功原子覆盖旧快照，不残留旧轮字段）；写入失败仅记 WARNING，不阻塞派发主流程；该文件为 `.fenix/` 运行时文件，MUST NOT 作为交付物校验对象。
- `_task_completion_blocker` 评估「未勾数字任务缺口」的证据优先级：① per-spec 快照；② 快照缺失时主树共享结果文件（且 stamp=本 spec）；③ 两者皆缺失时按存量兼容规则。done_ids 证据维持从 per-run jsonl（`parse_run_task_done`）读取；tasks.md 缺失或不含数字编号任务（`N.M` 格式）时门禁直接放行（无 gap 概念）。
- 证据缺失 fail-closed：快照与共享文件（stamp=本 spec）皆缺失，且 `STATE.implementer_run` 非空、tasks.md 存在未勾数字任务时门禁拦截，error 为 `task-gap: run 证据缺失（快照与共享文件均无），需人工确认`；`STATE.implementer_run` 为空（legacy/手工 spec）时放行。
- task-gap 拦截结论以 `task-gap:` 前缀写入 STATE error 字段；前缀常量单点定义，写侧（门禁）与读侧（恢复巡检、门禁自清除）共用；与 vblocker（验证进度不完整）并存时维持既有合并语义；D7 逃生门回 testing 时覆盖 error 属预期，重验证完成后门禁从持久快照重评并按需重建标记。
- 恢复机制尊重门禁结论：BLOCKER CHECK 巡检对卡在 verified 且 error 带 `task-gap:` 前缀的 spec 不触发 auto-recover 状态突变，blocker 条目 reason 改述为「任务缺口待人工裁决」形态；event_bus 周期 re-trigger 保留，作为确定性重评心跳与人工修复感知通道（有缺口再拦；人工补勾后门禁放行、清除 `task-gap:` error，verified→done 与 auto-approve 链路正常执行）。

## 溯源

- 2026-09-13 fix-verified-gate-evidence-race（spec/archive/2026-09-13-fix-verified-gate-evidence-race） — 确立 implementer 结果 per-spec 快照、门禁证据源优先级（快照>共享兜底>fail-closed）、task-gap 结论结构化持久与恢复巡检对门禁结论的尊重
