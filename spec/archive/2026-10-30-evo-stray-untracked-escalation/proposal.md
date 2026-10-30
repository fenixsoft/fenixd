# 提案：untracked 散件告警升级与自动认领（stray-untracked-escalation）

## 背景

maintree_untracked_stray_stale 信号（主树 untracked 散件滞留盘点，info 级只告警不处置）自 2026-10-03 起对 potplayer-base 主树散件连续留痕 30 条，0 处置、0 升级，散件规模从 44 entry 恶化至峰值 119 entry（现值 1.2G/92 entry）。对照同族 tracked 桶 maintree_stray_wip_stale：已收录 STORED_SIGNAL_TYPES 自动唤起 Administrator，10 signal 对应 20 条 disposition、全部 handled——自动链路的能力与出口都在，untracked 桶只是未被接入，且无适用于 untracked 文件的处置执行器（untrack 执行器的 D4 守卫仅认 tracked 信号）。

「只告警不处置」是有意设计（evo-add-verify-evidence-placement-contract design.md 裁定 + admin_monitor.py:352-356 MUST NOT 收录注释），本提案显式修订该裁定的适用边界：info 信号本身维持一次性留痕不收录，新增第二档升级信号接入自动唤起。

## 目标

1. untracked 盘点采集条目体积；滞留超 24 小时或体积超阈值（缺省 500MB，可配）时发出第二档升级信号 maintree_untracked_stray_escalated（severity major），只升级一次。
2. 升级信号接入既有自动唤起链路（SIGNAL_SEVERITY / STORED_SIGNAL_TYPES / _detect_family_explosion 三表同步），自动派发 admin 认领 run。
3. 新增 untracked 散件认领执行器：显式归档、追加 .gitignore、删除三种裁决；对 tracked 信号显式拒绝零 git 写。

## 非目标

- 不改 tracked 桶 maintree_stray_wip_stale 的既有触发、处置与 untrack 执行器语义。
- 不改 admin_alerts 存储结构（保持扁平记录列表）。
- 「证据入库或显式豁免」源头门由分级留存 spec（verify-evidence-tiered-retention）与 placement 契约的项目侧配置采用承载，本 SPEC 不重复建设。
- 不动 info 信号的一次性告警语义与降噪阈值。

## 验收口径

- 24 小时滞留与体积阈值两条升级路径各有测试钉住，且只升级一次。
- 升级信号触发 admin 自动唤起（注册表三表同步有测试）。
- 认领执行器对 tracked 信号拒绝零 git 写；三种裁决落盘行为有测试。