# 设计：verified→done 门禁证据持久化治理

## Context

事故链（2026-09-07，`.fenix/logs/fenixd.log` 实证）：

1. `fix-mobile-breakpoint-hook-tables` 第 2 轮验证通过 → verified。门禁 `_task_completion_blocker`（engine.py，源自已归档 add-task-progress-sync）读主树共享文件 `.fenix/.fenix-run-result.json`（stamp=本 spec、status=success），检出未勾数字任务 4.2/4.3/4.4（run 产物 done_ids 为空、仅 flat_done）→ 正确拦截，error 写「未完成任务：4.2、4.3、4.4」。
2. event_bus 恢复巡检把「卡在 verified」当瞬态异常（"卡 0 分钟，应为瞬态"），无视 error 字段，每 30 分钟 re-trigger `spec_verified`。
3. 07:59 另一 spec（add-lost-semantics-regression-tests）实现成功，其分支把 tracked 的 `.fenix-run-result.json` 草稿经 merge-back 带入主树（`worktree_manager.py:2332` 记载的运行时草稿失控史），共享文件 stamp 被覆盖。
4. 08:17 第三次 re-trigger：`_read_implementer_result` 命中「stamped != spec_name → 视作残留 → 返回 None」→ 门禁走「无 run 记录放行（无法证伪即放行）」→ 放行 → done → `approve_mode=auto` 12 秒后自动推送。

**lineage**：门禁源能力 = 已归档 `2026-09-02-add-task-progress-sync`（capability `task-progress-sync`）；恢复巡检 = 已归档 `2026-09-06-add-recovery-legacy-check`（capability `recovery-legacy-check`）。两者在 `spec/specs/` 无活跃副本，本 SPEC 以新能力 `verified-gate-evidence` 承接其修正。

**关键洞察**：门禁是无状态重复评估，证据却易失——recovery 循环只需扛到证据被覆盖即自动放行。修复的第一性原理是**证据寻址持久化**：决策读「这个 spec 自己的」持久证据，而非「最新的那个」共享事件。框架已有同款正确形态：verifier 结果落 `.fenix/verify-progress/<spec>/`（prompt_builder `{result_path}`）、family.py 注入 fix 上下文时把共享文件快照为 `prev-impl-result.json` 并注明「根文件会被后续 run 覆盖」。本设计把 implementer 结果纳入同一寻址。

## Goals / Non-Goals

**Goals**
- 门禁对「未勾数字任务」的拦截在任何 re-trigger 时序下都确定性成立（证据不随共享文件覆盖而蒸发）。
- 证据彻底缺失时 fail-closed（停在 verified + 结构化 error），不静默放行。
- 恢复机制不做绕过门禁结论的状态突变；人工补勾后 ≤30 分钟自动感知并走完 auto-approve。
- 存量兼容：legacy/手工 spec、无数字编号任务清单的行为不变。

**Non-Goals**
- 验证链通过后自动回写 4.x 验证类任务勾选（add-task-progress-verify-phase 谱系的后续选题）。
- 共享文件 `.fenix/.fenix-run-result.json` 的退役或写通道收敛（fast-track/repair prompt 相对路径契约、旧分支 tracked 草稿搬运）——本 change 只降级其读者地位，不动写侧。
- `approve_mode` 语义调整（auto/manual 取舍是用户配置决策）。
- done_ids / flat_done 解析口径（`parse_run_task_done` 维持现状；done_ids 证据本就在 per-run jsonl 中，非易失）。

## Decisions

### D1 快照写点与布局（dispatch 成功路径）

- **写点**：dispatch.py implementer 成功分支（`is_success` 收口，`_reconcile_impl_budget` 前后皆可，须在 merge-back 之前——merge 不影响快照内容，但放前面语义更清晰：成功即快照）。
- **内容**：`_read_implementer_result` 已解析的同一 dict（含 spec stamp、status、summary、verification 段、findings）。**不重构内容、原样落盘**——门禁与 fast-track 硬校验消费的是同一 schema。
- **路径**：`.fenix/verify-progress/<spec>/impl-result.json`。与既有 vp_dir 文件（test_scenarios.json / report.json / prev-impl-result.json）并置；文件名避开 `prev-impl-result.json`（family.py 所有物）。
- **原子写**：tempfile + `os.replace`（同 `_sync_task_progress` 手法）。
- **失败语义**：写侧 fail-open——OSError 等仅 WARNING 日志，不阻塞派发主流程（快照缺失由门禁 fail-closed 兜底，见 D2）。
- **幂等**：重派后新成功覆盖旧快照（`os.replace` 天然幂等）；fast-track 车道与标准车道共享 `is_success` 收口点则一并覆盖，若代码路径分离则仅标准车道落地（fast-track 的 verified→done 与成功处理同周期同步执行，竞态窗口为进程内顺序执行，不存在跨 spec 覆盖窗口）。

### D2 门禁证据优先级与 fail 方向（`_task_completion_blocker`）

评估顺序（tasks.md 无数字编号任务 / tasks.md 缺失时维持现状直接放行，不进入下述判定）：

1. **per-spec 快照存在** → 以快照 + 当前 tasks.md 勾选 ∪ done_ids（per-run jsonl，`parse_run_task_done`）评估。有缺口 → 拦截，error = `task-gap: 未完成任务：<ids>`；无缺口 → 放行并清除既有 `task-gap:` error（人工补勾的感知路径）。
2. **快照缺失，共享文件 stamp=本 spec** → 以共享文件评估（存量在飞 spec 兼容，行为与现状一致）。
3. **两者皆缺失**：
   - `STATE.implementer_run` 为空（legacy/手工）→ 放行（现状不变）；
   - `implementer_run` 在场 → **fail-closed 拦截**，error = `task-gap: run 证据缺失（快照与共享文件均无），需人工确认`。此分支正常不应触达（快照在 implementer 成功时必写），仅防御快照被误删/磁盘异常。

`task-gap:` 前缀常量单点定义（pm_engine 模块级），写侧（error 字段）与读侧（恢复巡检、门禁自清除）共用，杜绝字面量漂移。

与 vblocker（`_check_verification_gate`）的合并语义维持现状：两者并存时合并 error，vblocker 在场仍走 D7 逃生门回 testing；D7 的 error 覆盖使 task-gap 标记暂时消失是**可接受的**——重验证完成后门禁从持久快照重新评估，缺口仍在则重新落标记。

### D3 恢复机制尊重门禁结论

- **BLOCKER CHECK（engine.py 巡检）**：卡 verified 且 error 带 `task-gap:` 前缀的 spec，从「卡在 verified 状态 N 分钟（应为瞬态）→ Auto-recovering」路径改为：不触发 auto-recover，blocker 条目 reason 改述「任务缺口待人工裁决：<缺口摘要>」。spec 持续出现在 blocker 清单中 = 人工告警通道（既有 admin 可见性，不新增告警设施）。
- **event_bus re-trigger（event_bus.py:154）**：**保留**。快照落地后重评是确定性的：有缺口 → 再拦（无状态突变，幂等）；人工已补勾 → 放行 + 清 error + auto-approve。re-trigger 是人工修复的感知心跳，不是需要消灭的危害源。
- **危害归零的论证**：事故的充要条件 = 重复评估 × 证据蒸发。D1 消灭蒸发，D2 消灭 fail-open，D3 只剩降噪与显性化——三层独立，任一层单独存在都不会复现静默推送。

### D4 存量兼容矩阵

| 场景 | 行为 |
|------|------|
| 正常新 spec（快照存在，全勾） | 放行（现状） |
| 正常新 spec（快照存在，有缺口） | 拦截 + task-gap error（现状设计意图，竞态修复后真正生效） |
| 部署时刻在飞、已过 implementer 成功但无快照 | 走共享文件兜底（现状行为） |
| 快照与共享文件皆无、implementer_run 在场 | fail-closed 拦截（新行为，预期罕见） |
| legacy/手工 spec（无 implementer_run） | 放行（现状不变） |
| tasks.md 无数字编号任务（含 family 注入的纯无编号 fix 任务） | 无 gap 概念，放行（现状不变） |

## Risks / Trade-offs

- **吞吐回退（有意接受）**：带未勾验证类任务（4.x playwright）的 spec 将可靠停在 verified 等人工（实测近 5 个 spec 中 2 个受影响）。人工动作轻（核对验证已覆盖 → 补勾），换取静默完整性漏洞关闭。若噪声过高，后续由验证链回写勾选收敛（Non-Goals 引用）。
- **快照与共享文件短暂不一致**（重派期间旧快照在、新结果未落）：门禁读旧快照可能对重派前状态误拦——重派本身意味着上轮未通过 verified，门禁本就未放行，无误放行风险；误拦方向安全（多拦一次，重评自愈）。
- **`task-gap:` 前缀与其他 error 写入方互踩**：error 字段本就是单值覆盖语义，D2/D3 只认前缀不假设独占；被覆盖后快照仍在，下轮重评重建标记。

## Migration Plan

纯增量：新快照文件按需生成，无存量数据迁移；部署时在飞 spec 由 D4 兜底矩阵覆盖。回滚 = 还原三个文件，快照文件残留无害（仅新代码读取）。

## Open Questions

（无——execute 模式用户已确认 full；fail 方向、兼容边界、恢复语义均已在 proposal 阶段与用户对齐。）
