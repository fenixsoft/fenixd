# 设计：fix-codefix-wipgate-defer

## Context（现状与约束）

- `core/worktree_manager/mergeback.py` 升级拦截出口（add-pipeline-throughput-governance D2 / evo-merge-back-wip-overlap-gate）：主树 tracked-modified 与分支改动重叠时，`policy=escalate`（缺省）不发起 merge，返回 `MergeConflictInfo(success=False, error=…, wip_overlap=[…], wip_gate_blocked=True)`；spec 实现者车道 dispatch 层已「据此旁路熔断」（mergeback.py:92 注释），code-fix 批车道未接该标志。
- `core/worktree_manager/types.py:8` `MergeConflictInfo` 已含 `wip_overlap` / `wip_gate_blocked` 字段——本 SPEC 零框架侧改动。
- `core/code_fix.py` 批 worker 收尾（约 :1298）：`if not getattr(merge_info, "success", False):` 一律走「现场即弃」：`record_failed_batch(reason="merge_back_conflict")` → `_safe_cleanup(success=False)` → `_consumed_progress(reason="merge_back_conflict")` → `return "consumed"`。
- 失败档案机制（add-code-fix-batch-failure-selfheal）：`fix-failed.json` 记 `fail_count`（同条目集复用递增），`FAIL_RETRY_MAX = 3`，新链启动 `release_retryable_failed_batches` 释放预算内记录 → **重跑 agent 整批**。defer 的价值正在于跳过这次重跑。
- 链为单飞（`_code_fix_running` 单飞守卫 + `_in_flight`），批边界 = 批 worker 返回后 `_resubmit → checkpoint`；链收敛出口 = checkpoint 内 `count_open_items(root)==0` 早退分支。
- 运行时台账先例：`.fenix/code-review/fix-failed.json`（`record_failed_batch` / 读侧释放），`.fenix/code-review/fix-progress.json`（`write_progress`/`read_progress`，原子写）。defer 台账沿用同目录同模式。
- 09-23 实证：批 21/22 连烧（各 ~40min agent 产出），`git merge-tree` 证实内容零冲突；批 23 因主树恰好变干净而幸存。

## Goals / Non-Goals

**Goals**
1. wip_gate_blocked 与真冲突在 code-fix 车道可区分，前者零预算消耗。
2. agent 已产出的修复不重做：主树干净后自动合回核销。
3. 主树长期不清理时有确定的降级出口 + 人可见的告警。

**Non-Goals**
- 不做 autostash / 自动提交主树 WIP（人工处置为主，告警给提示）。
- 不改 `worktree.mergeback_wip_overlap_policy` 语义与 spec 车道行为。
- 不改前端（进度 reason 为透传文本；新 reason 值前端按普通文本渲染）。

## Decisions（决策）

### D1 分类入口：读 `wip_gate_blocked`，不解析错误文案
在批 worker 收尾合回失败分支首行加 `wip_blocked = bool(getattr(merge_info, "wip_gate_blocked", False))` 分派。不解析 `error` 字符串（脆弱）；`getattr` 缺省 False 保证对旧类型对象容错。

### D2 defer 台账独立于失败档案
新文件 `.fenix/code-review/fix-deferred.json`（原子写 + `.lock` 惯例同 fix-failed.json）。**不复用 fix-failed.json**：两者生命周期相反（失败档案烧预算、期待重跑；defer 队列零预算、期待原地合回），混写会让释放逻辑误伤 defer 条目。字段：`worktree`、`branch`、`tip_sha`、`item_ids`、`defer_count`、`first_deferred_at`（UTC ISO8601）、`last_overlap`（文件清单，供告警复用）。

### D3 保留 worktree 的锁语义
defer 时跳过 `_safe_cleanup`，worktree 留在磁盘（分支已含全部提交）。单飞链下无并发认领风险；跨链/跨重启由 D5 再认领覆盖。`wip_gate_blocked` 失败本身不污染 worktree 状态（merge 未发起，主树零污染——mergeback.py 升级出口保证）。

### D4 重试时机挂在既有链节拍上，不新增线程
两个重试点全部复用既有节拍：① `_resubmit → checkpoint` 内、选批之前（`_process_deferred_merges()`）；② `count_open_items==0` 收敛早退之前。重试即直接 `wm.merge_back(wt)`（内部预检重跑，过了就合），成功走与正常批一致的 `mark_resolved` + cleanup + 进度累加。每次「实际尝试过 merge_back」且仍被阻断时 `defer_count += 1`（纯等待不递增）。不新增定时器/线程，规避调度复杂度与重启孤儿。

### D5 再认领 = 台账核对磁盘，不做 worktree 状态机重建
新链启动（selfheal 已有的「链身份判定前移到选批之前」位置，`release_retryable_failed_batches` 旁）扫台账：`worktree` 目录存在且 `tip_sha` 可在分支解析 → 保留；否则移出台账 + warning（条目未核销，天然仍在 open 池，无需回写）。不做分支重挂/worktree create 认领（keep_for_reuse 机制复杂度高，收益仅覆盖「daemon 重启 + worktree 被清」双重罕见场景）。

### D6 预算双门 90min / 6 次，告警一次性
时间门兜住「链停摆很久后才恢复」的陈旧 defer；次数门兜住「主树反复变脏」的抖动。降级走 `record_failed_batch(reason="wip_gate_blocked_expired")` 进既有预算体系（`FAIL_RETRY_MAX=3` 之后是既有 blocked 出口），worktree 清理，台账移除。告警复用 admin_alerts 文件信号通道；一次性语义按条目集指纹（同 fix-failed「递增至上限那次发一次性 warning」先例）。首次 defer 的 info 提示用 `last_overlap` 渲染文件清单。

### D7 文案与 reason 常量
- defer 进行：reason=`wip_gate_blocked`，current=「第 N 批合回待重试（主树未提交改动：<files>）— 已保留，主树清理后自动合回」
- defer 成功：current=「延迟批合回成功（核销 N 条）」
- 降级：reason=`wip_gate_blocked_expired`
- 真冲突文案不变（回归保护）。

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| defer 期间 worktree 占盘（每批 ~几十 MB，预算 90min 上限） | 预算双门强制收敛；降级路径必 cleanup |
| 主树长期脏 → 每 defer 批 90min 后连环降级烧档案 | 首次 defer 即告警提示人工；降级后进既有 FAIL_RETRY_MAX 体系自然 blocked，不会无限烧 |
| 重试点 merge_back 抛异常打断链节拍 | 包裹 try/except 记 warning 继续（同 `_safe_cleanup` 哲学：锁泄漏比异常更糟） |
| 台账与磁盘真相漂移（手删 worktree 等） | D5 再认领核对磁盘，不可解析即回收；条目天然可重选批 |
| 批条目在 defer 期间被人工改状态（如置 ignored） | 合回成功核销时 `mark_resolved` 仅对仍非终态条目生效（既有核销原语行为），天然幂等 |

## Migration / 兼容

- 空 `fix-deferred.json`（或文件不存在）= 无延迟批，全部既有路径零变化。
- 真冲突路径行为逐字不变（Scenario 回归锁定）。
- 升级部署时若有历史「现场即弃」档案（如 09-23 批 21/22 的 branch/tip_sha），不自动救回（它们已被 cleanup、重建 worktree 成本≈重跑）；本 SPEC 只对未来生效。
