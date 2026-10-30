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

- [x] 3.1 /root/potplayer-base/.fenix/verify.yaml 显式声明 evidence_retention（语法参照 /root/fenixd/core/verify_contract_template.yaml），接线已实现的分级留存字段
- [x] 3.2 potplayer-base 活跃 spec tasks.md 中 7 处根 verify-evidence/ 落位路径改写为 .fenix/verify-evidence/<spec>/（spec/changes/neutralize-pack-static-fingerprints/tasks.md:10/12/169/199、spec/changes/pack2-official-encoder/tasks.md:56/58/65）
- [x] 3.3 potplayer-base 存量未跟踪散件（约 92 项、485MB）经已上线的 archive_untracked_stray / ignore_untracked_stray 裁决执行器清债（core/dashboard/data/admin_actions.py:3230，归档落 .fenix/stray-archive/），不新写迁移脚本；已入库的 689MB 历史清除涉及 filter-repo 重写，仅在处置记录留方案待人类决策

## 验证修复（原地打回第 1 轮）

- [x] 先复核失败有效性：逐条核对 `spec/changes/evo-persist-stray-escalation-clock/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码（复核结论：stray-clock-corrupt-state-fallback 属真实产品 Bug——tasks.md 1.1 与 spec.md「持久化损坏降级」要求损坏容错覆盖字节层与 JSON 层两类，而 `stray_wip.py:837` read_text utf-8 解码失败在 json.loads 之前上穿、except 仅覆盖 FileNotFoundError/OSError；场景断言与产品应有行为相符）
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码（产品代码修复：`_load_untracked_registry` 读取段 except 补 `UnicodeDecodeError`（ValueError 子类、非 OSError），docstring 同步字节层/JSON 层两类容错表述；补回归钉子 `test_corrupt_registry_bytes_falls_back_without_blocking`）
- [x] 修复后重跑验证确认通过（tests/test_verify_evidence_placement.py 全量 40 passed 含新钉子、stray_wip 消费方 5 文件 129 passed、场景口径进程级探针 SCENE4_PASS exit 0——损坏注册表回退空表、留降级告警、主盘点不阻断；全量回归由验证链执行）
