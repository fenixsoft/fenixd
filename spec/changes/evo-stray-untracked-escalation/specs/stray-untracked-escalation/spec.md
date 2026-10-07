# specs/stray-untracked-escalation/spec.md

## 能力

主树 untracked 散件滞留的分级升级与自动认领：滞留时长或体积触顶时升档为 major 升级信号并自动唤起 admin 处置。

## 需求

### R1 体积采集

untracked 散件盘点输出条目体积（字节），随注册表与告警 evidence 字段暴露。

### R2 第二档升级信号

- 新信号类型 maintree_untracked_stray_escalated，severity 为 major；
- 触发条件：滞留时长 ≥ 24 小时，或滞留集合体积 ≥ 阈值（缺省 524288000 字节，可配）；
- 同一滞留集合只升级一次（注册表双档标记）。

### R3 自动唤起接线

- SIGNAL_SEVERITY 表登记新类型；
- STORED_SIGNAL_TYPES 收录新类型；
- 摄取唤起循环的项目名解析清单覆盖新类型（缺失时记录被丢弃、唤起静默落空）。

### R4 untracked 认领执行器

- 三种裁决：显式归档（移入登记目录）、追加 .gitignore、删除；
- 仅接受 maintree_untracked_stray_escalated（及其 info 前身信号的清单格式），对 tracked 桶信号显式拒绝且零 git 写；
- 裁决选项在 dashboard 裁决清单登记。

## 验收

- R2 两条触发路径与「只升级一次」有测试；R3 三表同步有测试（含项目名解析清单回归）；R4 守卫与三种裁决落盘有测试。