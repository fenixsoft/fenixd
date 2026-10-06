## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_code_fix_night_quiet_window.py
  kind: modify
- path: tests/test_admin_dispatch_window_avoidance.py
  kind: new
```

## 1. 预计跨窗顺延（code-fix 夜间批）

- [ ] 1.1 core/code_fix.py：_night_quiet_state（:2866 附近）升级为「预计跨窗」判定——除派发时刻落窗外，取同链近批实测时长（run_metrics 已记 turns/时长）估计预计结束时刻，与静默窗区间（admin.code_review_fix.night_quiet_window 可配，缺省 04:15-04:45）求交，相交即把可投递时刻顺延到窗末；checkpoint 守卫块（:3204-3290）消费同一判定，复用 _local_window_end_epoch 的 end_ts 基建。

## 2. admin 派发避让

- [ ] 2.1 core/admin_monitor.py：_invoke_administrator（:5229 附近）唤起闸门处与既有信号死法冷却判断并列，新增两不派条件——provider 瞬断冻结态（复用 core/agent_runner/provider_circuit.py 的 transient break 态）与夜间断窗期（窗常量自 core/code_fix.py 引入或抽公共模块），命中即本轮跳过并留痕原因，留待下轮盘点重试。

## 3. 测试

- [ ] 3.1 tests/test_code_fix_night_quiet_window.py：补预计跨窗用例——窗前派出且近批均时长使预计结束时刻落窗→顺延到窗末；预计不跨窗→照常投递；窗内派出→既有顺延行为不回归。
- [ ] 3.2 tests/test_admin_dispatch_window_avoidance.py（新建）：瞬断冻结态/断窗期内不唤起 admin 会话且记录跳过原因；窗外正常唤起不受影响。