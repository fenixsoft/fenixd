## Context

`start_after`（定时拾取）是 `add-spec-scheduling-controls` 引入的能力，其门控谓词
`start_after_pending(entry)`（`core/state_machine.py:104`）语义为：晚于当前时刻（或哨兵
`manual`）返回 True = 未到期、应跳过。

**门控现有覆盖（读码核对，2026-09-18）**：

| 入口 | 文件:行 | 有 `start_after` 门？ |
|------|---------|----------------------|
| ready 派发 `_on_spec_ready` | `core/pm_engine/engine.py:552` | ✅ 有 |
| ready 恢复 `_recover_ready` | `core/event_bus.py:277` | ✅ 有 |
| 孤儿 ready 精触发 | `core/event_bus.py:384-390`（`_cancelled_hold` / 退避早退） | ✅ 有（下游 `_recover_ready`） |
| 假就绪巡检豁免 | `core/pm_engine/engine.py:2538` | ✅ 有 |
| **drafted 晋升 `_on_spec_drafted`** | `core/pm_engine/engine.py:342` | ❌ **无** |
| **reviewing 评审 `_on_spec_reviewing`** | `core/pm_engine/engine.py:428` | ❌ **无** |
| **恢复 drafted 分支** | `core/event_bus.py:149-151` | ❌ **无** |
| **恢复 reviewing 分支** | `core/event_bus.py:152-156` | ❌ **无** |

**触发路径（为何泄漏）**：`_on_spec_drafted` 被四条通道调用——① `_dispatch_changes`
扫描新 SPEC / 状态变化（`core/event_bus.py:557`，daemon 在线时注册新 SPEC 走这条）；
② `_recover_one` 恢复分支；③ `check_scheduling_deadlines` 到期唤起（`engine.py:677`）；
④ `_check_scheduling_kick_requests` 清空/激活后唤起（`.fenix/fenixd.py:1158`）。通道 ①②
无门 → 未到期的 `drafted` SPEC 立即被晋升。通道 ③④ 是**有意放行**（到期/人工触发），
必须继续放行。

**实证（2026-09-18）**：`add-project-detail-tabs`（`start_after`=本地 09-19 00:00）
在 daemon 23:17 启动后首个扫描周期（23:18）经 `_recover_one` drafted 分支 → `_on_spec_drafted`
被提前 42 分钟晋升 → 起评审 run。

**为何守 `drafted`/`reviewing` 分支就够**：门控是**实时评估**的——SPEC 停在 `drafted`
未到期期间不晋升；到期后由 `check_scheduling_deadlines`（60s）或 full_scan 走通道 ③ 正常
晋升。因此不需要新增定时器，也不需要改动 `check_scheduling_deadlines` 的现有分支
（它显式检查 `start_after_pending(entry, now)` 已是放行侧）。

## Goals

- 任何**自动**晋升/评审入口在 `start_after` 未到期（含 `manual` 哨兵）时都跳过，不产生
  状态突变与 run。
- 到期 / 清空 / 手工激活后的正常放行路径**零影响**。
- 恢复路径与 `_recover_ready` 用**同一谓词、同一口径**，不新写第二份判据。
- 无 `start_after`（null）的存量 SPEC 行为**完全不变**。

## Decisions

### D1：门加在 handler 入口（`_on_spec_drafted` / `_on_spec_reviewing`），而非只加在恢复分支

**决策**：在两个 handler 方法体开头加 `start_after_pending(entry)` 守卫，`_recover_one`
的 drafted/reviewing 分支同步加早退日志。

**理由**：

- handler 入口是**所有自动通道的汇聚点**。若只补 `_recover_one`，则 daemon 在线时
  `/fenix-new --start-after` 注册新 SPEC 走 `_dispatch_changes` → `_on_spec_drafted`
  仍会偷跑（正是本 SPEC「全路径」要求覆盖的第二种形态）。
- 与 `_on_spec_ready`（`engine.py:552`）的既有守卫位置对齐——同一层、同一语义，
  维护者读一处即懂三处。
- **不破坏有意放行**：`check_scheduling_deadlines`（通道 ③）与 `_check_scheduling_kick_requests`
  （通道 ④）在调用 `_on_spec_drafted` 前已确认到期/激活——到期后守卫 `start_after_pending`
  自然返回 False，正常放行。清空/激活把 `start_after` 置 null 后守卫同样放行。二者无需特判。

**替代方案（否决）**：只在 `_recover_one` 加门。否决理由=覆盖面不足，漏掉扫描注册路径。

### D2：守卫必须重读 STATE 取 entry，不用调用方传入的 entry

**决策**：`_on_spec_drafted` / `_on_spec_reviewing` 内部 `self.state_machine.read_one(spec_name)`
取最新 entry 再判定，而非依赖调用方传入的 `entry`。

**理由**：`handle_event("spec_drafted", name, entry)` 传入的 entry 可能是恢复扫描的
快照（读于本轮扫描开始时）。判定必须用**当前** STATE——否则同轮内已被清空/激活的
SPEC 可能被陈旧快照误判为「未到期」而跳过（或反之）。`_on_spec_ready` 既有实现同样
在方法内 `read_one`（`engine.py:540`），保持一致。

### D3：`manual` 哨兵纳入同一守卫（不另建判据）

**决策**：不区分时间值与哨兵，统一用 `start_after_pending`——它已内建哨兵分派
（`state_machine.py:121`，返回 True=永远 pending）。

**理由**：哨兵语义 = 「永不到期、待人工激活」，与「未到期」在守卫处行为完全一致（都
跳过）。复用谓词 = 零新增分支、零漂移。附带修正：`manual` SPEC 此前会被晋升出 `drafted`
（虽在派发口被拦、不误跑），今后稳定停在 `drafted`，语义正确。

### D4：判定异常 fail-open（不早退）

**决策**：守卫包 try/except，异常时记日志并**继续**走既有晋升/评审逻辑。

**理由**：与 `_recover_ready` 既有 `start_after` 早退的 fail-open 设计一致
（`event_bus.py:281`）——新闸门 MUST NOT 吞掉既有能力。`start_after_pending` 本身
对脏值已 fail-open（`parse_utc` 返回 None → 不阻塞），双重保底。

### D5：早退 MUST 零 STATE 写入、无「re-triggering」噪音日志

**决策**：跳过时不写 STATE、不记 `info` 级「re-triggering promote」日志（恢复分支只在
守卫放行后才打该日志），至多记 `debug`。

**理由**：对齐 `_recover_ready` 的既定约定（`event_bus.py:270-281` 注释：未到期直接跳过，
避免每 30 分钟噪音）。否则每个定时 SPEC 会在每轮扫描/60s 精触发产生一条噪音日志。

## Risks

| 风险 | 缓解 |
|------|------|
| 守卫误拦已到期 SPEC，导致到期后不晋升 | 守卫只调 `start_after_pending`（实时评估）；到期后同函数返回 False。补「已到期正常放行」回归用例。 |
| 通道 ③④（有意放行）被守卫挡住 | 单测覆盖：模拟 `start_after` 已过期的 drafted SPEC，验证 `check_scheduling_deadlines` 与 kick 信号仍能晋升。 |
| 恢复路径与派发路径判据漂移 | D1 复用同一谓词；补用例断言两处对同一 entry 结论一致。 |
| 存量 ready SPEC 受影响 | `_on_spec_ready` 守卫不变；本改动不动 ready 链路。 |

## Non-Goals

- 不改 `check_scheduling_deadlines` / kick 信号的到期放行逻辑（它们已是正确的放行侧）。
- 不为 `drafted`/`reviewing` 新增定时到期定时器（现 60s 检查已覆盖）。
- 不改 `start_after` 的数据模型、Dashboard UI、CLI。
