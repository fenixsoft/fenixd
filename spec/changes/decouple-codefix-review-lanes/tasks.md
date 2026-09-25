## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: docs/help/codefix-review-lane-decoupling.md
  kind: new
- path: tests/test_codefix_review_decoupling.py
  kind: new
```

## 1. 取证定案

- [x] 1.1 只读取证：grep code-fix 激活/推进路径与审查 run 在飞状态的耦合点，复核 09-24 15:15–16:45 空窗的日志链；候选 A（defer 合回缺自驱动推进）/ 候选 B（显式在飞门控）定案，结论与证据写入 `docs/help/codefix-review-lane-decoupling.md`

## 2. 派发解耦

- [x] 2.1 按取证结论落地解耦：defer 批合回后的自驱动推进（等价 `_resubmit`）为**无条件落地项**（Requirement 1 的 MUST，不随取证结论翻案）；候选 B（「审查在飞」否决/等待门控）若被取证证实则移除、若被排除则在交付文档记录排除证据即可；两者并存则都落地
- [x] 2.2 回归验证：审查 run 在飞（模拟无产出）期间 code-fix 照常建树派批推进，无派批空窗

## 3. 审查 stall 看门狗

- [x] 3.1 看门狗实现：审查 run 进度产物 mtime 与进程 CPU 时间双判据，阈值 `admin.review_stall_minutes`（缺省 30，`.fenix/config.template.yaml` 增键）；任一判据有进展即重置计时
- [x] 3.2 触发动作：cancel run → 既有急救落账路径（产物抢救入账）→ 告警留痕，挂载点复用 admin monitor 周期
- [x] 3.3 `docs/help/codefix-review-lane-decoupling.md` 补看门狗语义、阈值调参与误杀处置说明

## 4. 验证

- [x] 4.1 单测（tests/test_codefix_review_decoupling.py）：审查在飞 + 台账有 open 条目 → code-fix 照常派批（解耦）
- [x] 4.2 单测：defer 批合回成功 → 链自驱动推进下一批
- [x] 4.3 单测：双判据同时无进展达阈值 → 取消 + 急救落账 + 告警；任一判据有进展 → 不触发
- [x] 4.4 单测：审查正常收尾 inserted>0 → 链激活语义不变
