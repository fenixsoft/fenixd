## Deliverables

```yaml
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/pm_engine/dispatch/repair_lane.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_merge_back_spec_dir_guard.py
  kind: modify
- path: tests/test_admin_monitor_spec_amendment.py
  kind: new
```

## 1. merge-back 侧在飞修订探测

- [ ] 1.1 core/worktree_manager/mergeback.py：新增已提交在飞修订检测（git merge-base 求分叉点、git log <merge-base>..主树HEAD -- spec/changes/<spec>/ 判定），接入 merge_back_from_branch 闸门序列（_check_spec_dir_inflight 之后）；命中发 spec_amendment_inflight 告警（含修订提交短哈希列表）并把列表以带默认空值的新字段（如 amended_inflight）挂到 MergeConflictInfo
- [ ] 1.2 core/worktree_manager/mergeback.py：检测命中 MUST NOT 改变 merge-back 返回值与 has_semantic_conflict 语义、MUST NOT 计入 merge 熔断记账（对照 rehearsed 豁免先例）；实现分支不存在（merge-base 失败/已清理）时静默跳过
- [ ] 1.3 core/pm_engine/dispatch/queue.py：rehearsed 直通 repair 分支（_direct_rehearsed_to_repair）透传 amended_inflight，repair 派发上下文与 prompt 增补「主树在飞修订根因」段（repair_lane 消费）

## 2. 周期扫描入口

- [ ] 2.1 core/admin_monitor.py：对有活跃实现 run 的 spec 增加同条件周期检测（活跃实现分支 + merge-base 判定 spec 目录主树分叉），命中发 spec_amendment_inflight 告警（kind 级别/处方表注册，severity=major）；同一 spec+修订提交集合按告警指纹去重，不逐周期重复轰炸；分支/run 不在飞时静默跳过

## 3. 测试

- [ ] 3.1 tests/test_merge_back_spec_dir_guard.py：扩展——夹具仓库在 merge-base 之后于主树提交 spec 目录改动 → merge-back 发告警且 merge_info.amended_inflight 携带提交列表、repair 上下文含根因段；主树无新提交 → 行为与告警完全不变；分支不存在 → 静默跳过不报错
- [ ] 3.2 tests/test_admin_monitor_spec_amendment.py：实现 run 在飞 + 主树 spec 修订 → 一个扫描周期内告警、同指纹不重复；run 不在飞 → 不检测不告警
- [ ] 3.3 回归：tests/test_worktree_merge_guard.py（含 _wip_overlap_gate 用例）、tests/test_merge_tree_rehearsal.py、tests/test_mergeback_repair_lane.py 通过