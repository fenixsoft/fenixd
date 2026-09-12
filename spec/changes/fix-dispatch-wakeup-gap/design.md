## Context

Fenix daemon 的派发由两条路径驱动，二者互不重叠：

- **事件驱动（正常路径）**：`EventBus._watch_loop()` 每 2 秒轮询 `.fenix/STATE.md` 校验和；变化即调 `_dispatch_changes()`，后者**只为 status 发生变化的那条 SPEC** 产出事件（`drafted/ready/implemented/verified/bug-found/done` → 对应 `spec_*`），经 `PMEngine.handle_event` 入队派发。
- **兜底扫描（fallback）**：`full_scan()` 只在三个时机执行——daemon 启动、STATE.md 变化、每 `schedule.poll_interval_minutes`（默认 30）的周期扫描。它做三件事：`_dispatch_changes()`（同上）、逐条 `_recover_one()`（孤儿 ready 白名单恢复、中断态回退等）、`check_blockers()`（含 `check_recovery_watch()`）。

实测（2026-09-12，192 个 SPEC）`full_scan` **中位 26.7 ms**，137 次中 100 次低于 100 ms；仅有的两次 >5 s 分别是窗口内套了一次远端 `git push`（4.45 s 网络 IO）与 daemon 启动冷路径。**扫描本身不是成本瓶颈**，30 分钟这个默认值是在「兜底及时性」与「recovery 副作用放大半径」之间取的保守值——`_recover_one` 的注释留有疤痕：recovery 的 re-trigger 逻辑一旦有缺陷，缩短间隔会成比例放大（`add-spec-status-modal-budget` 曾有每小时重验 9 轮的实证）。

真正的问题不是间隔太长，而是**有两类 SPEC 落在这两条路径的空隙里**：

1. **依赖满足型**：`PMEngine._dependencies_satisfied()`（engine.py:1901）只在该 SPEC **正在被派发时**求值。依赖不满足即出队丢弃；依赖后来转入接受态时，那是**别的 SPEC** 的状态变化，`_dispatch_changes` 不会为等待者产出事件。
2. **观察项通过型**：`RecoveryWatch.check_recovery_watch()`（recovery.py:101）通过时只记 INFO 并关闭观察项，**不派发**。且其通过条件是「status 与登记时不同」，与 `post-recovery-patrol` 声明的「已离开 ready / 已有活跃派发」在「登记时 implementing → 窗口内回退 ready」这一真实形态下分叉——按声明是未恢复，按实现却判为通过。

## Goals / Non-Goals

**Goals:**

- 依赖转为接受态时，等待中的 dependents **事件到达即唤醒**，不再最坏等一个扫描周期。
- 观察项到期时，仍滞留 `ready` 且无活跃派发的 SPEC **就地重新派发**，而不是静默关闭；派发不成立才升级 `dispatch_stalled`。
- 两条唤醒路径都**不新增定时器、不改扫描间隔、不动优先级/并发/预算闸门**。

**Non-Goals:**

- 不调整 `schedule.poll_interval_minutes` 默认值，也不改变 `full_scan` 的触发源与语义。
- 不重构派发队列、不引入外部消息总线、不做跨 daemon 的分布式事件。
- 不处理 `start_after` 定时调度到期这一唤醒源（已由既有 scheduled-spec-pickup 能力覆盖）。

## Decisions

### D1：依赖唤醒挂在「接受态转换」的既有事件出口，不新增扫描

`_dispatch_changes()` 已经在逐条比较 status 变化。在它检出某 SPEC 转入接受态（`done` / `pushed` / `implemented` / `verified`）时，追加一次「反查 dependents → 逐个重评」的动作即可，触发器仍是既有事件源，**零新增定时器**。

反查方式二选一：遍历 `read_all()` 里所有 SPEC 的 `depends_on` 字段做匹配（192 条内存字典遍历，微秒级），或维护反查索引。选**遍历**——SPEC 数量在百量级，索引带来的失效维护成本高于收益；且复用已读入的 `current_specs`，无额外 IO。

**理由**：把唤醒点绑在「依赖确实变好了」这一事实上，而不是绑在时间上。这同时天然避免了「缩短间隔会放大 recovery 副作用」的问题——定向唤醒不经过 `_recover_one`。

### D2：重评复用 `_dependencies_satisfied`，不另立判据

定向唤醒只负责**触发重评**，接受态集合与读取口径完全交给既有 `_dependencies_satisfied()`。这样接受态集合如需调整（例如未来引入新的终态），单点变更即可，不会出现「闸门说满足、唤醒说不够」的双口径漂移。

### D3：唤醒走既有派发入口，天然继承全部闸门与幂等

dependent 的重评通过后，派发 MUST 走与 `spec_ready` 事件同源的入口（`PMEngine.handle_event("spec_ready", ...)` 或其内部等价的入队路径），而不是直接调 `_enqueue`。这样预算闸门、内容完整性闸门、冻结态、`_pending_dispatches`/`_last_dispatch_at` 冷却与去重全部自动生效——**幂等性不需要在唤醒路径上重新实现一遍**。

### D4：观察项通过条件按声明意图收紧，并补上派发动作

`check_recovery_watch()` 的通过判据从「status != 登记时 status」改为：

- **已恢复推进**：status 已进入 `ready` 之后的后续态（`implemented`/`testing`/`verified`/`done`/`pushed`），或已有活跃派发 → 关闭观察项、不告警（既有行为）。
- **尚未恢复推进**：status 为 `ready` 且无活跃派发（含「登记时 implementing、窗口内回退 ready」）→ **就地重新派发**；派发成立 → 关闭观察项、不告警；派发未成立（被预算/内容完整性/依赖闸门拦下，或存在活跃派发）→ 关闭观察项 + `dispatch_stalled` 信号（既有兜底分支）。

**理由**：原文声明的语义本就是「已被派发或进入后续状态」，实现比声明宽松是缺陷而非设计；收紧后既修掉了静默关闭，也把「就地派发」放在告警之前——能自愈的不升级人工。

### D5：不在 `EventBus` 里直接调用派发，经 `PMEngine` 门面

`EventBus` 只负责**识别事实**（某 SPEC 转入接受态），派发决策与闸门求值全部留在 `PMEngine`。保持既有分层：`EventBus` 不持有调度策略，`PMEngine` 不感知 STATE.md 的轮询细节。异常一律在 `EventBus` 侧捕获降级为 WARNING，不得使整轮扫描或事件派发中断（沿用 `full-scan-resilience` 已确立的单条隔离口径）。

## Risks / Trade-offs

- **风险：唤醒放大 recovery 副作用**。定向唤醒只做「重评依赖 + 入队」，不经过 `_recover_one` 的孤儿恢复/状态回退分支，副作用面小于全量扫描。缓解：D3 要求走既有派发入口，全部闸门生效；新增路径的派发次数上界 = 接受态转换次数 × dependents 数，规模可控。
- **风险：观察项通过条件收紧后误升级**。若某 SPEC 在窗口内确实已被派发但派发记录尚未落地，收紧后可能被判为「尚未恢复推进」。缓解：通过条件包含「已有活跃派发」（查 `worktree_manager.has_active_worktree`），且就地派发本身有去重/冷却（D3），不会重复起 run；判为未恢复时的兜底仍是既有 `dispatch_stalled` → Administrator，不是静默丢弃。
- **取舍：不做反查索引**。百量级 SPEC 下遍历 `depends_on` 的成本可忽略（复用已读入的字典，纯内存）；换来的是没有索引失效面。若未来 SPEC 数进入千量级，再引入索引并在本次留下的 Requirement 语义下优化实现，不需要改 spec。
- **取舍：不缩短 `poll_interval_minutes`**。缩短确实能减小空隙，但会成比例放大 `_recover_one` 的副作用（已有 9 轮/小时实证）。本次选择补事件源而非提频——治本且不放大副作用面。
