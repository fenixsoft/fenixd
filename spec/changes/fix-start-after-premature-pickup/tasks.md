# Tasks: fix-start-after-premature-pickup

## Deliverables

```yaml
- path: core/pm_engine/engine.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: tests/test_start_after_gate.py
  kind: new
```

> 注：修复落在两处汇聚入口——`core/pm_engine/engine.py` 的 `_on_spec_drafted` /
> `_on_spec_reviewing`（handler 入口守卫，覆盖 daemon 在线扫描注册与恢复两条自动通道）
> 与 `core/event_bus.py` 的 `_recover_one` drafted/reviewing 分支（早退，避免噪音日志）。
> 两处复用既有谓词 `start_after_pending`，无新判据。`tests/test_start_after_gate.py`
> 新增回归用例覆盖四条自动通道与三条元放行路径。

## 1. handler 入口守卫（`core/pm_engine/engine.py`）

- [ ] 1.1 在 `_on_spec_drafted`（`core/pm_engine/engine.py:342`）方法体开头新增 `start_after` 门控：`entry = self.state_machine.read_one(spec_name)` 取当前 entry（对齐 `_on_spec_ready` 的 `read_one`，`engine.py:532`），`start_after_pending(entry)` 为真时记 **debug** 日志（措辞对齐 `engine.py:553-556`「start_after pending (scheduled pickup)」）后直接 `return`——不软化、不 lint、不写 error、不 transition、不派发。守卫须置于现有 `promote_mode != auto` 闸口之外（两者独立：manual 晋升模式与定时拾取门互不替代）。**entry 为 None（SPEC 已删除/归档）时 MUST NOT 早退**，照常走既有链（`promote_drafted` 自带 not-found 拒绝与日志，是既有语义，守卫不得抢先吞掉）
- [ ] 1.2 在 `_on_spec_reviewing`（`engine.py:428`）方法体开头（早于 `_review_dispatches` 单飞标记与熔断短路）新增同源 `start_after` 门控：**自行** `read_one` 取 entry（MUST NOT 复用 `engine.py:461` 那次读盘——它位于单飞守卫/熔断之后，位置不符；MUST NOT 为省一次读盘而挪动其前后顺序），未到期/哨兵记 debug 日志后直接 `return`，不派发评审 run；**entry 为 None 时跳过判定**（不早退），交由既有链处理
- [ ] 1.3 两处守卫统一包 try/except：判定异常时记 warning 日志并**继续**走既有逻辑（fail-open，不吞掉既有晋升/评审能力）；`from core.state_machine import start_after_pending` 在方法内局部导入（对齐 `_recover_ready` 既有风格，`event_bus.py:275`）
- [ ] 1.4 核对有意放行通道未被拦截：`check_scheduling_deadlines`（`engine.py` 到期唤起）与 `_check_scheduling_kick_requests`（`.fenix/fenixd.py` 清空/激活唤起）在 `start_after` 到期或置 null/激活后调用 `_on_spec_drafted`，此时 `start_after_pending` 返回 False 正常放行——在守卫代码处补注释说明该放行语义
- [ ] 1.5 **人工放行豁免**：守卫 MUST 只对**自动**通道生效，人工显式操作（CLI `fenix_cli.py promote`、Dashboard「晋升」按钮经 `admin_actions.promote_spec`）MUST 继续对其 `start_after` 未到期的 `drafted` SPEC 放行——人工晋升是主动意图，若被定时门拦截会造成 42 分钟等不到、`/fenix-ready` 操作无反应。实现方式：守卫只加在 `_on_spec_drafted` / `_on_spec_reviewing`（自动通道汇聚点），**MUST NOT** 加在共享函数 `promote_drafted`（人工通道同经此函数）——`promote_drafted` 保持纯粹（软化 + lint + 判定），定时门不下沉到该函数

## 2. 恢复分支早退（`core/event_bus.py`）

- [ ] 2.1 在 `_recover_one` 的 `drafted` 分支（`core/event_bus.py:149-151`，`handle_event("spec_drafted", ...)` 之前、含 `event_bus.py:150` 的「Recovery: re-triggering promote」info 日志之前）新增 `start_after_pending(entry)` 早退：未到期/哨兵时记 **debug** 日志「Recovery: skip '<name>' — start_after scheduled pickup pending（drafted）」（措辞复用 `_recover_ready` 既有串，`event_bus.py:280`）后 `return True`（处理成功，计入 handled），MUST NOT 打「re-triggering promote」日志、MUST NOT 写 STATE。**级别偏离须在代码注释登记**：`_recover_ready` 同类跳过现为 **info**（`event_bus.py:279`），本处取 debug 是为避免每 60s 一条噪音；`_recover_ready` 保持不动（Non-Goals），本 SPEC MUST NOT 顺带改它
- [ ] 2.2 在 `_recover_one` 的 `reviewing` 分支（`event_bus.py:152-156`）同样新增早退，措辞「...（reviewing）」，debug 级，MUST NOT 打「re-triggering spec_reviewing」日志
- [ ] 2.3 两处早退统一包 try/except fail-open（异常时不早退、继续既有恢复路径，记日志）；`from core.state_machine import start_after_pending` 局部导入，与 `_recover_ready`（`event_bus.py:275`）同源同谓词

## 3. 回归测试（`tests/test_start_after_gate.py`）

- [ ] 3.1 新增测试文件，构造带 `start_after` 未来时间 / `manual` 哨兵 / 已过期三态的 STATE 条目 fixture（复用 `tests/test_event_bus.py` 与 `tests/test_spec_scheduling.py` 既有 fixture 构造手法，MUST NOT 触碰用户级配置或真实项目 STATE）
- [ ] 3.2 用例：`_on_spec_drafted` 对 `drafted + 未来 start_after` 的 SPEC 不晋升（status 保持 drafted、无 transition、无 run 派发）；对 `drafted + manual` 同样不晋升；对 `drafted + 已过期` 正常晋升
- [ ] 3.3 用例：`_on_spec_reviewing` 对 `reviewing + 未来 start_after` 不派发评审；对已过期正常派发
- [ ] 3.4 用例：`_recover_one` 对 `drafted`/`reviewing` + 未来 `start_after` 的 SPEC 早退——不产生「re-triggering promote」/「re-triggering spec_reviewing」日志、不写 STATE、返回 handled
- [ ] 3.5 用例：元放行路径——`check_scheduling_deadlines`（`engine.py:676`）对 `drafted + start_after 已过期` **经守卫放行**清空 drafted 条目（断言 status 不再为 drafted）并走 ③ 分支唤起；清空 `start_after`（置 null）后 `_on_spec_drafted` 正常晋升；kick 信号（`.fenix/fenixd.py:1157`）对清空后的 `drafted` SPEC 仍唤起晋升链
- [ ] 3.6 用例：fail-open——monkeypatch `start_after_pending` 抛异常时，`_on_spec_drafted` / `_on_spec_reviewing` / `_recover_one` 仍走既有逻辑（不被新闸门吞掉）
- [ ] 3.7 用例：无 `start_after`（null）的 `drafted` SPEC 行为与改动前一致（正常晋升）——锁定存量 SPEC 零回归；并断言 `entry` 读不到（SPEC 不存在/已归档）时两处守卫均**不早退**（走既有链、不抛异常）
- [ ] 3.8 用例：人工放行豁免——(a) 断言 `promote_drafted` / `dispatch_review` 内**无** `start_after_pending` 调用（静态断言：共享函数未被下沉定时门，守住 spec「门控 MUST NOT 下沉到共享晋升函数」）；(b) 直调 `core.dashboard.data.admin_actions.promote_spec` 与 `bin/fenix_cli.py promote` 路径对 `drafted + 未来 start_after` 的 SPEC 正常晋升（按评审判定分流到 ready 或 reviewing，定时门不拦截）；(c) `SpecReviewManager.re_review` 对 `blocked + 未来 start_after` 的 SPEC 仍可进入 reviewing（人工重评不被定时门拦）
- [ ] 3.9 用例：`_recover_one` 日志级别与措辞——`drafted`/`reviewing` + 未来 `start_after` 时日志中**不出现**「re-triggering promote」/「re-triggering spec_reviewing」（info 级断言），跳过日志为 debug 级
- [ ] 3.10 **能力边界变更登记（不产出代码，收工时写入 verification-report）**：本改动使 `add-spec-manual-activation`（已 pushed）声明的边界发生变化——该 SPEC 的 Non-Goal 原文为「手工激活只拦『ready→派发』，不拦『drafted→ready 晋升』」（`spec/changes/add-spec-manual-activation/proposal.md:33`、`design.md:23`），本 SPEC 后 `drafted + manual` 的 SPEC **不再被扫描/恢复自动晋升**，稳定停在草稿态等激活。须据此复核两点并留痕：
  (a) 激活动作语义**未变**——`activate_spec` 仍无条件写 kick 信号（`core/dashboard/data/admin_actions.py:423-427`），daemon 消费后对 `drafted` 走 `_on_spec_drafted`（`.fenix/fenixd.py:1157`），此时 `start_after` 已为 null → 守卫放行 → 正常晋升（即该 SPEC 的「激活即派发」场景仍成立，冻结场景无需改道；用例见 tasks 3.5）；
  (b) 仅需在 `verification-report.md` 登记上述边界变化（`drafted + manual` 的自动晋升被门拦下属本 SPEC 有意为之），供 `add-spec-manual-activation` 的能力文档后续修订参考

## 4. 验证与预演

- [ ] 4.1 运行相关测试全绿：`python3 -m pytest tests/test_start_after_gate.py tests/test_spec_scheduling.py tests/test_event_bus.py tests/test_pm_promotion_gate.py tests/test_review_circuit_breaker.py tests/test_task_track.py tests/test_deliverable_declaration_premechanize.py -q`
  （后三个文件含**不带 `start_after`** 的 `drafted`/`reviewing` 直调 `_on_spec_drafted` 用例——`tests/test_review_circuit_breaker.py` 断言熔断短路早于派发、`tests/test_task_track.py:278` 与 `tests/test_deliverable_declaration_premechanize.py:345` 断言 `drafted → ready` 晋升：本改动对「无 `start_after`」条目零影响，这三条是这次改动最直接的**零回归**护栏）
- [ ] 4.2 落地复现预演：构造一个 `drafted + 未来 start_after` 的临时 spec 目录（`.history/` 下），以全新 StateMachine 实例（对齐 daemon 冷启动语义）驱动 `_recover_one` 与 `_on_spec_drafted`，断言其状态保持 `drafted` 且无派发；同时以**已过期**的 `start_after` 再跑一遍，断言经 ③ `check_scheduling_deadlines` 正常晋升；清理临时夹具

## 5. 文档口径修正（2026-09-19 评审实测，防「声称已覆盖」误导实现与验证）

> 背景：初稿把「框架内部直调」笼统写成「走同一 handler，同样受 D1 守卫约束」，并把
> `core/pm_engine/family.py` 列为直调通道之一。逐行核对后两处均不成立（`family.py`
> 全文无 `handle_event(...)` 调用；`spec_review.py:358/845` 直调的是 `dispatch_review`，
> **不经** `_on_spec_reviewing`）。已同步修正 design.md / specs/scheduled-spec-pickup/spec.md。

- [ ] 5.1 实现前核对覆盖面边界（按修正后的文档）：门只落在 `_on_spec_drafted` /
  `_on_spec_reviewing` / `_recover_one` 两分支；**MUST NOT** 声称已覆盖
  `dispatch_review` 直调通道（`core/pm_engine/spec_review.py:358` 自动复评、
  `:845` 人工重评），该通道本 SPEC 有意不覆盖
- [ ] 5.2 在 `verification-report.md` 登记未覆盖通道与其实证缺口：被评审 `rejected`
  且未达上限的 SPEC 经 `spec_review.py:332-336` auto-transition 回 `reviewing`
  （`channel="auto"`）后，`:358` 无视未来 `start_after` 立即重派评审（评审闭环每轮
  ~10 分钟，快于 60s 到期检测兜底——`add-project-detail-tabs` 实证 15:18:01 派发 →
  15:27:55 收口）；并注明堵该通道需在 `dispatch_review` 侧加门或加调用来源判据，
  属独立决策，建议后续 SPEC 单列 Requirement 治理
