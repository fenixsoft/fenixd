# Spec Delta: stray-untracked-escalation

能力：主树 untracked 散件滞留的分级升级与自动认领——滞留时长或体积触顶时升档为 major 升级信号并自动唤起 admin 处置。

## ADDED Requirements

### Requirement: 体积采集随盘点输出

untracked 散件盘点 SHALL 输出滞留集合条目体积（字节），随注册表与告警 evidence 字段暴露。

#### Acceptance Scenario 1: 体积随 evidence 暴露
- WHEN untracked 盘点对滞留集合写告警与注册表条目
- THEN evidence 含集合体积（字节），注册表条目同源可查

### Requirement: 第二档升级信号

- 新信号类型 maintree_untracked_stray_escalated，severity 为 major；
- 触发条件：滞留时长 ≥ 24 小时，或滞留集合体积 ≥ 阈值（缺省 524288000 字节，可配）；体积判定 SHALL 独立于滞留时长（每轮对已告警在册集合计算体积，MUST NOT 以 elapsed 达标为体积计算前置）；
- 同一滞留集合只升级一次（注册表双档标记）。

#### Acceptance Scenario 1: 24 小时滞留触发升级
- WHEN 滞留集合 elapsed ≥ 24 小时且未升级过
- THEN 发出 maintree_untracked_stray_escalated（major），原 info 信号仍一次性不重复告警

#### Acceptance Scenario 2: 体积阈值独立触发升级
- WHEN 滞留集合体积 ≥ 阈值且滞留时长未达 24 小时
- THEN 仍发出升级信号（体积路径不被滞留时长门控）

#### Acceptance Scenario 3: 只升级一次
- WHEN 同一滞留集合已升级过且指纹未消失
- THEN 不再重复发出升级信号

### Requirement: 自动唤起接线

- SIGNAL_SEVERITY 表登记新类型（major）；
- SIGNAL_RECOMMENDATION 表登记新类型处置指引文案（写入方 _write_alert 与唤起记录 recommended_action 均查该表，漏登则告警无指引）；
- STORED_SIGNAL_TYPES 收录新类型；
- 摄取唤起循环的项目名解析清单覆盖新类型（缺失时记录被丢弃、唤起静默落空）。

#### Acceptance Scenario 1: 登记表与解析清单同步
- WHEN 新信号告警落盘
- THEN 摄取循环按「项目名=」解析出 spec 并唤起 admin，recommended_action 非空

### Requirement: untracked 认领执行器

- 三种裁决：显式归档（移入登记目录）、追加 .gitignore、删除；
- signal_type 绑定白名单仅含 maintree_untracked_stray_escalated，对 tracked 桶信号显式拒绝且零 git 写；evidence 清单段解析兼容 info 前身信号格式（仅指解析器复用，不将 info 信号放行为执行目标）；
- 裁决选项在 dashboard 裁决清单登记。

#### Acceptance Scenario 1: tracked 信号拒绝零 git 写
- WHEN 以 tracked 桶信号调用认领执行器
- THEN 在任何 git 读/写之前 fail-closed 拒绝，零 git 写

#### Acceptance Scenario 2: 三种裁决落盘
- WHEN 分别执行归档/追加 .gitignore/删除裁决
- THEN 归档移入登记目录、.gitignore 去重追加、删除移除目标文件，处置记录落盘

## 验收

- 升级信号两条触发路径与「只升级一次」有测试；登记表与项目名解析清单同步有测试（含解析清单回归）；认领执行器对 tracked 信号拒绝零 git 写与三种裁决落盘有测试。
