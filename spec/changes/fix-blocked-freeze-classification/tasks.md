# 任务

## Deliverables

```yaml
- path: core/state_machine.py
  kind: modify
- path: core/pm_engine/spec_review.py
  kind: modify
- path: core/pm_engine/budget.py
  kind: modify
- path: core/pm_engine/spec_integrity.py
  kind: modify
- path: tests/test_spec_review_gate.py
  kind: modify
- path: tests/test_state_machine.py
  kind: modify
- path: docs/help/03-lifecycle.md
  kind: modify
```

## 1. 分类契约与机械化 helper

- [ ] 1.1 core/state_machine.py：新增「冻结转人工」单一入口 helper（如 `freeze_for_human`）——一次调用完成 `status=blocked` + `frozen=True` + 规范 error 前缀，并经注入的告警回调发送人工升级告警，保证 frozen 与 alert 成对、不可分离。以最小依赖倒置解耦告警发送（helper 接收回调/发送器，不硬引 PM engine）。
- [ ] 1.2 core/state_machine.py：把重启重验超限冻结点（`~:849` 的 `freeze_spec` 调用）改为经 helper 走「冻结 + 告警」，补上缺失的人工升级告警（逐 SPEC 触发，不聚合丢失；signal_type 如 `verify_redo_exhausted`）。

## 2. 评审路径归入冻结转人工

- [ ] 2.1 core/pm_engine/spec_review.py：评审否决分支（`:186`，`rejected`）置 blocked 时改走「冻结转人工」——`frozen=True` + 人工升级告警（severity major，描述含否决 findings 摘要与评审 run id），替换现行裸 `transition(blocked)`。
- [ ] 2.2 core/pm_engine/spec_review.py：评审尝试耗尽两处（`:80` 入口前置判定、`:397` 失败计数达上限）置 blocked 时同样改走「冻结转人工」+ 告警（含连续失败原因）。

## 3. 既有冻结站点收敛到 helper

- [ ] 3.1 core/pm_engine/budget.py + core/pm_engine/spec_integrity.py：把各自手写的 `update_spec({status:blocked, FROZEN_FIELD:True, error:...})` + `_send_human_escalation_alert` 改为调用 §1.1 helper——行为与文案不变，仅换写法，消除「各站点各自记得成对」的漂移面。

## 4. 文档

- [ ] 4.1 docs/help/03-lifecycle.md：「冻结与解冻」邻域新增小节「blocked 的两种语义：冻结 vs 阻塞」——定义二分类、判据（admin 是否有操作杠杆）、各类消费者（admin_monitor 豁免 / dashboard 双标签 / 人工升级告警），并列出本轮归类的站点清单（评审否决/耗尽、预算耗尽、内容缺失、env 阻塞、重启重验超限 → 冻结；merge-back 熔断、契约缺失、env 单轮、交付物守卫终审 → 阻塞）。落点：该文档内新增小节（不新建独立文档）。若 §5 文档契约要求同步其它文档（如 07-safeguards.md 告警章节）则一并补一句交叉引用。

## 5. 回归测试

- [ ] 5.1 tests/test_spec_review_gate.py：断言评审否决（`rejected`）与尝试耗尽（`incomplete`）两条路径均写 `frozen=True` 且发出人工升级告警；断言 `admin_monitor` 的 blocked_stuck 对这些 SPEC 不再唤起（冻结豁免）。
- [ ] 5.2 tests/test_state_machine.py：断言重启重验超限冻结伴随人工升级告警（不再静默）。
- [ ] 5.3 tests/test_state_machine.py（或 helper 所属测试）：断言「冻结转人工」helper 的成对不变式——frozen=True 必然伴随一次告警发送；helper 调用后不存在无告警的冻结。
