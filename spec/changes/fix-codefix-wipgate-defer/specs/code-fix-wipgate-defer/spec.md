# code-fix-wipgate-defer 能力规格

code-fix 批合回遇主树 WIP overlap 预检阻断（`wip_gate_blocked=True`）时的延迟合回语义：批不即弃、预算不烧、主树干净后自动合回核销。

## ADDED Requirements

### Requirement: 合回阻断分类语义

code-fix 批收尾合回失败时，MUST 先读 `merge_info.wip_gate_blocked` 并分派到互斥的两条路径：
- `wip_gate_blocked=True` → defer 路径（见下一 Requirement），reason 恒为 `wip_gate_blocked`；
- `wip_gate_blocked=False`（真内容冲突或其他 git 失败）→ 维持既有「现场即弃」路径：`record_failed_batch(reason="merge_back_conflict")` + `_safe_cleanup(success=False)` + `fail_count` 预算照常。

两条路径的进度文案 MUST 可区分：「合回被主树未提交改动挡住」vs「合回冲突」。

#### Scenario: wip_gate_blocked 不烧失败预算
- **WHEN** 某批合回返回 `success=False` 且 `wip_gate_blocked=True`（主树脏文件与分支改动重叠）
- **THEN** `fix-failed.json` 不新增记录、任何条目的 `fail_count` 不递增；worktree 目录保留（未被 cleanup）；进度 reason 为 `wip_gate_blocked`，current 文案含「主树未提交改动」及交集文件名；批 worker 返回使链继续后续批

#### Scenario: 真冲突维持现状
- **WHEN** 某批合回返回 `success=False` 且 `wip_gate_blocked=False`
- **THEN** 行为与改动前完全一致：条目入 `fix-failed.json`（`reason="merge_back_conflict"`，`fail_count` 递增）、worktree 被清理、链继续

### Requirement: 延迟合回队列

wip_gate_blocked 时 MUST 把该批记入延迟台账 `.fenix/code-review/fix-deferred.json`（原子写，条目字段：`worktree`、`branch`、`tip_sha`、`item_ids`、`defer_count`、`first_deferred_at`、`last_overlap`），同时**保留 worktree**（跳过 cleanup）。台账中的条目不参与选批排除（其 `item_ids` 已随批交付，只是未合回）。

#### Scenario: defer 记录完整可恢复
- **WHEN** 一批进入 defer 路径
- **THEN** `fix-deferred.json` 新增一条含全部七个字段的记录；`first_deferred_at` 为 UTC ISO8601；该批 worktree 路径在磁盘上仍存在且分支 tip 等于记录的 `tip_sha`

### Requirement: 延迟批自动重试合回

链 MUST 在两个时机重试延迟批的 merge_back（直接对保留的 worktree 重跑 `wm.merge_back`，不重跑 agent）：① 每个 batch worker 收尾后的链边界（选下一批之前）；② 链收敛出口（无 open 条目落 idle 之前）。重试成功 → `mark_resolved` 核销该批 fixed 条目 + `_safe_cleanup(success=True)` + 从台账移除 + 进度 done 累加；仍被阻断 → 保留台账原样（不递增 `defer_count`，等下一边界）。

#### Scenario: 主树清理后自动合回
- **WHEN** 延迟批在台账中，且主树脏文件已被提交（或 stash），链到达任一重试时机
- **THEN** merge_back 成功，该批 `item_ids` 中 fixed 条目被核销为 resolved，worktree 被清理，`fix-deferred.json` 中该条目消失，进度 current 显示「延迟批合回成功（核销 N 条）」

#### Scenario: 主树仍脏时重试无害
- **WHEN** 延迟批重试时主树脏文件依旧
- **THEN** merge_back 再次返回 `wip_gate_blocked=True`，台账条目原样保留（`defer_count`、`first_deferred_at` 不变），链正常继续

### Requirement: 延迟预算与人工升级

延迟批带预算：`first_deferred_at` 起超过 **90 分钟**，或链边界重试让 `defer_count` 递增达 **6 次**（重试时机包括选批前与收敛出口，仅当本次重试发生了实际 merge_back 尝试才递增），任一先到即判定预算耗尽：条目按 `reason="wip_gate_blocked_expired"` 入 `fix-failed.json`（`fail_count` 正常递增）→ 清理 worktree → 移出台账 → 发一次性 admin 告警（同一条目集只发一次），告警含交集文件清单与「提交（git add/commit）或 stash（git stash push）主树改动」处置提示。首次进入 defer 路径时 MUST 发一条 info 级提示告警（含交集文件清单）。

#### Scenario: 预算耗尽降级并告警
- **WHEN** 延迟批 `first_deferred_at` 距今超过 90 分钟（或 `defer_count` 达 6）且仍被阻断
- **THEN** 该批条目以 `reason="wip_gate_blocked_expired"` 入 `fix-failed.json`（fail_count 递增 1）、worktree 清理、台账条目移除、admin 告警恰发一条且含文件清单

#### Scenario: 首次 defer 即提示
- **WHEN** 某批首次进入 defer 路径
- **THEN** 当轮即发一条 info 级 admin 告警，正文含交集文件路径清单

### Requirement: 换链与重启后再认领

新链启动（activation_id 更新）处理台账：worktree 目录仍存在且分支 tip 可解析的条目 → 原样保留继续重试（`defer_count`/`first_deferred_at` 沿用，不重置）；worktree 已不存或分支不可解析的条目 → 其 `item_ids` 放回 open 池（无操作即自然回归，因未核销）+ 清出台账 + 记 warning 日志。daemon 重启不丢台账（文件持久化）。

#### Scenario: 重启后台账存活条目续试
- **WHEN** daemon 重启后新链启动，`fix-deferred.json` 有一条 worktree 仍存活的记录
- **THEN** 该记录字段不变地保留在台账中，链边界重试照常覆盖它

#### Scenario: worktree 丢失条目回收
- **WHEN** 新链启动发现台账条目的 worktree 目录已不存在
- **THEN** 该条目从台账移除并记 warning；其条目因从未核销而仍在 open 池，可被后续链重新选批
