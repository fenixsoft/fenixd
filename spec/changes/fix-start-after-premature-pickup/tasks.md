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

- [ ] 1.1 在 `_on_spec_drafted` 方法体开头新增 `start_after` 门控：`self.state_machine.read_one(spec_name)` 取当前 entry，`start_after_pending(entry)` 为真时记 info 日志（含 spec 名与「start_after pending」语义）后直接 `return`——不软化、不 lint、不写 error、不 transition、不派发。守卫须置于现有 `promote_mode != auto` 闸口之外（两者独立：manual 晋升模式与定时拾取门互不替代）
- [ ] 1.2 在 `_on_spec_reviewing` 方法体开头（早于 `_review_dispatches` 单飞标记之前）新增同源 `start_after` 门控：未到期/哨兵记 info 日志后直接 `return`，不派发评审 run
- [ ] 1.3 两处守卫统一包 try/except：判定异常时记 warning 日志并**继续**走既有逻辑（fail-open，不吞掉既有晋升/评审能力）；`from core.state_machine import start_after_pending` 在方法内局部导入（对齐 `_recover_ready` 既有风格）
- [ ] 1.4 核对有意放行通道未被拦截：`check_scheduling_deadlines`（`engine.py` 到期唤起）与 `_check_scheduling_kick_requests`（`.fenix/fenixd.py` 清空/激活唤起）在 `start_after` 到期或置 null/激活后调用 `_on_spec_drafted`，此时 `start_after_pending` 返回 False 正常放行——在守卫代码处补注释说明该放行语义
- [ ] 1.5 **人工放行豁免**：守卫 MUST 只对**自动**通道生效，人工显式操作（CLI `fenix_cli.py promote`、Dashboard「晋升」按钮经 `admin_actions.promote_spec`）MUST 继续对其 `start_after` 未到期的 `drafted` SPEC 放行——人工晋升是主动意图，若被定时门拦截会造成 42 分钟等不到、`/fenix-ready` 操作无反应。实现方式：守卫只加在 `_on_spec_drafted` / `_on_spec_reviewing`（自动通道汇聚点），**MUST NOT** 加在共享函数 `promote_drafted`（人工通道同经此函数）——`promote_drafted` 保持纯粹（软化 + lint + 判定），定时门不下沉到该函数

## 2. 恢复分支早退（`core/event_bus.py`）

- [ ] 2.1 在 `_recover_one` 的 `drafted` 分支（`handle_event("spec_drafted", ...)` 之前）新增 `start_after_pending(entry)` 早退：未到期/哨兵时记 info 日志「Recovery: skip '<name>' — start_after scheduled pickup pending（drafted）」（复用 `_recover_ready` 既有措辞风格）后 `return True`（处理成功，计入 handled），MUST NOT 打「re-triggering promote」日志、MUST NOT 写 STATE
- [ ] 2.2 在 `_recover_one` 的 `reviewing` 分支同样新增早退，措辞「...（reviewing）」，MUST NOT 打「re-triggering spec_reviewing」日志
- [ ] 2.3 两处早退统一包 try/except fail-open（异常时不早退、继续既有恢复路径，记日志）；`from core.state_machine import start_after_pending` 局部导入，与 `_recover_ready`（`event_bus.py:275`）同源同谓词

## 3. 回归测试（`tests/test_start_after_gate.py`）

- [ ] 3.1 新增测试文件，构造带 `start_after` 未来时间 / `manual` 哨兵 / 已过期三态的 STATE 条目 fixture（复用 `tests/test_event_bus.py` 与 `tests/test_spec_scheduling.py` 既有 fixture 构造手法，MUST NOT 触碰用户级配置或真实项目 STATE）
- [ ] 3.2 用例：`_on_spec_drafted` 对 `drafted + 未来 start_after` 的 SPEC 不晋升（status 保持 drafted、无 transition、无 run 派发）；对 `drafted + manual` 同样不晋升；对 `drafted + 已过期` 正常晋升
- [ ] 3.3 用例：`_on_spec_reviewing` 对 `reviewing + 未来 start_after` 不派发评审；对已过期正常派发
- [ ] 3.4 用例：`_recover_one` 对 `drafted`/`reviewing` + 未来 `start_after` 的 SPEC 早退——不产生「re-triggering promote」/「re-triggering spec_reviewing」日志、不写 STATE、返回 handled
- [ ] 3.5 用例：元放行路径——`check_scheduling_deadlines` 对 `drafted + start_after 已过期` 正常唤起晋升；清空 `start_after`（置 null）后 `_on_spec_drafted` 正常晋升
- [ ] 3.6 用例：fail-open——monkeypatch `start_after_pending` 抛异常时，`_on_spec_drafted` / `_recover_one` 仍走既有逻辑（不被新闸门吞掉）
- [ ] 3.7 用例：无 `start_after`（null）的 `drafted` SPEC 行为与改动前一致（正常晋升）——锁定存量 SPEC 零回归
- [ ] 3.8 用例：人工放行豁免——直调 `core.dashboard.data.admin_actions.promote_spec`（或 `promote_drafted` 共享函数）对 `drafted + 未来 start_after` 的 SPEC 正常晋升，验证定时门未下沉到共享函数

## 4. 验证与预演

- [ ] 4.1 运行相关测试全绿：`python3 -m pytest tests/test_start_after_gate.py tests/test_spec_scheduling.py tests/test_event_bus.py tests/test_pm_promotion_gate.py -q`
- [ ] 4.2 落地复现预演：构造一个 `drafted + 未来 start_after` 的临时 spec 目录（`.history/` 下），以全新 StateMachine 实例（对齐 daemon 冷启动语义）驱动 `_recover_one` 与 `_on_spec_drafted`，断言其状态保持 `drafted` 且无派发；清理临时夹具
