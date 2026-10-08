## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: core/code_review.py
  kind: modify
- path: tests/test_code_fix_severity_gate.py
  kind: new
```

## 1. 配置键

- [ ] 1.1 core/config.py：get_code_review_fix_config 增加 min_immediate_severity（severity 词表内取值，缺省 major）与 minor_batch_cadence（天数，缺省 7）两键读取，沿既有严格校验+回退缺省范式，非法值回退缺省并走既有配置告警通道，不新增异常路径

## 2. 选批分级

- [ ] 2.1 core/code_fix.py：checkpoint 选批处按 severity 分流——达 min_immediate_severity 的条目保持既有当日批序，低于门限的置 deferred 标记（含 deferred_since）延后，距首个 deferred_since 达 minor_batch_cadence 天时整组放行；deferred 条目在链收敛统计与 chain_skipped 对账中按挂起计、不计为 skipped/lost，指纹重开（core/code_fix.py:2528 一线）命中 deferred 条目时合并刷新而非新开
- [ ] 2.2 core/code_review.py：generate_fix_spec 候选筛选应用同一 severity 谓词（谓词放单一函数供两模块导入），使 Dashboard 手工触发与 scheduled 触发同门，未到周批窗口的纯 minor/info 触发按空批处理并说明原因

## 3. 测试

- [ ] 3.1 tests/test_code_fix_severity_gate.py：覆盖混合严重度选批分流、deferred 跨周批晋级、deferred 期间同指纹合并、链收敛不计 skipped/lost、非法配置回退缺省、门限配为最低档时与现状零差异

## 4. 运维收尾（一次性处置，非代码交付物）

- [ ] 4.1 用户级 /root/.fenix/config.yaml 的 admin.code_review.scope 由 full 回拨为 window（增量收集与空窗跳过已由 core/admin_monitor.py:1591-1629 现有实现免费获得），次日核对最新评审 manifest 仅含窗口内变更文件且无改动日直接跳过
