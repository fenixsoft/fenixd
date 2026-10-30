## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: tests/test_stray_untracked_session_attribution.py
  kind: new
```

## 1. 落地校验

- [x] 1.1 core/worktree_manager/stray_wip.py：_untracked_signal 增参 running_run_ids=()，在越阈分支（宽限判定前）接入 identify_wip_occupant，按归因器三态分别处置——命中会话归因且 admin.maintree_session_attribution_action != keep 时 pop 计时条目（宽限时钟复位）、落 info 留痕、返回 session-attributed 且不进宽限告警与升级判定；命中在飞实现车道 holder（非会话归因）同样 pop 计时、不告警、返回 holder-attributed（对齐 tracked 流 :464-472 holder 分支）；零命中维持现状流程。同步补全 _untracked_signal docstring 的 status 枚举（补 session-attributed / holder-attributed 及既有 escalated）。
- [x] 1.2 core/worktree_manager/stray_wip.py：_sweep_locked 调用点透传 running_run_ids；低于阈值早退分支不调用归因器；升级 major 信号 evidence 追加归因探测结果注记，措辞按探测结果分档：零命中写「归因探测已执行，零命中（判据：近窗提交路径交/活跃 transcript 路径提及）」，命中但 keep 回退写「归因探测已执行，命中但配置 keep 回退（视同零命中）」。
- [x] 1.3 core/worktree_manager/stray_wip.py：豁免语义对齐 tracked 流——复位时钟而非永久豁免，归因消失后重新建档计时；keep 配置完全回退现状行为。

## 2. 测试

- [x] 2.1 tests/test_stray_untracked_session_attribution.py：覆盖五态——会话归因命中（条目复位+session-attributed+零告警）；在飞车道 holder 命中（条目复位+holder-attributed+零告警）；keep 配置（照常计时）；零命中（宽限流不变+升级 evidence 含注记）；低于阈值（归因器零调用，stub 计数断言）。stub 方式参考 tests/test_maintree_stray_wip_sweep.py 既有探针形态。
- [x] 2.2 tests/test_stray_untracked_session_attribution.py：升级 evidence 注记断言用例——零命中场景断言「归因探测已执行」「零命中」字样在场；keep 回退场景断言注记为「命中但配置 keep 回退」而非「零命中」（不误述）。
- [x] 2.3 tests/test_maintree_stray_wip_sweep.py 与 tests/test_stray_whitelist_untracked.py 既有用例回归通过（python3 -m pytest tests/test_maintree_stray_wip_sweep.py tests/test_stray_whitelist_untracked.py -q）。