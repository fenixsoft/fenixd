## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_code_fix_night_quiet_window.py
  kind: modify
- path: tests/test_admin_dispatch_window_avoidance.py
  kind: new
```

## 1. 预计跨窗顺延（code-fix 夜间批）

- [ ] 1.1 core/code_fix.py：_night_quiet_state（:2866 附近）升级为「预计跨窗」判定——除派发时刻落窗外，取同链近批实测时长（自 1.2 补记的 duration_s 读取）估计预计结束时刻，与静默窗区间（admin.code_review_fix.night_quiet_window 可配，缺省 04:15-04:45）求交，相交即把可投递时刻顺延到窗末；checkpoint 守卫块（:3204-3290）消费同一判定，复用 _local_window_end_epoch 的 end_ts 基建。近批无有效时长样本（冷启动/历史行未记时长）时回退既有「仅判派发时刻落窗」行为，fail-open 不阻塞投递。预计跨窗态与真实窗内态共用窗次标识与武装告警语义（同窗次幂等），MUST NOT 因「预测态→真实窗内态」迁移重复武装。
- [ ] 1.2 core/agent_runner/runner.py：run_metrics 行补记 duration_s（run 墙钟时长）——归档行（:6359 附近）与日志侧 metric_type=run_metrics 行（:6400 附近）两处同源写入；读取侧（code_fix.py _read_run_metrics）对历史行缺该字段按缺样跳过。

## 2. admin 派发避让

- [ ] 2.1 core/admin_monitor.py：_invoke_administrator（:5229 附近）唤起闸门处与既有信号死法冷却判断并列，新增两不派条件——provider 瞬断冻结态（复用 core/agent_runner/provider_circuit.py 的 transient break 态）与夜间断窗期（窗常量自 core/code_fix.py 引入或抽公共模块），命中即本轮跳过并留痕原因，留待下轮盘点重试。落点与人工通道政策沿 design D2：与信号死法冷却同位并列，人工显式触发同样避让（先例 core/code_fix.py:3210-3212 手动授权仅越过 enabled 总开关）；瞬断冻结态判定复用 provider_circuit.is_global_transient_break（core/agent_runner/provider_circuit.py:1061）；跳过属非失败路径，MUST NOT 增 retry_count、MUST NOT 落升级告警。

## 3. 测试

- [ ] 3.1 tests/test_code_fix_night_quiet_window.py：补预计跨窗用例——窗前派出且近批均时长使预计结束时刻落窗→顺延到窗末；预计不跨窗→照常投递；窗内派出→既有顺延行为不回归；近批无有效样本→回退仅判派发时刻、照常投递；「预测态→真实窗内态」迁移不重复武装。
- [ ] 3.2 tests/test_admin_dispatch_window_avoidance.py（新建）：瞬断冻结态/断窗期内不唤起 admin 会话且记录跳过原因；窗外正常唤起不受影响；人工显式触发在断窗/冻结期内同样避让且不增 retry_count、不落升级告警。