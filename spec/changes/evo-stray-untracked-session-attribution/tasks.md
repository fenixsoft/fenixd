## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: tests/test_stray_untracked_session_attribution.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/worktree_manager/stray_wip.py：_untracked_signal 增参 running_run_ids=()，在越阈分支（宽限判定前）接入 identify_wip_occupant——命中会话归因且 admin.maintree_session_attribution_action != keep 时 pop 计时条目（宽限时钟复位）、落 info 留痕、返回 session-attributed 且不进宽限告警与升级判定；零命中维持现状流程。
- [ ] 1.2 core/worktree_manager/stray_wip.py：_sweep_locked 调用点透传 running_run_ids；低于阈值早退分支不调用归因器；升级 major 信号 evidence 追加「归因探测已执行/零命中」注记。
- [ ] 1.3 core/worktree_manager/stray_wip.py：豁免语义对齐 tracked 流——复位时钟而非永久豁免，归因消失后重新建档计时；keep 配置完全回退现状行为。

## 2. 测试

- [ ] 2.1 tests/test_stray_untracked_session_attribution.py：覆盖四态——会话归因命中（条目复位+session-attributed+零告警）；keep 配置（照常计时）；零命中（宽限流不变+升级 evidence 含注记）；低于阈值（归因器零调用，stub 计数断言）。stub 方式参考 tests/test_maintree_stray_wip_sweep.py 既有探针形态。
- [ ] 2.2 tests/test_stray_untracked_session_attribution.py：升级 evidence 注记断言用例（归因已执行/零命中字样在场）。
- [ ] 2.3 tests/test_maintree_stray_wip_sweep.py 与 tests/test_stray_whitelist_untracked.py 既有用例回归通过（python3 -m pytest tests/test_maintree_stray_wip_sweep.py tests/test_stray_whitelist_untracked.py -q）。