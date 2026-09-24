## Why

`start_after`（定时拾取）门控只挡在 **ready 派发口**（`_on_spec_ready` / `_recover_ready`），
却没挡在 **晋升/评审入口**。于是一个处于 `drafted` 且 `start_after` 为未来时间的 SPEC，
一旦被任何路径触发 `spec_drafted` 事件，就会被立即晋升出草稿态——定时语义被击穿。

2026-09-18 实证：SPEC `add-project-detail-tabs` 的 `start_after` 为本地 09-19 00:00
（UTC 16:00），却在 daemon 于 23:17 启动后的**首个扫描周期**（23:18）被
`Recovery: re-triggering promote` → `Auto-promoting: drafted → reviewing` 提前约 42 分钟
拾取并起评审 run。这不是启动路径独有：daemon 在线时**注册新 SPEC**（`/fenix-new` 带
`--start-after`）走同一条 `_dispatch_changes` 扫描 → `spec_drafted` → 晋升链，同样会偷跑。

同型缺口还波及 `start_after: manual`（待激活哨兵）：待激活 SPEC 注册为 `drafted` 后会被
晋升出草稿态。该形态**并非仅语义错位**：若分流判定命中评审（`promote_drafted` 返回
`next_status="reviewing"`），`_on_spec_drafted` 会同步直调 `_on_spec_reviewing` 派发
**真实评审 run**——评审派发经 `SpecReviewManager.dispatch_review`，不经派发队列的
`start_after_pending` 谓词（`core/pm_engine/dispatch/queue.py:233/317`），故派发口的既有
门拦不住它。实证：`add-project-detail-tabs`（未到期）15:18:01 晋升 reviewing 后
15:18:03 即起评审 run（`.fenix/logs/fenixd.log:41314-41320`），`manual` 哨兵 SPEC 走
同一条链。

## What Changes

- **晋升入口补齐 `start_after` 门控**：`_on_spec_drafted` 与 `_on_spec_reviewing` 入口
  各加一道守卫——`start_after_pending(entry)` 为真（未到期或 `manual` 哨兵）时静默跳过，
  不软化、不 lint、不写 error、不派发（对齐 `_on_spec_ready` 既有守卫语义）。
- **recovery 分支早退**：`_recover_one` 的 `drafted` / `reviewing` 分支在触发 handler 前
  先过 `start_after_pending` 早退（对齐 `_recover_ready` 既有早退），避免每轮扫描生产
  「re-triggering promote」噪音事件。
- **附带修正**：`manual` 哨兵 SPEC 不再被自动晋升出 `drafted`，稳定停留在待激活态。
- 到期/清空/激活后经同一 handler 正常放行（守卫为实时评估，无残留限制）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `scheduled-spec-pickup`: 现有「调度器对未到期 SPEC 跳过拾取」Requirement 的覆盖范围从
  **仅 ready 派发候选筛选**扩展到 **晋升（drafted→ready/reviewing）与评审入口**——任何
  会推进 SPEC 进入调度的入口 MUST 过 `start_after` 门；并新增 Requirement 规定 recovery
  与扫描路径统一受该门约束。

## Impact

- **代码**：`core/pm_engine/engine.py`（`_on_spec_drafted` / `_on_spec_reviewing`）、
  `core/event_bus.py`（`_recover_one` 的 `drafted` / `reviewing` 分支）。
- **测试**：新增 `tests/test_start_after_gate.py`（覆盖四条自动通道与三条放行路径，见
  tasks.md）；既有 `tests/test_spec_scheduling.py` / `tests/test_event_bus.py` /
  `tests/test_pm_promotion_gate.py` 作为回归基线一并跑通（无 `start_after` 的条目
  行为完全不变，既有用例无需改动）。
- **行为变更**：`drafted`/`reviewing` 态且 `start_after` 未到期的 SPEC 不再被自动晋升；
  `manual` 哨兵 SPEC 停在 `drafted`（此前会被晋升到 `ready`/`reviewing`，并可能直接派发
  评审 run）。`manual` SPEC 的人工激活语义不变：`activate_spec` 置 null + kick 信号后，
  daemon 消费信号时 `start_after` 已为 null → 守卫放行 → 正常晋升与派发
  （`core/dashboard/data/admin_actions.py:423-427` → `.fenix/fenixd.py:1157`）。
- **无破坏性**：既有无 `start_after`（null）的 SPEC 行为完全不变；`start_after` 已到期的
  SPEC 行为完全不变。
