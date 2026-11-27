## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: tests/test_stray_tracked_registry_persistence.py
  kind: new
- path: spec/knowledge/domains/worktree-vc/stray-escalation-clock-persistence.md
  kind: modify
- path: spec/knowledge/domains/worktree-vc/maintree-stray-wip-sweep.md
  kind: modify
```

## 1. tracked 流注册表落盘

- [ ] 1.1 core/worktree_manager/stray_wip.py：tracked 流注册表同构落盘——新增 TRACKED_REGISTRY_RELPATH='.fenix/stray_tracked_registry.json'，文件两分区（`tracked` 计时条目 + `alert_history` 静默窗台账）；复用 untracked 先例（UNTRACKED_REGISTRY_RELPATH:128、_UNTRACKED_PERSISTED_FIELDS:136、_load_untracked_registry:2039、_persist_untracked_registry:2192）的路径常量/字段白名单/加载/原子写（tmp+replace、payload 无变更跳过）形态；载入挂点 sweep() 进入 _sweep_locked 前（每进程一次守卫，对齐 :685），回写挂点 sweep() 内层 finally（含本轮放弃路径，对齐 :687-691）；载入 OSError/字节层损坏置「本轮禁写」哨兵（对齐 _untracked_persist_suppressed，code-review item d055f002ec41），本进程不覆写盘上完好文件。
- [ ] 1.2 core/worktree_manager/stray_wip.py：24 小时滚动静默窗——同 fp 距上次告警不足 24h 抑制（不写 AdminStore、不唤起 admin run、suppressed_count += 1、60 分钟聚合 info 日志，形态对齐 _session_attr_dedup_log）；满 24h 正常重告并在 evidence 携带「静默窗抑制轮数」（与 _prior_stray_rounds 复发轮数分列）；指纹演进按常规宽限告警。tracked 告警门槛由 `not entry.get("escalated_at")` 改为 alert_history 判定（escalated_at 仍写入/持久化，仅审计与兼容）。alert_history 独立于 _registry 生命周期（:1035/:1048 pop 与 :1125 复位不清台账），不在场且超 24h 淘汰；抑制轮 sweep 返回 status 维持 orphan-timed、键集不变。
- [ ] 1.3 core/worktree_manager/stray_wip.py：同步改写模块 docstring 与类 docstring 的 D5 注记（:22-33、:517-521），删除「tracked 流维持内存态/损失仅时效」表述并记录推翻依据（两窗 14 次处置 run 约 11.8 美元、重启后 4/4 命中 69-71 秒重登记 first_seen、宽限后重告的 AdminStore/归档先例实测口径）；同步把「落盘仅两处」的零触碰注记改为三处（AdminStore、untracked 注册表、tracked 注册表）。
- [ ] 1.4 spec/knowledge/domains/worktree-vc/stray-escalation-clock-persistence.md 与 maintree-stray-wip-sweep.md：改写「仅 untracked 持久化 / tracked 注册表维持内存态 / 损失仅时效」表述，记录本 SPEC 的推翻依据与 tracked 24h 静默窗语义（含台账与计时条目分账），避免知识真相源与实际行为相反。

## 2. 测试

- [ ] 2.1 tests/test_stray_tracked_registry_persistence.py：覆盖落盘/重启恢复（字段白名单、原子写）、24h 内同指纹抑制且 suppressed_count 累计、满 24h 重告带抑制轮数、指纹演进重告并复位计时、归因分支 pop 计时条目后台账仍在、载入 OSError 禁写、注册表损坏回退内存态不阻塞盘点、台账淘汰；装配方式参照现有 tests/test_maintree_stray_wip_sweep.py 与 tests/test_stray_whitelist_untracked.py。
- [ ] 2.2 回归锚：tests/test_maintree_stray_wip_sweep.py 与 tests/test_stray_whitelist_untracked.py 全绿——同指纹一次性、registry 复位、零触碰对账、sweep 返回键集/取值逐位不变（含认领核销相关断言）。
