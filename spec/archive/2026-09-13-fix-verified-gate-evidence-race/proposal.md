# verified→done 门禁证据持久化治理（fix-verified-gate-evidence-race）

## Why

2026-09-07 `fix-mobile-breakpoint-hook-tables` 带 4 条未勾任务（4.2-4.4 验证类 + 重跑确认）被自动推送。根因：verified→done 任务完成门禁（`_task_completion_blocker`，源自已归档 add-task-progress-sync）两次正确拦截后，恢复巡检每 30 分钟 re-trigger 重评门禁，而门禁证据依赖易失的跨 spec 共享文件 `.fenix/.fenix-run-result.json`——期间另一 spec（add-lost-semantics-regression-tests）实现成功覆盖了该文件，第三次重评时门禁读不到自己的 run 记录，走「无法证伪即放行」分支静默放行，`approve_mode=auto` 随即自动推送。实测近 5 个 spec 中 2 个（touch-disclosure 3 条、provider-transient-backoff 15 条）带未勾数字任务被推送——竞态实际上是这类 spec 的惯用逃生阀，人工裁决设计从未真正生效。门禁是 auto-push 的最后一道闸，其证据链必须可靠。

## What Changes

- **implementer 结果 per-spec 快照**：dispatch 在 implementer 成功路径把结果 dict 原子快照到 `.fenix/verify-progress/<spec>/impl-result.json`（复用 family.py `prev-impl-result.json` 同款手法与 vp_dir 既有 per-spec 布局）；重派后新结果覆盖旧快照；快照写失败仅告警不阻塞主流程。
- **门禁证据源切换 + fail 方向收敛**：`_task_completion_blocker` 优先读 per-spec 快照，共享文件降级为快照缺失时的兜底；两者皆缺失且 `STATE.implementer_run` 在场且存在未勾数字任务时，由「无法证伪即放行」翻转为拦截（fail-closed），error 带结构化前缀 `task-gap:` 供人工裁决与下游识别。存量兼容：无 `implementer_run`（legacy/手工 spec）与无数字编号任务清单的 spec 行为不变。
- **恢复机制尊重门禁结论**：BLOCKER CHECK 巡检对 error 带 `task-gap:` 前缀的卡 verified spec 不再 auto-recover（不做状态突变），blocker 理由改述为「任务缺口待人工裁决」；event_bus 的 30 分钟 re-trigger 心跳保留——快照落地后重评是确定性的（有缺口必拦、人工补勾后自动放行），是人工修复的感知通道而非危害源。
- 人工补勾任务后，下次 re-trigger 门禁放行、`task-gap:` error 清除、auto-approve 链路正常走完。

## Capabilities

### New Capabilities

- `verified-gate-evidence`: verified→done 门禁的证据寻址与 fail 方向契约——implementer 结果的 per-spec 快照生命周期、门禁评估的证据优先级（快照 > 共享兜底 > fail-closed）、task-gap 结论的结构化持久与清除、恢复机制对门禁结论的尊重、存量 spec 兼容边界。

### Modified Capabilities

（无——源能力 task-progress-sync / recovery-legacy-check 已归档、`spec/specs/` 无活跃副本，lineage 在 design.md 记录；活跃 SPEC add-task-progress-verify-phase 仅涉显示层且明示非目标不改状态机，与本 change 正交。）

## Impact

- 代码：`core/pm_engine/dispatch.py`（implementer 成功路径快照写点，约 15 行）；`core/pm_engine/engine.py`（`_read_implementer_result` 证据源优先级 + `_task_completion_blocker` fail 方向与 task-gap 持久化 + BLOCKER CHECK auto-recover 尊重 error，约 60 行）；`core/event_bus.py`（re-trigger 前置判断，约 10 行）。
- 测试：`tests/test_pm_verification.py`、`tests/test_pm_dispatch.py`（快照写点/证据源优先级/竞态回归/fail-closed/存量兼容/recovery 尊重/人工补勾闭环）。
- 数据：零迁移；`.fenix/verify-progress/<spec>/impl-result.json` 为运行时文件（.fenix 已 gitignore，非交付物）。
- 无新配置键（不触发配置项须带 Dashboard 界面要求）；无 UI 改动。
- **预期行为变化（有意）**：带未勾数字任务的 spec 将可靠停在 verified + task-gap error 等人工（此前被竞态静默放行）；人工动作 = 核对后补勾（验证链已覆盖的验证类任务）或重派。若后续噪声过高，验证链通过后自动回写勾选属 add-task-progress-verify-phase 谱系的后续选题，本 change 非目标。
- 回归面：所有 full 模式 spec 的 verified→done 与 fast-track 推进链（fast-track 与标准车道共享 `is_success` 收口点的快照写点）。
