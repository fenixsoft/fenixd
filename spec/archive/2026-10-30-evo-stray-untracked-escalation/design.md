# 设计：stray-untracked-escalation

## 根因与断链点

info 级 untracked 信号被显式排除在自动唤起通道外（设计裁定），且缺第二档升级、缺体积数据源、缺适用执行器——三处均为增量建设而非改错。

## 方案

1. core/worktree_manager/stray_wip.py：_untracked_stray_entries（约 404 行）采集体积；untracked 盘点流（约 504-565 行）加第二档判定（elapsed≥24h 或体积≥阈值，阈值仿 untracked_stray_threshold :81 的可配范式，缺省 500MB）；_untracked_registry（约 157 行）加双档 escalated 标记；新信号 maintree_untracked_stray_escalated 按 :611 写告警处参数化 severity。
2. core/admin_monitor.py：SIGNAL_SEVERITY（约 290 行）、SIGNAL_RECOMMENDATION（约 390 行，文案仿 tracked 桶 major 模板 :440——写入方 _write_alert 与唤起记录 recommended_action（:2708 .get 查表）均从该表取值，漏登则告警无处置指引）、STORED_SIGNAL_TYPES（约 481 行）、_detect_family_explosion 项目名解析清单（约 2519 行旁）四处同步登记新类型。
3. core/dashboard/data/admin_actions.py：新增 untracked 认领执行器，复用 _latest_stray_wip_manifest 清单段解析与 _append_gitignore_entries/_path_already_ignored（约 2908-2944 行）；保持 _exec_untrack_stray_wip D4 守卫（约 2978 行）不动。
4. core/dashboard/data/adjudication_choices.py：按既有模式（约 119/313 行）登记三裁决选项。

## 关键取舍

- 新设第二信号类型而非直接收录现 info 信号：须同步修订 admin_monitor.py:352-356 与 stray_wip.py:31-35 的 MUST NOT 收录注释，注明「info 信号维持不收录、升级信号除外」——该裁定出自 evo-add-verify-evidence-placement-contract design.md:15，本提案即其显式修订。
- 认领不复用 untrack 执行器：git rm --cached 对 untracked 路径无语义，D4 守卫语义也不同。
- 体积计算对大盘点集合的成本：升级判定每轮对已告警在册的滞留集合执行（经 entry 阈值门控后在册集合规模小，du 成本可负担），不在全量散件上每轮 du；体积路径独立于 elapsed 判定——MUST NOT 以「elapsed 达标后才计算体积」实现之，否则体积超限的集合被额外门控在 24h 之内，与「elapsed 或体积」的或语义相抵。

## 风险

- _detect_family_explosion 项目名解析清单漏加新类型会导致 spec=None 记录被丢弃、唤起静默落空（源码注释点名的同款坑）——以测试钉住。
- 自动唤起放大误报面：升级信号保留同指纹一次性与双档标记两重兜底。