## Why

2026-09-12 验证环境阻塞事故的善后复盘中实测到一个调度缺口：**已经具备执行条件、且并发槽位空闲的 SPEC，最坏要等满 30 分钟才被拾取**。当天两次实证：

- `fix-root-init-import-shadow`：11:03:02 恢复闭环复查判定「已恢复推进」并**静默关闭观察项**，直到 11:28:02 的周期全量扫描才被派发——**空等 25 分钟**。
- `add-stale-code-selfheal`：11:22:04 其依赖 `fix-supervisor-hosting-chain` 转为 `pushed`（依赖闸门接受态），同样等到 11:28:02——**空等 6 分钟**。

两者的共同结构是：**这两个 SPEC 都没有「能唤醒自己」的事件源**。

- `EventBus._dispatch_changes()`（core/event_bus.py）只在**某个 SPEC 自身 status 发生变化**时才为它产生事件。依赖满足是**别的 SPEC** 的状态变化，观察项通过是**主循环定时器**的产物——都不会为等待中的 SPEC 产生事件。
- `PMEngine._dependencies_satisfied()`（core/pm_engine/engine.py:1901）只在**该 SPEC 正在被派发时**求值；依赖不满足即 `Skipping '<spec>': dependencies not satisfied` 并从队列丢弃，此后无人重新求值。
- `RecoveryWatch.check_recovery_watch()`（core/pm_engine/recovery.py:101）的「通过」分支只记一条 INFO 日志并关闭观察项，**不派发**。

而 `full_scan()` 只有三个触发源：daemon 启动、STATE.md 变化、每 `schedule.poll_interval_minutes`（默认 30）的周期扫描。于是上述两类 SPEC 的等待时间被硬编码为「最坏一个扫描周期」。

代价不只是延迟：等待期间并发槽位闲置（实测当时 `agents.max_concurrent=3` 而只有 2 个 spec agent 在跑），整条 SPEC 链路的墙钟被无谓拉长。

同时，`RecoveryWatch.check_recovery_watch()` 的通过条件存在与既有能力声明不一致之处：`post-recovery-patrol` 的 Scenario 声明通过条件是「该 spec **已离开 ready** 或已有活跃派发」，语义是「已**真实恢复推进**」；而实现判定的是「status 与登记时**不同**」。二者在「登记时是 implementing、窗口内回退到 ready」这一真实形态下分叉——此时按声明意图是**尚未恢复**，按实现却判为通过并静默关闭。事故当天 `fix-root-init-import-shadow` 走的就是这条路径。

## What Changes

- **依赖定向唤醒（新增能力 `dispatch-dependency-wakeup`）**：当某个 SPEC 转入依赖闸门接受态（`done` / `pushed` / `implemented` / `verified`）时，为所有把它声明为 `depends_on` 的等待中 SPEC 补一次重评——满足即入队派发，无需等下一轮全量扫描。重评 MUST 复用既有 `_dependencies_satisfied` 判据，不得另立一套口径。
- **恢复闭环复查通过即派发（修改既有能力 `post-recovery-patrol`）**：把 `check_recovery_watch()` 的通过条件收紧为声明意图——「已真实恢复推进」= 已进入后续状态或已有活跃派发；当一个观察项到期、spec **仍处于 `ready` 且无活跃派发**时，不再静默关闭，而是**就地重新派发**（走与 `spec_ready` 事件同源的派发路径），保留既有的 `dispatch_stalled` 上报分支作为兜底。
- 两条唤醒路径均 MUST 保持在 `EventBus` 既有的事件派发与 `PMEngine` 既有派发队列语义之内：不新增轮询定时器、不缩短全量扫描间隔、不改动优先级/并发/预算闸门。

## Capabilities

### New Capabilities

- `dispatch-dependency-wakeup`: 依赖满足时的定向唤醒——依赖 SPEC 转入接受态后，对等待中的 dependents 补一次重评与入队；含接受态集合口径、重评范围、幂等与去重要求（不重复派发已有活跃派发或在飞派发的 SPEC）。

### Modified Capabilities

- `post-recovery-patrol`: 「每次自动恢复后必须安排闭环复查」这条 Requirement 的通过条件被收紧并补上派发动作——从「status 与登记时不同即关闭且不派发」改为「已真实恢复推进（进入后续状态或已有活跃派发）才关闭；仍滞留 `ready` 且无活跃派发时**就地重新派发**，派发不成再走 `dispatch_stalled` 上报」。

## Impact

- 代码：
  - `core/event_bus.py` — `_dispatch_changes()` 在检出 SPEC 转入依赖接受态时，触发 dependents 重评（新增调用点，不改既有事件映射）
  - `core/pm_engine/engine.py` — `check_recovery_watch` 的派发落地（`_pm.check_recovery_watch` 门面委托）与 dependents 重评入口（复用既有 `_dependencies_satisfied`）
  - `core/pm_engine/recovery.py` — `check_recovery_watch()` 通过分支收紧 + 派发
- 行为：等待中的 SPEC 从「最坏等一个扫描周期（默认 30 分钟）」变为「事件到达即唤醒」；`dispatch_stalled` 信号的触发面不变（本条不是放宽，是把原本静默关闭的一类**正确处置**掉，避免其后来以别的形态升级）
- 不改动：`schedule.poll_interval_minutes` 默认值、`full_scan()` 触发源与语义、优先级/并发/预算闸门、状态机合法转移表
- 测试：`tests/test_pm_recovery.py`、`tests/test_event_bus.py`、`tests/test_run_lifecycle_governance.py` 扩展；用例需覆盖「registered=implementing → 窗口内回退 ready」这一真实事故形态
