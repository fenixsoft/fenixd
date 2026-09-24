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

**自动通道全量核对（2026-09-18，以代码为准；「任何自动入口」的判据即此表）**：进入
`_on_spec_drafted` / `_on_spec_reviewing` 的自动路径共六条——

| # | 通道 | 触发点 |
|---|------|--------|
| ① | full_scan 扫描新 SPEC / 状态变化 | `event_bus.py:557` `_dispatch_changes` → `handle_event` |
| ② | 启动/周期恢复 | `event_bus.py:149-156` `_recover_one` |
| ③ | 60s 到期检测（放行侧） | `engine.py:676` `check_scheduling_deadlines` |
| ④ | 清空/激活 kick 信号（放行侧） | `.fenix/fenixd.py:1157` |
| ⑤ | 框架内部直调（本 SPEC 覆盖面核对结论，2026-09-19 实测） | 真正进入两 handler 的内部直调只有本表 ⑥（`engine.py:392`）。**`core/pm_engine/family.py` 并无任何 `handle_event(...)` 调用**（该文件只调 `_on_spec_ready`，`family.py:657`），原文「family.py 直调 spec_drafted/spec_reviewing」为误记，**已删除** |
| ⑦ | 绕过 handler 入口的框架内部直调（**不在守卫覆盖内**） | `core/pm_engine/spec_review.py:358`（评审否决后的自动复评）与 `:845`（人工 `re_review`）**直接调用 `SpecReviewManager.dispatch_review`**，不经 `_on_spec_reviewing`（`dispatch_review` 的唯一受门调用点是 `engine.py:466`，位于 handler 内）。故该通道**不受本守卫约束**，属本 SPEC 显式登记的边界（理由见 D1「已知取舍」） |

① ② 无门 → 未到期的 `drafted`/`reviewing` SPEC 立即被推进；③ ④ 是**有意放行**，
必须继续放行；⑤ 无此通道（误记已删）；⑥ 与 ① ② 走同一 handler，**同样受 D1 守卫约束**
（对定时 SPEC 是正确行为，理由见 D1「已知取舍」）；⑦ **明确不受门**（边界已登记）；
人工路径不在本表内，见 D1 末条。

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
  维护者读一处即懂三处（含日志级别：既有守卫记 **debug**，本守卫同级别，见 D5）。
- **不破坏有意放行**：`check_scheduling_deadlines`（通道 ③）与 `_check_scheduling_kick_requests`
  （通道 ④）在调用 `_on_spec_drafted` 前已确认到期/激活——到期后守卫 `start_after_pending`
  自然返回 False，正常放行。清空/激活把 `start_after` 置 null 后守卫同样放行。二者无需特判。
- **已知取舍（登记，不扩大改动面）**：除 ①②③④ 外，另有两条**框架内部**的直调路径，
  本决策**只覆盖其中一条**，边界必须如实登记（2026-09-19 逐行核对）：
  - **在覆盖面内**：`engine.py:392` 的 `_on_spec_drafted` → `_on_spec_reviewing` 同步
    直调（进入同一 handler，受守卫约束）。对本 SPEC 的目标（定时 SPEC 不被自动拾取）
    而言这是**正确**行为：未到期的 `drafted`/`reviewing` SPEC 本就不应被任何自动通道
    推进；被延后的推进由 60s 到期检测 / full_scan（通道 ③）在到期后补齐，与「实时
    评估、到期自然放行」的既有语义一致。
  - **在覆盖面外（MUST NOT 声称已覆盖）**：`core/pm_engine/spec_review.py:358`
    （评审否决后的自动复评）与 `:845`（人工 `re_review`）**直接调用
    `SpecReviewManager.dispatch_review`**，不经 `_on_spec_reviewing` 入口，故不受
    本守卫约束。**实证缺口**：一条被评审 `rejected`（且未达既手上限）的 SPEC 会先经
    `spec_review.py:332-336` 被 auto-transition 回 `reviewing`（`channel="auto"`），
    随后 `:358` 无视未来 `start_after` 立即重派评审——评审↔否决复评闭环每轮仅
    ~10 分钟（`add-project-detail-tabs` 实证：15:18:01 派发 → 15:27:55 收口），远快于
    60s 到期检测的兜底，故对这类 SPEC 定时语义仍会被击穿。**本 SPEC 有意不修**：堵住它
    需给 `dispatch_review` 加「调用来源」参数或加第二套判据，与 D1 末条「改动面 MUST
    保持在两个 handler + `_recover_one` 两分支」冲突，且属评审闭环语义（复评是否应受
    定时门约束）需独立决策。**后续 SPEC 应在 `dispatch_review` 侧补门并单列一条
    Requirement**；本 SPEC 只承诺「经两个 handler 进入的通道」全覆盖。改动面 MUST 保持
    在两个 handler + `_recover_one` 两分支，MUST NOT 为此新增调用点参数或第二套判据。
- **人工路径不受影响**（与本决策的分界）：CLI `fenix_cli.py promote`、Dashboard
  「晋升」按钮（`admin_actions.promote_spec`）、CLI `review` / Dashboard「重新评审」
  均**不经** `_on_spec_drafted` / `_on_spec_reviewing`——它们直接调共享函数
  `promote_drafted`（`bin/fenix_cli.py:51`、`core/dashboard/data/admin_actions.py:266`）
  或 `SpecReviewManager.re_review`（→ `dispatch_review`），故未被本守卫拦截。这是
  有意的：`manual` 哨兵 SPEC 的「激活」与人工「晋升」都只清 `start_after`、走人工
  通道，MUST NOT 被定时门挡回（见 tasks 1.5）。

**替代方案（否决）**：只在 `_recover_one` 加门。否决理由=覆盖面不足，漏掉扫描注册路径。

### D2：守卫必须重读 STATE 取 entry，不用调用方传入的 entry

**决策**：`_on_spec_drafted` / `_on_spec_reviewing` 内部 `self.state_machine.read_one(spec_name)`
取最新 entry 再判定，而非依赖调用方传入的 `entry`。

**理由**：`handle_event("spec_drafted", name, entry)` 传入的 entry 可能是恢复扫描的
快照（读于本轮扫描开始时）。判定必须用**当前** STATE——否则同轮内已被清空/激活的
SPEC 可能被陈旧快照误判为「未到期」而跳过（或反之）。`_on_spec_ready` 既有实现同样
在方法内 `read_one`（`engine.py:532` `spec = self.state_machine.read_one(spec_name) or {}`），保持一致。

**落点与「读不到 entry」约定**（两处形态不同，必须分别写明，避免实现歧义）：

- `_on_spec_drafted`（`engine.py:342`）：守卫置于方法体开头，`entry = self.state_machine.read_one(spec_name)`；
  **`entry` 为 None（SPEC 已被删除/归档）时守卫 MUST NOT 早退**，照常走既有链
  （`promote_drafted` 自带 not-found 拒绝并记日志，是既有语义，本守卫不得抢先吞掉）。
- `_on_spec_reviewing`（`engine.py:428`）：本方法**当前不在入口 `read_one`**（首次读盘在
  `engine.py:461`，位于单飞守卫与熔断短路**之后**）。守卫 MUST 插在方法体最前面（早于
  `_review_dispatches` 单飞标记与熔断短路），并**自行** `read_one`；读不到 entry 时
  **跳过守卫判定**（不早退），交由既有链自然处理。守卫 MUST NOT 复用 461 行那次读盘
  （位置不符），MUST NOT 为省一次读盘而挪动 461 行前后顺序。

### D3：`manual` 哨兵纳入同一守卫（不另建判据）

**决策**：不区分时间值与哨兵，统一用 `start_after_pending`——它已内建哨兵分派
（`state_machine.py:121`，返回 True=永远 pending）。

**理由**：哨兵语义 = 「永不到期、待人工激活」，与「未到期」在守卫处行为完全一致（都
跳过）。复用谓词 = 零新增分支、零漂移。附带修正：`manual` SPEC 此前会被晋升出 `drafted`
（且同 D1/§Why：分流命中评审时会**真实派发评审 run**，不只是在派发口被拦），今后稳定
停在 `drafted`，语义正确。

### D4：判定异常 fail-open（不早退）

**决策**：守卫包 try/except，异常时记日志并**继续**走既有晋升/评审逻辑。

**理由**：与 `_recover_ready` 既有 `start_after` 早退的 fail-open 设计一致
（`event_bus.py:281`）——新闸门 MUST NOT 吞掉既有能力。`start_after_pending` 本身
对脏值已 fail-open（`parse_utc` 返回 None → 不阻塞），双重保底。

### D5：早退零 STATE 写入、日志级别对齐既有守卫（debug）

**决策**：跳过时不写 STATE、不打 `info` 级日志，统一记 **`debug`**，措辞对齐既有守卫。

- `_on_spec_drafted` / `_on_spec_reviewing`：措辞与级别对齐 `_on_spec_ready` 既有
  `start_after` 跳过（`engine.py:553-556`：`"Skipping '<spec>': start_after pending (scheduled pickup)"`，
  **debug**）。
- `_recover_one` 的 drafted/reviewing 分支：措辞对齐 `_recover_ready` 既有跳过
  （`event_bus.py:278-281`：`"Recovery: skip '<name>' — start_after scheduled pickup pending"`），
  级别按 D5 的零噪音取向取 **debug**——`_recover_ready` 现为 info（`event_bus.py:279`），
  本 SPEC 不改它（该处已有既存噪音，属独立治理项，登记为非目标）。
- 恢复分支的「Recovery: re-triggering promote」（`event_bus.py:150`，info）MUST NOT 在
  早退时打出——日志语句本身排在守卫之后即可。

**理由**：对齐 `_recover_ready` 早退的既定零噪音约定（`event_bus.py:270-273` 注释：未到期
直接跳过，避免每 30 分钟噪音）。否则每个定时 SPEC 会在每轮 full_scan + 60s 精触发持续
产生 info 噪音（`add-project-detail-tabs` 实证：15:28-15:37 每 60s 一条
`Recovery: skip … start_after scheduled pickup pending`，`.fenix/logs/fenixd.log:41335-41414`）。

## Risks

| 风险 | 缓解 |
|------|------|
| 守卫误拦已到期 SPEC，导致到期后不晋升 | 守卫只调 `start_after_pending`（实时评估）；到期后同函数返回 False。补「已到期正常放行」回归用例。 |
| 通道 ③④（有意放行）被守卫挡住 | 单测覆盖：模拟 `start_after` 已过期的 drafted SPEC，验证 `check_scheduling_deadlines` 与 kick 信号仍能晋升。 |
| 恢复路径与派发路径判据漂移 | D1 复用同一谓词；补用例断言两处对同一 entry 结论一致。 |
| **到期→派发延迟（本改动的真实代价，必须登记）** | 派发门 `_recover_ready`（`event_bus.py:277`）在未到期时**不重触发** `_on_spec_ready`，因此**到期不会由 recovery 接力派发**；到期后 `_on_spec_ready` 的实际调用方只有 ③ `check_scheduling_deadlines`（60s 粒度，`engine.py:676`）与 ④ kick 信号（清空/激活时，`.fenix/fenixd.py:1157`）。故「到期即派发」依赖 60s 检测存活。守卫返回 False 后的语义与 `_on_spec_ready` 既有门**逐字一致**（同谓词、同 fail-open），本改动 MUST NOT 弱化它：把守卫写成「到期后主动补派」会凭空创造第二条派发路径。补用例：`check_scheduling_deadlines` 在到期时分流 `drafted → _on_spec_drafted` 且经守卫放行。 |
| 存量 `ready` SPEC 受影响 | `_on_spec_ready` 守卫不变；本改动不动 ready 链路（`_recover_ready` 亦不改）。 |

## Non-Goals

- 不改 `check_scheduling_deadlines` / kick 信号的到期放行逻辑（它们已是正确的放行侧）。
- 不为 `drafted`/`reviewing` 新增定时到期定时器（现 60s 检查已覆盖）。**到期→晋升/派发的
  延迟上界由此固定为 ≤ 一个 60s 检测周期**（验证/文档口径以此为准，勿写成「即时」）。
- 不改 `start_after` 的数据模型、Dashboard UI、CLI。
- 不给 D1 表 ⑤/⑥ 的内部直调点加参数区分来源（它们是自动链的一部分，对齐 D1「已知取舍」）。
- 不动 `_recover_ready`（`event_bus.py:279`）既有的 info 级跳过日志——它已是既存噪音
  （`add-project-detail-tabs` 每 60s 一条），属独立治理项，本 SPEC 不顺带改。
