## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: tests/test_verify_evidence_placement.py
  kind: modify
```

## 1. 注册表持久化

- [x] 1.1 core/worktree_manager/stray_wip.py：_untracked_registry 落盘持久化到 .fenix/ 运行时状态区（指纹→first_seen/first_seen_iso/路径集合/escalated_at/escalated_signal_at，与现行内存条目同构；sizes_bytes/total_bytes 每轮现采不持久化），盘点变更后原子写（临时文件+os.replace，沿 core/signals.py 既有原子写范式），盘点开始时载入合并；文件缺失或损坏回退空表并留一条告警，不阻断主盘点；既有 30 分钟宽限、5 条阈值、500MB 体积阈值与指纹规则全部不变；同步改写模块 docstring D5 注记（「不引入新的持久化状态文件」对 untracked 注册表被本 SPEC 显式取代，tracked 流维持内存态）
- [x] 1.2 core/worktree_manager/stray_wip.py：注册表载入与每轮盘点时对盘上已消失路径做惰性清理（条目剔除、空指纹整条删除），使 24 小时滞留升级（elapsed≥1440 分钟）与体积升级跨 daemon 重启连续计时、同指纹一次性告警跨重启去重、升级标记（escalated_signal_at）跨重启保持——已升级集合重启后不重复发 maintree_untracked_stray_escalated

## 2. 测试

- [x] 2.1 tests/test_verify_evidence_placement.py：补充覆盖——重启模拟（清内存→重载注册表→elapsed 连续累计并命中 maintree_untracked_stray_escalated）、合成旧时间戳驱动升级路径、同指纹跨重启不重复告警、已升级集合跨重启不重复发升级信号（escalated_signal_at 持久化）、持久化文件损坏回退降级、失效路径惰性清理后不复燃

## 3. 项目侧收尾（一次性运维处置，非代码交付物）

- [ ] 3.1 /root/potplayer-base/.fenix/verify.yaml 显式声明 evidence_retention（语法参照 /root/fenixd/core/verify_contract_template.yaml），接线已实现的分级留存字段
- [ ] 3.2 potplayer-base 活跃 spec tasks.md 中 7 处根 verify-evidence/ 落位路径改写为 .fenix/verify-evidence/<spec>/（spec/changes/neutralize-pack-static-fingerprints/tasks.md:10/12/169/199、spec/changes/pack2-official-encoder/tasks.md:56/58/65）
- [ ] 3.3 potplayer-base 存量未跟踪散件（约 92 项、485MB）经已上线的 archive_untracked_stray / ignore_untracked_stray 裁决执行器清债（core/dashboard/data/admin_actions.py:3230，归档落 .fenix/stray-archive/），不新写迁移脚本；已入库的 689MB 历史清除涉及 filter-repo 重写，仅在处置记录留方案待人类决策
