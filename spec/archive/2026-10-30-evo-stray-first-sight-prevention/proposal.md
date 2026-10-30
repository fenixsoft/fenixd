## Why

主树散件治理三起同型损失全部走「产物滞留→告警→升级→被动 ignore」被动链路，累计烧掉约 $3.7 管理员处置成本与多日主树 git status 污染：

1. 10-03→10-08 历史验证证据散件 90 entry/509MB 滞留约 5 天后归档处置（run admin-potplayer-base-1791485794，$1.51287/32 次工具调用，归档目录 stray-archive/20261008T185520Z 现存）。
2. build-win-configure.log 10-04 入库后三度烧 admin 处置（10-04 run admin-potplayer-base-1791048866 $0.78/12 轮、10-06 run admin-potplayer-base-1791275605 $0.92/11 轮、10-10 两 run 合计约 862 秒），10-10 由提交 a47a56a/151ff6e 根治。
3. .debug/ 调试产物 9 entry/49-51MB 滞留 25.9-28.5 小时（告警 21c165e39b42/d9df508ec2b0/b1b9391b3295），run admin-potplayer-base-1791787013（$0.452301/12 次工具调用）执行 ignore_untracked_stray，提交 913f41b 根治。

框架盘点→升级→认领闭环齐全（stray_wip.py + admin_monitor.py + adjudication_choices.py）但纯被动：major 升级要滞留 24 小时（UNTRACKED_ESCALATION_STALE_MINUTES=24*60，stray_wip.py:77）或体积超 500MB；且 sweep 对低于 entry 阈值（5）的集合直接静默返回（stray_wip.py:768/796 below_threshold 早退）——小型散件集连 info 提示都没有。交付侧同样无检查点：deliverables.py 的 check-ignore 逻辑方向相反（校验声明的交付路径不得被 ignore），不检查运行时落盘路径是否有覆盖；receiver 的 exe 相邻写盘路径至今无名字级 ignore，只因 exe 恰部署在已忽略目录而被间接覆盖。两次根治提交均自述「按先例」，被动模式在自我复制。

## What Changes

1. 盘点首现提示：untracked 散件盘点对「登记表无 first_seen 记录、未被 .gitignore 覆盖的目录型产物集合」即时发一次 info 级首现提示（kind=maintree_untracked_stray_first_sight），携带预防性 .gitignore 条目草案与成因注释；低于 entry 阈值的集合同样提示——填补 below_threshold 静默缺口。同目录仅提示一次；目录消失走既有复位逻辑，复位后再现视为新首现。首现提示不启动升级时钟、不进自动唤起收录。
2. 交付侧检查点：implementer 交付契约（agents/implementer.md）收尾检查清单新增——交付引入运行时落盘路径（日志、dump、产物目录）且落在仓库树内时，同提交追加对应 .gitignore 覆盖或将默认落盘路径移出仓库树，提交前 git status 自查零 untracked 产物。

## Capabilities

### New Capabilities
- `stray-first-sight-prevention`: 运行时产物散件的首现预防——盘点对新型产物目录首现即提示预防性 ignore，交付契约含落盘路径覆盖检查点

### Modified Capabilities

（无——maintree_untracked_stray_stale 与 maintree_untracked_stray_escalated 既有语义不动）

## Out of Scope

- 不动 24 小时升级阈值（stray_wip.py:77）、500MB 体积阈值与 5 entry info 阈值的既有语义。
- 不动 evo-recurring-stray-remediation 的复发处置强制语义——该 spec 治「第 2 次起的处置当场根治」，本 SPEC 治「第 1 次的首现预防提示」，相邻环节互补不重叠。
- 不跨仓改动：potplayer-base 的 .debug/ 已由其仓内提交 913f41b 落地 ignore；evo-ignore-receiver-debug-artifacts 的一次性免疫条目不动。
- 不做散件自动 ignore（提示与交付检查点均为建议面，ignore 动作仍走既有裁决执行器，避免盘点获得写副作用）。

## Impact

- **改动**：core/worktree_manager/stray_wip.py 盘点函数与登记表复用（first_seen/指纹持久化已由 evo-persist-stray-escalation-clock 落地）、agents/implementer.md 模板一段、新增 tests/test_stray_first_sight_prevention.py。
- **预期收益**：同型散件事件从「24 小时滞留 + 升级告警 + admin 处置 run（实测每起 $0.45-$1.51）」塌缩为「首现即提示 + 预防性 ignore 一行」；三起历史损失形态（含 10-08 大宗归档的早期留痕阶段）均可在首现当天以近零成本消除。
- **风险有界**：首现提示同目录仅一次且不自动唤起，最坏情况是告警面板多一行 info；既有升级路径行为不回归由测试钉住。