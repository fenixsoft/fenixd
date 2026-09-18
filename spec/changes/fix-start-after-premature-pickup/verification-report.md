# 验证报告：fix-start-after-premature-pickup

**验证时间**：2026-09-19
**验证引擎**：实现者自验证（单测 + 落地复现预演）
**验证结论**：✅ 实现完成，相关回归全绿

---

## 能力边界变更登记（tasks 3.10）

本改动使 `add-spec-manual-activation`（已 pushed）声明的边界发生变化——该 SPEC 的
Non-Goal 原文为「手工激活只拦『ready→派发』，不拦『drafted→ready 晋升』」
（`spec/changes/add-spec-manual-activation/proposal.md:33`、`design.md:23`）。
本 SPEC 后 `drafted + manual` 的 SPEC **不再被扫描/恢复自动晋升**，稳定停在草稿态
等激活。据此复核两点并留痕：

- **(a) 激活动作语义未变**：`activate_spec` 仍无条件写 kick 信号
  （`core/dashboard/data/admin_actions.py:423-427`），daemon 消费后对 `drafted`
  走 `_on_spec_drafted`（`.fenix/fenixd.py:1157`），此时 `start_after` 已为 null
  → 守卫放行 → 正常晋升（「激活即派发」场景仍成立，冻结场景无需改道；用例见
  tasks 3.5 —— `test_kick_signal_drafted_promotes_after_clear`）。
- **(b) 边界变化**：`drafted + manual` 的自动晋升被门拦下属本 SPEC 有意为之
  （`start_after_pending` 哨兵分派恒返回 True = 永远 pending，D3），供
  `add-spec-manual-activation` 的能力文档后续修订参考。

## 未覆盖通道登记（tasks 5.1/5.2）

**覆盖面边界**：门只落在 `_on_spec_drafted` / `_on_spec_reviewing` / `_recover_one`
两分支（`core/pm_engine/engine.py` + `core/event_bus.py`），以 **handler 入口为界**。
本 SPEC **MUST NOT 声称**已覆盖 `dispatch_review` 直调通道。

**实证缺口（有意不修）**：被评审 `rejected` 且未达既手上限的 SPEC 经
`core/pm_engine/spec_review.py:332-336` auto-transition 回 `reviewing`
（`channel="auto"`）后，`:358` 无视未来 `start_after` 立即重派评审——评审↔否决
复评闭环每轮仅 ~10 分钟（`add-project-detail-tabs` 实证 15:18:01 派发 →
15:27:55 收口），远快于 60s 到期检测兜底，故对这类 SPEC 定时语义仍会被击穿。

堵该通道需在 `dispatch_review` 侧加门或加调用来源判据（与 D1 末条「改动面 MUST
保持在两个 handler + `_recover_one` 两分支」冲突），属独立决策——**建议后续 SPEC
单列一条 Requirement 治理**：在 `dispatch_review` 侧补 `start_after` 门控。

## 回归基线（tasks 4.1/4.2）

- `tests/test_start_after_gate.py`：23 用例全绿（四条自动通道 + 三条元放行路径 +
  fail-open + 零回归 + 人工豁免 + 日志级别）。
- 相关回归全绿（225 passed）：`test_spec_scheduling.py` / `test_event_bus.py` /
  `test_pm_promotion_gate.py` / `test_review_circuit_breaker.py` /
  `test_task_track.py` / `test_deliverable_declaration_premechanize.py` ——
  无 `start_after` 条目行为完全不变，既有用例零改动。
- 落地复现预演（`.history/` 临时夹具，已清理）：全新 StateMachine 驱动
  `_recover_one` + `_on_spec_drafted`，`drafted + 未来 start_after` 保持 drafted
  且无派发；`drafted + 已过期 start_after` 经 `check_scheduling_deadlines`（通道 ③）
  正常晋升到 ready。
