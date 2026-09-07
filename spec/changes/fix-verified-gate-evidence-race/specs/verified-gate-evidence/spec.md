# verified-gate-evidence 能力规格

verified→done 门禁的证据寻址、fail 方向与恢复机制约束。

## ADDED Requirements

### Requirement: implementer 结果 per-spec 快照

implementer run 成功时，dispatch 层 SHALL 把该 run 的结果 dict（与 `_read_implementer_result` 解析产物同 schema，含 spec stamp）原子快照到 `.fenix/verify-progress/<spec>/impl-result.json`。快照 SHALL 幂等（重派后新成功覆盖旧快照）；快照写入失败 SHALL 仅记 WARNING 不阻塞派发主流程；快照文件为 `.fenix/` 运行时文件，MUST NOT 作为交付物校验对象。

#### Scenario: 成功即快照
- **WHEN** implementer run 声明 success 且 dispatch 走到成功收口点
- **THEN** `.fenix/verify-progress/<spec>/impl-result.json` 存在，内容含 `spec`（=本 spec）与 `status`（=success），与共享结果文件的解析 schema 一致

#### Scenario: 重派覆盖旧快照
- **WHEN** 同一 spec 经打回重派后 implementer 再次成功
- **THEN** 快照文件内容被新一轮结果原子替换，不残留旧轮字段

#### Scenario: 快照写失败不阻塞
- **WHEN** 快照写入抛出 OSError（如磁盘异常）
- **THEN** dispatch 主流程（预算对账、merge-back、状态推进）照常执行，仅产生 WARNING 日志

### Requirement: 门禁证据源优先级

`_task_completion_blocker` SHALL 按以下优先级取证据评估「未勾数字任务缺口」：① per-spec 快照；② 快照缺失时主树共享结果文件（且 stamp=本 spec）；③ 两者皆缺失时按存量兼容规则（见下）。done_ids 证据维持从 per-run jsonl（`parse_run_task_done`）读取。tasks.md 缺失或不含数字编号任务（`N.M` 格式）时，门禁 SHALL 直接放行（无 gap 概念，现状不变）。

#### Scenario: 共享文件被覆盖后门禁仍确定性拦截（事故回归场景）
- **WHEN** 门禁首次评估拦截（error 落 `task-gap:` 前缀）后，主树共享结果文件被其它 spec 的成功覆盖，恢复巡检 re-trigger `spec_verified`
- **THEN** 门禁从 per-spec 快照重新评估，缺口仍在则再次拦截并维持 verified，不产生任何状态突变

#### Scenario: 人工补勾后自动放行
- **WHEN** task-gap 拦截生效期间，人工把缺口任务在 tasks.md 补勾，恢复巡检再次 re-trigger
- **THEN** 门禁评估无缺口 → 放行、清除 `task-gap:` error、verified→done 及后续 auto-approve 链路正常执行

#### Scenario: 全勾 spec 正常放行
- **WHEN** 快照存在、status=success、tasks.md 全部数字任务勾选或被 done_ids 覆盖
- **THEN** 门禁放行，行为与现状逐字段一致

### Requirement: 证据缺失时 fail-closed

当 per-spec 快照与共享文件（stamp=本 spec）皆缺失，且 `STATE.implementer_run` 非空、tasks.md 存在未勾数字任务时，门禁 SHALL 拦截（不再「无法证伪即放行」），error = `task-gap: run 证据缺失（快照与共享文件均无），需人工确认`。`STATE.implementer_run` 为空（legacy/手工 spec）时 SHALL 放行。

#### Scenario: 快照丢失转为人工裁决
- **WHEN** implementer_run 在场的 spec 进入 verified→done，但快照文件被误删且共享文件 stamp 已被其它 spec 覆盖，tasks.md 存在未勾数字任务
- **THEN** 门禁拦截，error 带 `task-gap:` 前缀并注明证据缺失，spec 维持 verified

#### Scenario: legacy spec 无证据放行
- **WHEN** 无 implementer_run 的存量/手工 spec 通过门禁（快照与共享文件均无本 spec 记录）
- **THEN** 门禁放行，与现状行为一致

### Requirement: task-gap 结论结构化持久

task-gap 拦截结论 SHALL 以 `task-gap:` 前缀写入 STATE error 字段；前缀常量 SHALL 单点定义，写侧（门禁）与读侧（恢复巡检、门禁自清除）共用。vblocker（验证进度不完整）与 task-gap 并存时 SHALL 维持既有合并语义；D7 逃生门回 testing 时覆盖 error 属预期，重验证完成后门禁从持久快照重评并按需重建标记。

#### Scenario: 拦截结论可被下游机械识别
- **WHEN** 门禁因任务缺口拦截
- **THEN** STATE error 字段以 `task-gap:` 开头，dashboard 运维视图可见，恢复巡检无需解析自由文本语义即可识别

### Requirement: 恢复机制尊重门禁结论

BLOCKER CHECK 巡检对卡在 verified 且 error 带 `task-gap:` 前缀的 spec MUST NOT 触发 auto-recover 状态突变，其 blocker 条目 reason SHALL 改述为「任务缺口待人工裁决」形态；event_bus 的周期 re-trigger SHALL 保留（作为确定性重评心跳与人工修复感知通道）。

#### Scenario: 巡检不再自动放行缺口 spec
- **WHEN** spec 卡在 verified 超过巡检阈值且 error 带 `task-gap:` 前缀
- **THEN** BLOCKER CHECK 将其列为 blocker（reason 为待人工裁决形态）但不执行 auto-recover，spec 状态保持 verified

#### Scenario: re-trigger 心跳保留
- **WHEN** task-gap 拦截生效期间到达 event_bus 周期 re-trigger
- **THEN** 门禁确定性重评（有缺口再拦 / 已补勾放行），re-trigger 本身不被抑制
