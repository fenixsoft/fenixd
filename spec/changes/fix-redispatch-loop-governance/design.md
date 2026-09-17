# Design: fix-redispatch-loop-governance

## Context

`fix-robustness-edge-cases` 事故（2026-09-17）：实现 run 每一轮都**真实成功**（`result.success=True`、进程 exit 0、14/15 任务完成、结果文件如实写 `status: "partial"` + `unattainable: [4.2]`），却连续被判失败重派 3 轮，每轮约 $18，且每轮 5 个提交整支丢弃。

三层根因，本次立项覆盖全部：

1. **读源自锁**（已原地修复，本 spec 补契约与防回退）：诚实退出的三处缺口消费原本在缺 `unfinished` 时回退读**主树** `tasks.md`；主树 `[x]` 只由 `_sync_task_progress` 在成功/merge-back 路径回写，partial 收敛走不到 → 「未收敛 → 主树全未勾 → 已完成项也算缺口 → 收敛不成立」的闭环。
2. **重派熔断是空转**（本 spec 新发现）：`dispatch.py` 的失败重派分支在 `retries >= max_r` 时**把 `_retry_count` 重置为 0 后立即 `_enqueue` 重派**——`agents.max_retries: 3` 形同虚设，「All retries exhausted」只是一行日志。实测该 spec `_retry_count` 始终为 1 却跑了 4 轮。
3. **成果不继承**（本 spec 新增治理）：`keep_for_reuse` 只在**失败/取消**路径触发；run 层报成功时走 `cleanup(success=True)` 清理 worktree。于是「run 成功但 spec 层判失败」的重派必然从 main 新建 worktree，前一轮成果只剩分支。

### 关键既有机制（现状实证）

| 机制 | 位置 | 现状 |
|---|---|---|
| 诚实退出收敛判定 | `dispatch._honest_exit_gap` | 已改调 `gap_from_result`（读源修复） |
| 缺口口径 | `run_task_track.gap_from_result` | 本次新增；`unfinished` 优先，否则 `全部任务 − completed_tasks` |
| 失败重派计数 | `dispatch` 失败分支 | `retries >= max_r` → **清零 + 照样重派**（空转） |
| 实现预算 | `agents.impl_run_budget`（缺省 6） | 真实生效，事故中 used 到 4/6 |
| 死亡 run 豁免 | `_exempt_dead_run_budget` | 仅「run 无收工结果」形态，与同因重派正交 |
| worktree 复用 | `worktree_manager._take_reusable_worktree` / `keep_for_reuse` | 继承仅失败/取消路径触发 |
| 配置项 UI 约定 | `agents.scale_precheck` 先例 | 新配置键 MUST 带设置界面（`TokenBudgetPanel` 页签） |

## Goals / Non-Goals

**Goals:**

- 把「诚实退出收敛」固化为**可测契约**（判据 / 口径单点 / 收口序列 / 两车道对称 / 留痕）。
- 让 `agents.max_retries` **真正生效**：同因重派达阈值即冻结转人工，而非清零重派。
- `partial` 收敛不成立或后续卡门需要重派时，**继承上一轮 worktree 与分支成果**。
- 新增配置键提供 Dashboard 设置界面。

**Non-Goals:**

- 不改变 `unattainable` 申报本身的语义与合法性校验（既有 `parse_unattainable` 已覆盖）。
- 不重新设计整个重试/退避体系（transient / merge-fingerprint / 锁冲突退避各有其道，本变更不动）。
- 不修改验证阶段（verifier）的行为。

## Decisions

### D1：收敛判据（固化现状 + 补不对称）

```
收敛成立 ⟺ result.success ∧ impl_status == "partial"
            ∧ (缺口 := gap_from_result(impl_result, project_root, spec))
            ∧ 缺口 非空 ∧ 缺口 ⊆ unattainable_ids
```

- 「缺口 ⊆ unattainable」**且缺口必须非空**——缺口为空而 `status=partial` 属于申报不自洽（结果门 `_check_partial_consistency` 会拦），此处不重复判定但 MUST NOT 把「无缺口」也当收敛放过。
- 收敛成立 ⇒ `impl_error = None`、`is_success = True`，随后走**既有成功路径全链**（零变更哨 → 交付物守卫 → relint → merge-back → verifier），MUST NOT 短路。
- 缺口口径 MUST 单点 `gap_from_result`；**禁止**任何回退读主树勾选的路径。

### D2：两条车道对称化

`_run_agent_worker`（full）与 `_run_fast_track_flow`（fast-track）两处 `honest_exit_gap` 用法 MUST：

- 同一判据函数（`_honest_exit_gap`），MUST NOT 各自实现一套；
- 同一收口语义（不重派 + 转成功收口）；
- 同一留痕（`_note_unattainable_todos` 人工待办告警 + 含缺口清单的日志）。

已知且**允许**的差异（MUST 在契约测试中显式记录，避免被误判为不对称）：

| 维度 | full 车道 | fast-track 车道 |
|---|---|---|
| 收敛后去向 | `implemented` → 入队 verifier | `_hard_check_fast_track` → `_fast_track_advance_to_verified`（单 run 全包，无独立 verifier 车道） |
| 缺口归因入口 | `_partial_attribution` | `_partial_attribution`（同函数） |

### D3：同因重派熔断（替代空转的 max_retries）

**现状**：`retries >= max_r` 时清零 + 重派 = 无熔断。本变更 MUST 让该分支真正终止自动重试。

- 「同因」判据（机械、可测）：对失败归因文案做**归一化指纹**（`_merge_fingerprint` 的同族手法——取稳定前缀/哈希，剔除 run_id、时间戳、路径等易变段），连续同指纹计数 `_redispatch_same_cause_streak`。
- 阈值：新增配置键 `agents.max_same_cause_redispatches`（缺省 **3**），达阈值 → **冻结转人工**（`state_machine.freeze_for_human`，`status=blocked` + `frozen=True` + 人工升级告警，signal_type `redispatch_loop_detected`），MUST NOT 再 `_enqueue`。
- 计数载体：STATE 新字段 `_redispatch_same_cause_streak` + `_redispatch_cause_fp`（随条目序列化，须加进 `serialize` 显式键表）；差异化原因（指纹变化）即重置为 1。
- 解冻：`unfreeze_spec` 现有语义已清多个计数字段，MUST 同步清零这两个新字段（人工处置后从零起算）。

**为什么不用改 `max_retries` 本身**：`max_retries` 现有语义是「连续失败重试次数」，用于 transient/一般失败；把它改成熔断会改变既有行为面。新增同因维度更精准——**每轮都在变的原因不该熔断，每轮不变的原因才该**。

### D4：成果继承

`partial` 收敛不成立（确有未申报缺口）或收敛后卡在后续门而需重派时，MUST 保留 worktree 供下轮认领：

- 现有 `keep_for_reuse` 触发集中在 `runner.py` 的失败/取消/transient 分支；MUST 扩展覆盖「run 层成功但 spec 层判失败重派」形态。
- 实现方式（design 层面二选一并记录理由）：① runner 侧把「partial 且 non-convergent」纳入 keep 判定；② dispatch 侧在判重派前显式调用 `keep_for_reuse`（须确保 worktree 尚未被 `cleanup(success=True)` 删除——注意当前 runner 成功路径**先** cleanup，故 ① 更自然）。
- **MUST NOT 影响**成功推进路径的 `cleanup(success=True)` 语义（正常收敛/成功时仍清理 worktree、保留分支）。

### D5：配置键与 Dashboard 界面

新增 `agents.max_same_cause_redispatches`（正整数，缺省 3，范围 1–100）MUST：

- 进 `_AGENTS_MANAGED_SUBKEYS` / `_SOURCE_KEYS`（`config_admin.py`）；
- `read_config` / `read_effective_config` 回显（缺省填充 + 非法回退走归一化函数）；
- `_deep_merge_managed` 合并分支 + `write_config` 合法性校验；
- `TokenBudgetPanel`（设置界面「预算」页签）提供输入项；
- `config.template.yaml` 补模板与说明。

（沿用 `agents.scale_precheck` 的落地范式；缺任一项即为「新增配置项无 Dashboard 界面」，违反项目约定。）

### D6：不使用绝对行号锚定

任务与交付物以函数名 / 字段名 / 配置键锚定。

## Risks / Trade-offs

- **[风险] 同因熔断误冻真需多轮修复的 spec** → 缓解：「同因」以归一化指纹判定，每轮原因变化即重置；阈值可配且缺省保守（3）。
- **[风险] 归因指纹归一化过度 → 不同原因被判同因** → 缓解：指纹只剔除易变段（run_id/时间戳/路径），保留原因主干；须有「不同因不误熔断」的回归用例。
- **[风险] 成果继承把脏现场带进下一轮** → 缓解：现有 `keep_for_reuse` 已有 dirty 登记与 WIP checkpoint 语义，直接复用；MUST NOT 新增旁路。
- **[风险] 新计数字段未进序列化键表 → daemon 重启丢失** → 缓解：MUST 加进 `state_machine` 的显式序列化键表，并有重启保持性测试。
- **[风险] 改动落在 `dispatch.py`/`runner.py`（高频改动文件）** → 缓解：改动集中在既有分支内，不重排结构。

## Migration Plan

1. 阶段 1：缺口口径反回退守卫 + 收敛链契约测试（固化现状）。
2. 阶段 2：两车道对称化 + 留痕对齐。
3. 阶段 3：同因重派熔断（含配置键 + Dashboard 界面）。
4. 阶段 4：成果继承。
5. 阶段 5：全量回归与基线比对。

回滚：各阶段独立 commit。

## Open Questions

- 归因指纹的归一化规则具体到什么粒度（剔除哪些段）——实现阶段以「同缺口的连续 partial」与「同一 merge 错误」两个样本校准。
