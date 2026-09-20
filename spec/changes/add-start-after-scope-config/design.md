## Context

`start_after`（定时拾取）门控的覆盖范围在两天内变动了两次，两次都是**有意**的，但只能
二选一、无法按项目偏好选择：

| 阶段 | 覆盖范围 | 规则来源 | 现象 |
|------|----------|----------|------|
| 旧行为 | 仅**实现派发**口 | `add-spec-scheduling-controls`（2026-09-12） | 定时/`manual` SPEC 立即晋升、立即跑方案评审；只在派发实现时等到期 |
| 新行为 | 同时覆盖**晋升 + 评审**入口 | `fix-start-after-premature-pickup`（2026-09-18） | 定时/`manual` SPEC 停留 `drafted`，到期/激活才晋升并评审 |

**当前门控点（读码核对，2026-09-20）**：

| 入口 | 文件:行 | 类别 | 当前行为 |
|------|---------|------|----------|
| 派发候选筛选 | `core/pm_engine/dispatch/queue.py:370,:473` | 实现派发 | 无条件跳过 |
| ready 派发 `_on_spec_ready` | `core/pm_engine/engine.py:731` | 实现派发 | 无条件跳过 |
| ready 恢复 `_recover_ready` | `core/event_bus.py:444` | 实现派发 | 无条件跳过 |
| 假就绪巡检豁免 | `core/pm_engine/engine.py:2902` | 实现派发（观测） | 无条件跳过 |
| 孤儿探测豁免 | `core/admin_monitor.py:596` | 实现派发（观测） | 无条件跳过 |
| **drafted 晋升 `_on_spec_drafted`** | `core/pm_engine/engine.py:465` | 晋升 | 无条件跳过（本 SPEC 改为受 scope 约束） |
| **reviewing 评审 `_on_spec_reviewing`** | `core/pm_engine/engine.py:582` | 评审 | 无条件跳过（本 SPEC 改为受 scope 约束） |
| **恢复 drafted 分支** | `core/event_bus.py:224` | 晋升 | 无条件跳过（同上） |
| **恢复 reviewing 分支** | `core/event_bus.py:246` | 评审 | 无条件跳过（同上） |

**新键的语义边界**：`start_after_scope` 只控制「是否**提前**晋升/评审」，不控制「是否到点
才实现」——后者是 `start_after` 的无条件本职，由实现派发口（上表前五行）恒久守住。

## Goals

- 用一个配置键 `gates.start_after_scope`（枚举 `full`/`dispatch`）在两档行为间切换，缺省
  `dispatch`（旧行为），用户可显式设 `full` 拿回 `fix-start-after-premature-pickup` 的守持行为。
- 该键同时作用于定时值与 `manual` 哨兵，且**恒不削弱**「哨兵不自动实现」的保证。
- 零迁移：不写该键的项目行为回到旧行为（立即晋升/评审），语义可预期；键纳入受管白名单，
  设置页「审批」页签可控，热更新生效。

## Decisions

### D1：新键 `gates.start_after_scope`，缺省 `dispatch`

**决策**：新增 `gates.start_after_scope`，取值 `full` / `dispatch`，缺省 `dispatch`。

**理由**：
- 与既有 `gates.*` 三键（`approve_mode` / `promote_mode` / `spec_review_mode`）同段同居，
  复核、同步（`_SYNC_PAGE_KEYS['approval']`）、校验都走既有通道，改动面最小。
- 值语义面向**用户理解**而非内部实现：`dispatch` = 「只约束派发」（旧行为）；`full` =
  「全门约束」（新行为）。避免 `promote`/`review` 之类的内部术语。
- 缺省 `dispatch` 是用户在本 SPEC 中明确选定的档位——「提前跑方案评审、到期才实现」是
  多数项目的节奏诉求；需要守持的项目显式设 `full` 即可。

**替代方案**：布尔键 `gates.start_after_gates_promotion: true/false`。否决——与既有三键
「枚举而非布尔」的既定风格一致（design 先例见 `VALID_BUG_REPAIR_MODES` 注释：「枚举而非
布尔，为未来第三种修复策略留扩展位」）。

### D2：谓词分层——`start_after_pending` 保持无条件，新增组合谓词

**决策**：
- `core/state_machine.py` 的 `start_after_pending(entry)` **保持不变**（无 config 参数），
  仍是「未到期或哨兵」的纯判定；
- 新增模块级函数 `start_after_blocks_promotion(entry, config=None) -> bool`，
  实现为 `start_after_pending(entry) and ConfigLoader.get_start_after_scope(config) == "full"`。
  谓词本身**不吞异常**（纯组合、无 try/except）：fail-open 由四处调用点既有的
  try/except + warning 原样承担，与本 SPEC 之前的行为一致（理由见 D3）。

**理由**：
- `start_after_pending` 有 6 个调用点（`admin_monitor.py:596`、`event_bus.py:224/:246/:444`、
  `engine.py:465/:582/:731/:2902`、`queue.py:370/:473`、`repair_lane.py` 注释），其中**实现
  派发口必须继续无条件调用**。若给 `start_after_pending` 加 config 参数，实现派发口的调用点
  全部要传一个「忽略 scope」的标志，反而更易误用。
- 组合谓词只在**晋升/评审**的 4 个调用点替换（`engine.py:465`、`engine.py:582`、
  `event_bus.py:224`、`event_bus.py:246`），其余调用点一行不动。语义边界在函数名上自明。
- 新谓词入参 `config=None`：缺省即 `dispatch`（不阻塞），与存量调用点零改动的兜底一致。

**替代方案**：在 `_on_spec_drafted` 内直接写 `if scope == "full" and start_after_pending(...)`。
否决——4 处重复判定逻辑，且 scope 判定会各写一份（字符串常量散落四处）；单点谓词杜绝漂移
（fail-open 本身仍由四处调用点各自的 try/except 承担，见 D3）。

### D3：fail-open 语义由四处调用点承担，新谓词**不吞异常**

**决策**：原 4 个调用点各自的 `try/except ... fail-open + warning` **原样保留且是唯一收口处**；
新谓词 `start_after_blocks_promotion` 内部**不写 try/except**，异常正常向上传播到调用点。

**理由（实测证据）**：
- 若谓词内部吞掉异常（原稿方案），调用点的 `except` 分支将**永不进入**——
  `tests/test_start_after_gate.py:438/456/477` 三条 fail-open 用例断言
  `logger.warning` 含「start_after 门控判定异常」，实测（monkeypatch
  `start_after_pending` 抛异常 + 谓词内 try/except）该 warning 不可达，三例必失败。
- 语义不变：调用点 fail-open 即「不阻塞 = 放行」，与谓词返回 `False` 等价；
  异常穿透到调用点后行为与改动前逐字节一致，且保住「判定异常须留痕」的既有契约。
- 谓词保持为两条件的纯组合，无分支、无日志依赖（谓词内不持 logger），单点可测。

### D4：`manual` 哨兵同受 scope 约束（用户选定）

**决策**：`dispatch` 档下，`manual` 哨兵 SPEC 也立即晋升并（按评审判定）起评审，评审通过
后停在 `ready`，由实现派发口的无条件门拦住不实现，直到人工激活。

**理由与保证**：
- 用户明确选择「定时与 manual 统一」（本 SPEC 澄清阶段确认）。
- **哨兵「不自动实现」的保证恒成立**：实现派发口的 `start_after_pending` 无条件，因此
  `ready + manual` 恒不派发（`queue.py:370/:473`、`engine.py:731` 均跳过）。
- 付出的代价：`manual` 哨兵在 `dispatch` 档下会**提前**消耗一次方案评审。这是有意取舍——
  用户既然选择「提前评审」的节奏，对待激活 SPEC 同样希望提前拿到评审结论。
- `add-spec-manual-activation` 声明的「只拦派发、不拦晋升」在此重新生效（`dispatch` 档）；
  `docs/help/06-governance.md` 已如实记载该表述，本 SPEC 的文档任务据此按 scope 补注。

### D5：复用既有受管键通道，不新增机械

**决策**：`gates.start_after_scope` 走 `gates.promote_mode` / `gates.spec_review_mode` 的
同一套六处改动（`_SOURCE_KEYS` 来源标注 → `read_config` 回显 → `read_effective_config`
生效值回显 → `_deep_merge_managed` 合并分支 → `write_config` 前置校验 → `_SYNC_PAGE_KEYS`
同步白名单），前端在 `ApprovalModePanel` 加一个 `Radio.Group`。

**理由**：既有两键的每一处都有明确的历史教训注释（「缺合并分支会被静默丢弃」），照抄最稳。
前端 MUST `npm run build` 重出 `dist`（`per-agent-timeout-override` / `add-impl-code-review-tuning`
先例）。

### D6：不动实现派发口，也不动 `check_scheduling_deadlines` 的放行语义

**决策**：`check_scheduling_deadlines`（`engine.py:1023`）与 kick 信号通道保持原样——它们
是「到期后的接力放行」通道，在 `dispatch` 档下不会被触发到（SPEC 早已晋升 ready），在
`full` 档下照常接力。

**理由**：`check_scheduling_deadlines` 在调 handler 前已确认到期（`start_after_pending` 返回
False），后续 handler 内的 scope 守卫恒放行，无需特判（与 `fix-start-after-premature-pickup`
D1 通道 ③④ 的既有结论一致）。

## Risks

| 风险 | 缓解 |
|------|------|
| 缺省改为 `dispatch` 让 `fix-start-after-premature-pickup` 的实证问题（提前 42 分钟拾取）复现 | 实证场景的根因是 **`start_after` 本意即「到点才实现」**——`dispatch` 档下该 SPEC 的**实现**仍等到点，评审提前是有意的（用户已确认）。需要完全守持的项目设 `full` |
| `dispatch` 档下 `manual` 哨兵被提前评审，产生一次预期外的评审消耗 | 用户已明确选择该语义；文档（`06-governance.md`）明确写出并给出切回 `full` 的指引 |
| 新键被写入而 daemon 读的是旧代码（`daemon stale code` 前科） | 键经 ConfigLoader 单点 getter 读取，热更新 30s 生效；`full` 档不生效时表现是「提前晋升」，可观测（日志有 promote 记录） |
| 四处调用点漏改其一，导致两档行为不一致 | tasks 列 4 处逐点任务；测试对每个门控点覆盖两档，缺一即失败 |
| 前端改了源码忘 `npm run build` | tasks 显式列 build 任务（先例：`fix-mobile-touch-disclosure` / `add-test-regression-tab`） |
| `manual` 哨兵在 `dispatch` 档下经评审否决被自动复评，绕过 `_on_spec_reviewing` | 该通道本就**不在**定时门覆盖范围（`fix-start-after-premature-pickup` 显式登记的边界），本 SPEC 不改变该结论 |

## Migration Plan

- **无迁移**：不写 `gates.start_after_scope` 的存量项目，getter 返回 `dispatch` = 行为回到
  `fix-start-after-premature-pickup` **之前**。这是**有意的行为回退**（用户选择）。
- **需要守持行为的项目**（如依赖「定时 SPEC 停在 drafted 不提前评审」）：显式在项目级或
  用户级 `.fenix/config.yaml` 写 `gates.start_after_scope: full`。
- **测试基线**：`tests/test_start_after_gate.py`（23 用例）当前断言的是 `full` 档行为，需
  在 setUp 的 `_auto_config()` 中加入 `start_after_scope: "full"` 以保持断言成立，并**新增**
  `dispatch` 档用例。既有断言不容许被静默改写（tasks 显式列该调整）。

  **必须同步补 scope 的点位（实测核对，2026-09-20；漏一处即既有用例转红）**：该文件共
  10 处构造点（`_make_engine(..., _auto_config())` 6 处、`_make_engine(..., {})` 4 处、
  `EventBus(..., {}, ...)` 2 处），另有 1 处**文件外**：

  | 位置 | 现状 | 新缺省档下的实际行为（实测） | 处置 |
  |------|------|------------------------------|------|
  | `_auto_config()` | 无 scope | 等同 dispatch | 加 `start_after_scope: "full"`（覆盖 6 处） |
  | 同文件 4 处 `_make_engine(..., {})`（`:204` / `:222` / `:235` / `:464`） | 无 gates 段 | 等同 dispatch | 逐处改传 `_auto_config()`（**MUST NOT** 只改 `_auto_config()` 就以为覆盖全） |
  | 同文件 2 处 `EventBus(..., {}, ...)`（`:261` / `:488`） | 无 gates 段 | 等同 dispatch | 逐处传 `_auto_config()`（`_recover_one` 早退用例依赖 full 档） |
  | `tests/test_spec_review_async_dispatch.py:90-105` `test_start_after_blocks_enqueue` | `_make_engine` 传 `{}`（`:45`） | **实测：`dispatch` 档下该用例转红**（入队 1 条，断言 0 条） | 该用例的 `_make_engine` 传 `{"gates": {"start_after_scope": "full"}}`，**或**在 tasks 5.5 的回归清单显式登记为「缺省档变更的预期差异」并按其语义改写 |

  `python3 -m pytest tests/test_spec_review_async_dispatch.py` 已作为基线跑通（36 例全绿），
  可用作改动后的对照。

## Open Questions

（无——两档语义、缺省值、哨兵范围均已在立项澄清中与用户确认。）
