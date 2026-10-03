## Deliverables

```yaml
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: core/worktree_manager/types.py
  kind: modify
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: tests/test_maintree_interactive_session_attribution.py
  kind: new
```

## 1. 归因器扩展

- [ ] 1.1 core/worktree_manager/mergeback.py：identify_wip_occupant（:856 起）在在飞车道归因零命中后追加只读「主树活交互会话」探测（候选源按 design 决策 1 取舍：会话注册/锁文件、最近提交人启发、transcript mtime 活跃信号），命中返回会话归因形态的 WipOccupantInfo；探测零命中/源缺失时行为与现状逐位一致（fail-open 回无主），全程无主树写入（遵守 :952 既有约束）。
- [ ] 1.2 core/worktree_manager/types.py：WipOccupantInfo 增加会话归因 occupant kind；BLIND_SPOT_NOTE（:27）与 describe()（:77-79）文案同步——命中会话归因时 evidence 标注会话线索，不再自认无主盲区。

## 2. 消费侧接入

- [ ] 2.1 core/worktree_manager/stray_wip.py：盘点侧（:180-201）对活会话归因散件默认降级——记 info 留痕（含会话线索、指纹记账与复位复用 :217-251 现状）不派 maintree_stray_wip_stale major、不触发 admin 代查；新增配置键 admin.maintree_session_attribution_action（info|keep，缺省 info，keep=现状行为）经既有宽限配置读取位（:44-65）同型加载。约定：info 留痕走盘点结构化返回值（status 新增会话归因形态，如 session-attributed）与既有日志通道，MUST NOT 新增 AdminStore signal_type（免 admin_monitor 三表登记缺口，漏登记则落 store 后无人摄取）；配置非法值守卫回退 keep（保守方向：配置事故 MUST NOT 静默吞 major，对齐 grace_minutes 守卫哲学）；会话归因分支的计时/复位与既有在飞车道命中分支同型（pop 计时条目、指纹消失即复位）。
- [ ] 2.2 core/code_fix.py：归因消费点（:3651 _coordinate_blocked_merge_impl，note=describe() 于 :3678/:3683、owner_kind 结构化台账 :3656-3660）与 defer 升级告警（:2486/:2501）复用归因结果/透传 describe() 新文本，不复制探测逻辑；defer 侧对会话归因的采信受 admin.maintree_session_attribution_action 同键约束（keep=视同零命中走现状 orphan 宽限升级流）。

## 3. 测试

- [ ] 3.1 tests/test_maintree_interactive_session_attribution.py（新建）：覆盖探测命中/零命中/源缺失三分支、WipOccupantInfo 会话形态与 describe 文案、stray_wip 降级与配置回退（info|keep）、code_fix 透传。
- [ ] 3.2 tests/test_maintree_stray_wip_sweep.py 与 tests/test_mergeback_wip_coordination.py（后者是 identify_wip_occupant 的直接既有测试场，:184-:615 十余处用例）：补「活会话归因命中时不发 major 告警、info 留痕、配置 keep 回退后仍发 major」用例，两文件既有用例全部不回退。