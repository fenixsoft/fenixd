## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: core/dashboard/data/adjudication_choices.py
  kind: modify
- path: tests/test_maintree_stray_wip_sweep.py
  kind: modify
- path: tests/test_stray_untrack_remediation.py
  kind: modify
```

## 1. 体积采集与第二档升级

- [ ] 1.1 core/worktree_manager/stray_wip.py：_untracked_stray_entries（约 404 行）采集滞留集合条目体积（字节），随注册表与告警 evidence 字段输出
- [ ] 1.2 core/worktree_manager/stray_wip.py：untracked 盘点流（约 504-565 行）加第二档升级判定——滞留 elapsed≥24h 或集合体积≥阈值（缺省 524288000 即 500MB，仿 :81 untracked_stray_threshold 的可配范式；体积判定独立于 elapsed，每轮对已告警在册集合计算体积，MUST NOT 以 elapsed 达标为体积计算前置，否则体积路径被 24h 门控）时发出新信号 maintree_untracked_stray_escalated（severity major，按 :611 写告警处参数化），注册表（约 157 行）支持双档 escalated 标记保证同一集合只升级一次；同步修订 :31-35 的 MUST NOT 收录注释表述（info 信号维持不收录、升级信号除外）

## 2. 自动唤起接线

- [ ] 2.1 core/admin_monitor.py：SIGNAL_SEVERITY（约 290 行）登记 maintree_untracked_stray_escalated=major；SIGNAL_RECOMMENDATION（约 390 行）登记处置指引文案（写入方 _write_alert 与唤起记录 recommended_action :2708 查表取值，漏登则告警无指引）；STORED_SIGNAL_TYPES（约 481 行）收录新类型；_detect_family_explosion 的项目名解析清单（约 2519 行旁）覆盖新类型，防 evidence 无项目名的记录被丢弃致唤起静默落空

## 3. untracked 认领执行器

- [ ] 3.1 core/dashboard/data/admin_actions.py：新增 untracked 散件认领执行器——显式归档（移入登记目录）、追加 .gitignore、删除三种裁决；复用 _latest_stray_wip_manifest 清单段解析与 _append_gitignore_entries/_path_already_ignored（约 2908-2944 行）；_exec_untrack_stray_wip 的 D4 守卫（约 2978 行）保持不动，新执行器对 tracked 桶信号显式拒绝零 git 写
- [ ] 3.2 core/dashboard/data/adjudication_choices.py：仿既有登记模式（约 119/313 行）为 maintree_untracked_stray_escalated 登记三种裁决选项

## 4. 测试

- [ ] 4.1 tests/test_maintree_stray_wip_sweep.py：覆盖第二档升级（24h 触发、体积阈值触发、只升级一次、info 信号本身仍一次性不重复告警）；TestAdminMonitorRegistration 两例随新信号类型同步
- [ ] 4.2 tests/test_stray_untrack_remediation.py：覆盖新认领执行器对 tracked 桶信号拒绝零 git 写，以及归档/ignore/删除三种裁决的落盘行为
