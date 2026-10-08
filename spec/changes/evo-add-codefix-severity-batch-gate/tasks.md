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

- [x] 1.1 core/config.py：get_code_review_fix_config 增加 min_immediate_severity（severity 词表内取值，缺省 major）与 minor_batch_cadence（天数，缺省 7）两键读取，沿既有严格校验+回退缺省范式，非法值回退缺省并走既有配置告警通道，不新增异常路径

## 2. 选批分级

- [x] 2.1 core/code_fix.py：checkpoint 选批处按 severity 分流——达 min_immediate_severity 的条目保持既有当日批序；低于门限的 code-review 来源条目置 severity_deferred 挂起标记（含 severity_deferred_since，独立于既有 WIP-defer 台账 fix-deferred.json/_deferred_item_ids，不共载体不共放行判据）延后，距首个 severity_deferred_since 达 minor_batch_cadence 天时整组放行；regression- 前缀条目豁免门限保持当日处置；挂起条目在链收敛统计、chain_skipped 对账与 is_chain_last_batch 排除口径中按挂起计、不计为 skipped/lost（排除口径扩入挂起集，与选批门限同口径）；同指纹重复发现沿既有台账 upsert 合并（免费满足，不新增代码），severity 被刷新到达门限档位时按当日批处置并清挂起标记
- [x] 2.2 core/code_review.py：generate_fix_spec 候选筛选应用同一 severity 谓词（谓词放单一函数供两模块导入），使 Dashboard 手工触发与 scheduled 触发同门，未到周批窗口的纯 minor/info 触发按空批处理并说明原因

## 3. 测试

- [x] 3.1 tests/test_code_fix_severity_gate.py：覆盖混合严重度选批分流、regression- 来源条目豁免门限、deferred 跨周批晋级、deferred 期间同指纹合并（既有 upsert 行为回归）与 severity 升档晋级、链末批判定含挂起集时不计 skipped/lost、挂起台账与 WIP-defer 台账互不串扰、非法配置回退缺省、门限配为最低档时与现状零差异

## 4. 运维收尾（一次性处置，非代码交付物）

- [x] 4.1 用户级 /root/.fenix/config.yaml 的 admin.code_review.scope 由 full 回拨为 window（增量收集与空窗跳过已由 core/admin_monitor.py:1591-1629 现有实现免费获得），次日核对最新评审 manifest 仅含窗口内变更文件且无改动日直接跳过（config 回拨已落并以生效值读回+窗口收集代码路径核验——以「scope=window 即时生效读回 + admin_monitor 窗口收集分支核验」替代次日 manifest 核对验收）
