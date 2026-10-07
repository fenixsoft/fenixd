# Spec Delta: spec-amendment-watch

## NEW Requirements

### Requirement: 主树 spec 目录的在飞修订必须被早期探测与告警

实现分支在飞期间，框架 MUST 能检测「spec/changes/<spec>/ 相对 merge-base 在主树上出现新的已提交修订」（`git log <merge-base>..主树HEAD -- spec/changes/<spec>/` 非空），并 MUST 发 `spec_amendment_inflight` 告警，内容含修订提交短哈希列表、受影响在飞分支/run 与「merge-back 将相撞」预警。

- 检测 MUST 提供两个入口：merge-back 主链（`merge_back_from_branch` 闸门序列内、预演前后均可，core/worktree_manager/mergeback.py:107）与 admin_monitor 周期扫描（core/admin_monitor.py）；周期入口 MUST 在修订落地后一个扫描周期内告警，不得等到 merge 时刻。
- 周期扫描入口 MUST 对同一 spec+修订提交集合按告警指纹去重，MUST NOT 每个扫描周期重复轰炸。
- 检测命中 MUST NOT 顺延或中止 merge-back（冲突结局确定，顺延无收益）、MUST NOT 计入 merge 熔断记账（对照 rehearsed=True 豁免先例，core/pm_engine/dispatch/queue.py:1853-1863）。
- 实现分支不存在（已合回清理）时检测 MUST 静默跳过，MUST NOT 报错。

**背景（事件依据）**：2026-10-02 修订提交 803c688（10:46:21）落在实现 run 在飞窗口内，14:28:55 预演检出 spec/changes/cimbar-airgap-transfer/tasks.md 冲突直通 repair（fenixd.log 06:28:55Z）；修订落地到检出相隔近 4 小时且全程零反馈。

#### Scenario: 在飞期间主树修订落地

- **WHEN** 实现 run 在飞且主树出现触及 spec/changes/<spec>/ 的新提交
- **THEN** 一个扫描周期内发出 spec_amendment_inflight 告警（含提交列表与相撞预警），同一修订集合不重复告警，merge-back 与派发行为不变

#### Scenario: merge-back 撞在飞修订转 repair 带根因

- **WHEN** merge 预演检出 spec 目录语义冲突且存在在飞修订提交
- **THEN** 直通 repair 的派发上下文 MUST 附着修订提交列表，repair prompt 含「主树在飞修订」根因段，无须 repair 自行考古

#### Scenario: 无修订零扰动

- **WHEN** merge-base 之后主树 spec 目录无新提交，或实现分支已不存在
- **THEN** 不发告警，merge-back 与周期扫描行为完全不变