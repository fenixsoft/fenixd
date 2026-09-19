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

- [x] 1.1 core/state_machine.py：新增「冻结转人工」单一入口 helper（如 `freeze_for_human`）——一次调用完成 `status=blocked` + `frozen=True` + error 文案，并经注入的告警回调发送人工升级告警，保证 frozen 与 alert 成对、不可分离。以最小依赖倒置解耦告警发送（helper 接收回调/发送器，不硬引 PM engine）。**error 文案契约**：helper 必须显式接收 error 文本参数（各站点保留既有文案，不强制统一前缀文本——预算/完整性站点的长文案须原样保留）；对评审路径，error 必须内嵌 `原状态 <冻结前状态>` 子串（评审三处为 `reviewing`，与 dashboard 冻结的「原状态 X」文本契约一致，复用 `parse_orig_status` 共享读函数），保证解冻后恢复到冻结前状态——评审类 spec 解冻 → 恢复 `reviewing` → daemon 事件链（event_bus `reviewing→spec_reviewing` → `_on_spec_reviewing` → `dispatch_review`）自动重派评审，不得因缺失「原状态」子串而让 `parse_orig_status` 回退 `ready`（会把被否决 spec 误推至实现调度）。
- [x] 1.2 core/state_machine.py：把重启重验超限冻结点（`~:849` 的 `freeze_spec` 调用）改为经 helper 走「冻结 + 告警」，补上缺失的人工升级告警（逐 SPEC 触发，不聚合丢失；signal_type 如 `verify_redo_exhausted`）。**告警回调接线**：`recover_interrupted` 是 :849 路径的唯一生产调用点（fenixd.py:404），告警回调须沿既有 `remerge_callback` 同型注入通道接线（fenixd 侧构造非 None 回调）——缺省 None 会使恢复路径退回静默冻结、违反「冻结必告警」不变式，生产接线 MUST 非 None（None 仅允许单测场景）。

## 2. 评审路径归入冻结转人工

- [x] 2.1 core/pm_engine/spec_review.py：评审否决分支（`:186`，`rejected`）置 blocked 时改走「冻结转人工」——`frozen=True` + 人工升级告警（severity major，描述含否决 findings 摘要与评审 run id），替换现行裸 `transition(blocked)`。**冻结收口**：helper 冻结后在同一收口内清除 `reviewer_run` 与 `_review_attempts`（沿用现行 update_spec 清理，但不携带 error 键覆盖冻结 error）；error 文案格式 `用户指令冻结：原状态 reviewing · spec-review-rejected: <blocking findings 摘要>`（run id 取自收口前的 `reviewer_run`），使「解冻 → 恢复 reviewing → 自动重派评审」闭环可达。
- [x] 2.2 core/pm_engine/spec_review.py：评审尝试耗尽两处（`:80` 入口前置判定、`:397` 失败计数达上限）置 blocked 时同样改走「冻结转人工」+ 告警（含连续失败原因）。error 文案格式 `用户指令冻结：原状态 reviewing · spec-review-incomplete: <连续失败原因>`，其余收口与 2.1 相同。

## 3. 既有冻结站点收敛到 helper

- [x] 3.1 core/pm_engine/budget.py + core/pm_engine/spec_integrity.py：把各自手写的 `update_spec({status:blocked, FROZEN_FIELD:True, error:...})` + `_send_human_escalation_alert` 改为调用 §1.1 helper——行为与文案不变，仅换写法，消除「各站点各自记得成对」的漂移面。

## 4. 文档

- [x] 4.1 docs/help/03-lifecycle.md：「冻结与解冻」邻域新增小节「blocked 的两种语义：冻结 vs 阻塞」——定义二分类、判据（admin 是否有操作杠杆）、各类消费者（admin_monitor 豁免 / dashboard 双标签 / 人工升级告警），并列出本轮归类的站点清单（评审否决/耗尽、预算耗尽、内容缺失、env 阻塞、重启重验超限 → 冻结；merge-back 熔断、契约缺失、env 单轮、交付物守卫终审 → 阻塞）。**恢复路径必写**：冻结评审类 spec 的人工恢复 = 修订方案后解冻（dashboard/CLI 解冻恢复原状态 `reviewing`）→ daemon 自动重派评审；并注明 `re_review`（重新评审入口）对 frozen spec 保持拒绝（既有冻结保护契约，见 test_dashboard_api.py:1034 `test_re_review_frozen_rejected`）——评审类冻结的恢复走解冻而非 re_review。落点：该文档内新增小节（不新建独立文档）。若 §5 文档契约要求同步其它文档（如 07-safeguards.md 告警章节）则一并补一句交叉引用。

## 5. 回归测试

- [x] 5.1 tests/test_spec_review_gate.py：断言评审否决（`rejected`）与尝试耗尽（`incomplete`）两条路径均写 `frozen=True` 且发出人工升级告警；断言 `admin_monitor` 的 blocked_stuck 对这些 SPEC 不再唤起（冻结豁免）。**新增恢复闭环断言**：冻结 error 含「原状态 reviewing」子串；按 dashboard 解冻语义（`parse_orig_status` 解析 → `unfreeze_spec(status=orig)`）解冻后 SPEC 恢复 `reviewing` 且可由 `_on_spec_reviewing` 重新派发评审（`reviewer_run`/`_review_attempts` 已清空）。
- [x] 5.2 tests/test_state_machine.py：断言重启重验超限冻结伴随人工升级告警（不再静默）。
- [x] 5.3 tests/test_state_machine.py（或 helper 所属测试）：断言「冻结转人工」helper 的成对不变式——frozen=True 必然伴随一次告警发送；helper 调用后不存在无告警的冻结。
