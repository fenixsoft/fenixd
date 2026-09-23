# 提案：fix-codefix-wipgate-defer

## Why（为什么做）

code-fix 车道把 merge-back 的 **WIP overlap 预检阻断**（`MergeConflictInfo.wip_gate_blocked=True`，`core/worktree_manager/mergeback.py` 升级拦截出口）当**普通合回冲突**消费：整批「现场即弃」——agent 已完成并提交在 worktree 分支的全部修复作废（只留 branch/tip_sha 档案），条目入 `fix-failed.json` 烧 `fail_count` 预算，下轮重试**重跑整个 agent**。而多会话并行开发下「主树 WIP 与批改动文件重叠」是常态，导致连环烧批。

**实证（2026-09-23）**：批 21（01:38 UTC）、批 22（02:09 UTC）连续「合回冲突，现场即弃」，各烧约 40 分钟 agent 产出；`git merge-tree` 证实两分支与主树 HEAD 内容合并**零冲突**——纯粹是主树 tracked-modified 挡路，属可等待自愈的暂态，不应消耗任何失败预算。

spec 实现者车道已正确区分（mergeback.py:92「wip_gate_blocked=True 的可区分失败，dispatch 层据此旁路熔断」），code-fix 批车道需要对等处理。

## What Changes（改什么）

1. **分类语义**：`core/code_fix.py` 批收尾合回失败分支先读 `merge_info.wip_gate_blocked`：
   - `True` → 走新增 **defer 路径**：独立 reason `wip_gate_blocked`，不进 `fix-failed.json`、不烧 `fail_count`，进度文案区分「主树未提交改动挡住合回」与「合回冲突」；
   - `False` → 维持现状（现场即弃 + 失败档案 + 预算）。
2. **延迟合回队列（根治）**：wip_gate_blocked 时**保留 worktree**（跳过 cleanup），把 {worktree, branch, tip_sha, item_ids, defer 元数据} 记入新运行时台账 `.fenix/code-review/fix-deferred.json`；批条目照常放行使链继续跑后续批。链在每个批边界（checkpoint 选批前）与链收敛出口重试延迟批的 merge_back——agent 产物已提交，只需合回：成功即 `mark_resolved` 核销 + cleanup，不重跑 agent。
3. **预算与升级告警**：延迟批带预算（超时上限 90 分钟或重试次数上限 6 次，取先到）；耗尽 → 降级入失败档案（`reason=wip_gate_blocked_expired`，正常烧 `fail_count`）+ 清理 worktree + 发一次性 admin 告警（含交集文件清单与「提交或 stash 主树改动」处置提示，文案复用 mergeback.py 升级出口既有话术）。首次 defer 即发 info 级提示告警。
4. **重启/换链恢复**：新链启动时再认领 `fix-deferred.json` 中 worktree 仍存活的条目继续重试；worktree 已不存的条目将条目放回 open 池并清档（记 warning）。

## Capabilities（能力）

- `code-fix-wipgate-defer`（新增）：code-fix 批合回遇主树 WIP 预检阻断时的延迟合回语义。

## Impact（影响面）

- `core/code_fix.py`：批收尾失败分支 + 延迟队列读写/重试/再认领（核心改动面）。
- `tests/test_code_fix.py`：分类分支、defer 重试、预算降级、再认领回归。
- 不改 `core/worktree_manager/*`（`wip_gate_blocked` 标志与策略已齐备）；不改前端（进度 reason 为透传文本）。
- 非目标：不实现 autostash/自动提交主树 WIP（人工处置提示已够）；不改 spec 实现者车道的既有升级语义。
