## Context

`start_after` 清空（Dashboard「设置拾取时间」清除 / 激活哨兵 SPEC）走的是
**文件信号 + 隐含消费者**模式：写侧落一个信号文件，daemon 主循环轮询消费。

该模式在本仓有一族同构实现，均为**单槽位**：

| 信号 | 路径常量 | 写入方 | 冲突行为 |
|---|---|---|---|
| admin invoke | `.fenix/admin_invoke_request.json` | `core/signals.py` | 返回 conflict |
| run cancel | `.fenix/cancel_run_request.json` | `admin_actions.py` | 返回 conflict |
| approve push | `.fenix/approve_push_request.json` | `admin_actions.py` | 返回 conflict |
| **scheduling kick** | `.fenix/scheduling_kick_request.json` | `admin_actions.py` | **返回 conflict 且被调用方丢弃** |

前三者的调用方都把 `conflict` 变成**显式拒绝**（HTTP 409），所以「单槽位」是可接受
的设计——用户看到失败会重试。**只有 scheduling kick 不同**：调用方丢弃返回值、
接口返回成功、前端宣称「立即恢复调度」，把「静默丢弃」伪装成了成功。

本次故障正是这一差异的后果。已有记忆 `fenixd-file-signal-consumer-gap` 记录的同族
缺陷（`approve_push_request.json` 单槽位滞留锁死后续推送）证明该模式的风险是
**已知且反复发生时**的。

**约束**：

- 消费侧 `_check_scheduling_kick_requests` 定义在根 `fenixd.py`（不在 `core/` 包内），
  无法作为共享模块被 dashboard 侧 import——写入逻辑须落在**中性模块**（对齐
  `core/signals.py` 既有的「消除 pm_engine → dashboard.data 反向 import」搬迁先例）。
- `.fenix/scheduling_kick_request.json` 是**运行时文件**（`.fenix/*` 被 gitignore），
  不属于本仓库交付物；改动它的路径形态不涉及仓库内文件迁移。
- 前端 `dist/` 为构建产物，声明为 `reference`，由框架按既有流程重建。

## Goals / Non-Goals

**Goals:**

- 消除「不同 SPEC 的清空/激活信号互相顶掉」——同一时间窗内任意数量的 SPEC 清空
  定时，每个都必须被即时唤醒。
- 消除「假成功」——信号写入失败时，接口/前端如实告知，不再宣称「立即恢复调度」。
- 消除「陈旧信号永久占槽」——无人消费的信号不再让后续唤醒全部失效。
- 兼容存量项目上残留的旧单槽位文件，不要求人工清理。

**Non-Goals:**

- **不动**实现派发口的 `start_after` 门控语义（`_on_spec_ready` / `_recover_ready` /
  派发队列筛选）——那是 `start_after` 的本职，与本次并发缺陷正交。
- **不动**其余三个信号（admin invoke / run cancel / approve push）的单槽位语义——
  它们的调用方已把冲突变成显式 409 拒绝，行为正确；若也要改多槽位，属独立决策。
- **不引入**信号消费确认（回执）机制——「写侧写成功但消费失败」的跨进程确认需要
  新一轮状态设计（记忆 `fenixd-file-signal-consumer-gap` Gap D 登记在案），本次
  以「幂等重放 + 周期兜底」缓解，不做完整确认协议。
- **不改** `check_scheduling_deadlines` 的 60s 周期与 full_scan 的 30 分钟兜底——
  它们是信号丢失时的既有保险，本 SPEC 只让信号不再轻易丢失。

## Decisions

### D1. 信号载体：每 SPEC 一文件（`.fenix/scheduling_kick/<spec>.json`）

**选定**：目录 + 每 SPEC 一个文件，文件名即 SPEC 名。

**理由**：
- 直接消除跨 SPEC 互斥——不同 SPEC 写不同文件，无共享槽位即无冲突。
- 同一 SPEC 重复清空天然幂等（同路径覆盖，语义一致：都是「唤醒该 SPEC」）。
- 目录扫描与逐条删除的消费逻辑与现有单文件版本**同构**（读→删→唤起），
  改动面小、易测。

**替代方案（否决）**：
- *append 型队列（单文件多行/JSON Lines）*：并发追加需额外的锁与部分读防护；
  且无法对「同一 SPEC 的重复唤醒」去重。收益不抵复杂度。
- *保留单文件 + 冲突时轮询重试*：写侧在 HTTP 请求线程里等消费位不可接受；
  改为落盘重试则又绕回「谁来保证最终写出」，仍需目录语义。
- *保留单文件 + 冲突时覆盖*：会丢掉先写入者的唤醒——把静默丢弃变成静默吞掉
  另一个 SPEC 的唤醒，更糟。

**SPEC 名合法性**：SPEC 名已被 `fenix_spec.py new` 约束为 kebab-case（`[a-z0-9-]`），
不含路径分隔符，可直接作文件名。写入侧仍 MUST 做一次校验，且判据复用该权威正则
（`core/spec_gen.py:_KEBAB_RE`，`^[a-z][a-z0-9]*(-[a-z0-9]+)*$`）——黑名单式拒绝
（只查空串 / `/` / `\` / `..`）会放过 `.`、前导点、含 `:` 或非 ASCII 等「能当文件名但
不合规」的输入，正则白名单与之等价且无遗漏。

**临时文件命名（与消费侧扫描谓词成对）**：写入用 `mkstemp` + `os.replace`，临时文件
与目标同目录；消费侧按 `.json` 后缀筛选，故临时名 MUST NOT 以 `.json` 结尾
（如 `<spec>.json.tmp.<rand>`）。这条谓词同时消解 D1「每 SPEC 一文件幂等覆盖」与
`os.replace` 的 rename 竞态：`replace` 是「先去旧名 → 后立新名」，两次并发写同一 SPEC
时消费侧可能撞见目标名瞬间不存在——但旧新内容语义同为「唤醒该 SPEC」，故这只是
「唤醒了但与本次写入不可分辨」的极窄窗口，不产生错误语义，**不作为**要求写入侧加锁的理由。

### D2. 写入助手落在 `core/signals.py`

**选定**：在 `core/signals.py` 新增 `SCHEDULING_KICK_DIR` 常量与
`write_scheduling_kick(project_root, spec) -> dict` 函数，`admin_actions.py`
的 `_write_scheduling_kick_signal` 改为委托它。

**理由**：消费方是根 `fenixd.py`。若把定义留在 `core/dashboard/data/admin_actions.py`，
则 daemon 侧要么反向依赖 dashboard 包（分层倒置，正是 `fix-deferred-findings CYC-1`
在消除的模式），要么各自复制一份路径常量（路径漂移风险）。`core/signals.py` 已是
「pm_engine / dashboard.data 共用信号函数的中性模块」，把路径与写入语义放这里，
两端 import 同一个定义，与 `request_admin_invoke` 的搬迁先例完全一致。

**替代方案（否决）**：*新建 `core/scheduling_signal.py`*——单函数单常量不值得新模块，
且 `signals.py` 的既有定位就是「信号函数中性模块」，语义上门当户对。

### D3. 返回值契约：写侧如实回报，API 透传，前端分支文案

**选定**：`write_scheduling_kick` 返回
`{"ok": bool, "file": str|None, "error": str|None}`；
`set_spec_start_after` / `activate_spec` 在返回值中新增
`scheduling_kick: {"ok": bool, "error": str|None}`；
API 响应把该结果透出，失败时附 `warning` 字符串。

**理由**：修复的本质不只是「让信号不再丢失」，还包括「丢了要说」。若只改载体
不改回报，下一个类似缺陷仍会以假成功的形态潜伏。API 层保持 200（`start_after`
确实已成功置 null，请求本身是成功的），但携带 `warning` 字段供前端区分文案。

**文案契约**：
- 信号写出成功 → 「已清除定时，立即恢复调度」/「已激活，立即恢复调度」
- 信号写出失败 → 「已清除定时，但即时唤醒信号写入失败，将由下次扫描（缺省 ≤30 分钟）派发」
  （文案中的周期数取自 `schedule.poll_interval_minutes` 缺省值 30，该键为用户可配置项——
  文案 MUST 措辞为「缺省/默认」而非硬编码承诺；提示意在消除「假成功」，精度不要求随配置动态渲染）

**替代方案（否决）**：*写出失败返回 HTTP 5xx*——`start_after` 已成功置 null，
把整个请求判失败会让前端提示「操作失败」而用户重试时面对的是「已是 null」的
无操作路径，更混乱。状态变更成功 + 附告警是更诚实的表达。

### D4. 陈旧信号回收：启动 + 周期对账

**选定**：daemon 启动清扫与周期计时段（600s，对齐既有 `orphan_clean_ts` 节拍）
对 `.fenix/scheduling_kick/` 目录对账：

- 条目 `created` 在回收阈值内 → **消费**（按既有语义唤起）后删除。唤醒是幂等的
  （既有 handler 内部谓词拦截终态/派发中的 SPEC），重复唤醒无副作用，故「先消费
  再删」比「直接删」更安全——保证不丢唤醒。
- 条目 `created` 早于回收阈值 → 判为陈旧信号，**仅删除不唤醒**（daemon 长期停机后
  的积压不应引发一轮集中派发）。
- 损坏 / 非法 JSON / 缺 `spec` 字段 → 删除（防每轮报错卡死，与既有单文件消费同构）。

**回收阈值**：MUST 为代码常量，值与既有信号时序族同量级（取 1 小时）。理由：daemon
正常运行时消费延迟 ≤ 2s（1s 主循环），超过 1 小时未消费只可能是消费方缺席——此时
「唤醒」已失去即时语义，退化为「下次扫描自然会处理」。MUST NOT 进配置（对齐
`docs/help/06-governance.md` 既有记载「文件监听 2 秒、定时拾取 60 秒 … 均为代码常量」）。

**启动侧调用点**：`_reclaim_stale_scheduling_kicks` 的启动清扫 MUST 排在
`self.event_bus.start()` **之后**（该方法同步完成 STATE 基线快照 `_update_known_state`）、
进入主循环之前。阈值内的条目会被「先消费再删」唤起并写 STATE；早于基线快照的写入会被
随后的首扫 `_dispatch_changes` 当作新变化重放（`fenixd.py` 中 2026-09-07「重启后 15+ pushed
spec 的 commit-push hook 连环触发」事故的注释即为此防线）。

**替代方案（否决）**：*写入侧在写前检查并覆盖/清理陈旧条目*——写入方是短生命周期
的 dashboard HTTP 请求，不该承担「判断另一个进程是否还活着」的职责；且 dashboard
与 daemon 可能不同根部署。以 `created` 时间戳为唯一判据（消费方时钟）更稳。

### D5. 旧路径兼容：消费侧仍认单文件，消费后删除

**选定**：`_check_scheduling_kick_requests` 先扫新目录，再处理旧单文件路径
（存在即按既有逻辑消费并删除）。

**理由**：存量项目主树上可能残留旧文件（现场 `activation-showcase` 有一个，实测写于
2026-09-18T09:13:49Z 且至今未被消费）。让消费侧兼容，迁移成本为零，不需要任何人工步骤
或数据迁移。旧路径**只读不写**：新写入一律走目录，旧文件在下次被消费后自然消失。

**旧路径同样受 D4 阈值约束**：兼容分支 MUST 复用 D4 的 `created` 分档，而非无条件消费。
否则上述 `activation-showcase` 的旧文件（写于 09-18，daemon 恢复时早已超阈值）会在
项目下次启动时触发一轮「唤醒早已过时」的派发——正是 D4 判为陈旧的语义。同一判据同时
适用两条路径，不新增条件分支。

## Risks / Trade-offs

- **[目录条目堆积]** daemon 长期停机期间写入的唤醒信号会一直留在目录里 →
  已由 D4 的启动对账承担：启动时逐条消费/清理，不会无限堆积。运行期每 600s 兜底。
- **[重复唤醒]** 同一 SPEC 反复清空/激活会落同一文件（幂等覆盖）；启动对账的
  「先消费再删」可能在 SPEC 已进入派发后被再唤醒一次 → 既有 handler 内部谓词
  （终态检查 / 在飞 run 检查 / 派发中检查）会幂等拦截，与现状同源，无新风险。
- **[SPEC 名作文件名]** 恶意/异常 SPEC 名可逃逸目录 → D1 已定写入侧校验（复用
  `core/spec_gen.py:_KEBAB_RE` kebab-case 白名单），且 SPEC 注册路径本身已约束为
  kebab-case。
- **[前端文案契约漂移]** 新文案依赖 API 回传的 `warning`，若前端漏改则仍显示旧
  文案（不产生错误，只是不够诚实）→ tasks 中显式覆盖前端改动并加测试断言。
- **[CLI 是第二个「动作方」]** 同一个 `activate_spec` 还有 CLI 入口
  （`bin/fenix_cli.py:cmd_activate`，文案「已激活，立即进入调度」）。D3 的回报契约
  若只落到 API/前端，CLI 会保留同款「假成功」→ tasks 2.5 与 6.9 显式覆盖 CLI
  分支输出与断言。
- **[唤起的额外副作用（非回归）]** 阈值内的新鲜信号可能把 `ready` SPEC 重新走一遍
  `_on_spec_ready → _enqueue → _process_queue`，派发冷却（`DISPATCH_COOLDOWN_SECONDS=10`）
  与队列去重吸收秒级重复，但若该 SPEC 此前因派发锁退避（`_dispatch_backoff_until`）
  而被暂缓，重放会命中同一退避门——退避门在 `_on_spec_ready`/`_process_queue` 内，
  与本次改动同源，不新增绕过路径。
- **[与在飞 SPEC 的修改冲突]** `add-start-after-scope-config` 正在实现，它修改
  `scheduled-spec-pickup` 能力的**另两条** Requirement（「调度器对未到期 SPEC
  跳过拾取」「恢复与扫描路径统一受 start_after 门约束」）。本 SPEC 只改该能力的
  「定时门控为实时评估而非一次性」一条，两条 delta 的 Requirement 名不重叠，
  合并时不会同段冲突。

## Migration Plan

无数据迁移。部署顺序无关紧要（写入侧与消费侧可各自先上）：

1. 写入侧改为新目录 → 旧文件不再新增。
2. 消费侧同时兼容新目录与旧文件 → 存量旧文件在下次被消费后消失（阈值内）或仅被
   清理（超阈值，见 D5 末段）。
3. 陈旧回收随消费侧一起上线。

无需人工步骤。旧文件若长期存在（daemon 从不启动），不影响新路径的正确性。
