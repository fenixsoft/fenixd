# Design

## 现状与缺口

- 盘点链路：core/worktree_manager/stray_wip.py 的 untracked 盘点（source=maintree-stray-wip-sweep）产出 info 档 maintree_untracked_stray_stale（宽限 30 分钟、entry 阈值 5，stray_wip.py:85/88）→ 滞留 24 小时（UNTRACKED_ESCALATION_STALE_MINUTES=24*60，stray_wip.py:77）或体积超 500MB 升级 maintree_untracked_stray_escalated → admin_monitor.py 三表登记 → adjudication_choices.py 的 archive/ignore/delete 三裁决。
- 缺口一：stray_wip.py:769 计算 below_threshold = count < threshold，796 行 below_threshold 时直接返回——低于 5 entry 的散件集合不发任何信号。
- 缺口二：无「首现」概念：持久化登记表（first_seen/指纹，evo-persist-stray-escalation-clock 已落地）只服务于升级计时，目录型集合第 1 次出现与第 N 次出现行为相同。
- 缺口三：交付契约无落盘覆盖检查点：agents/implementer.md 无「运行时产物写仓库树内须同提交 ignore」要求；core/deliverables.py 的 check-ignore 方向相反（防交付路径被 ignore），不能复用。

## 方案

### 1. 首现提示（stray_wip.py）

- 在 untracked 盘点完成归组后、below_threshold 早退（796 行）之前插入首现判定：对每个目录型产物集合计算目录指纹，若登记表无 first_seen 记录且集合内路径均未被 .gitignore 覆盖（check-ignore 批量判定），发 info 级首现提示信号 maintree_untracked_stray_first_sight。
- 提示 evidence 携带：目录清单、总体积、gitignore 草案行（目录路径 + 中文成因注释，对齐既有 913f41b/151ff6e 的注释风格）。
- 首现即写登记表（first_seen/指纹），复用既有持久化；同目录不重复提示；目录消失走既有 _reset_untracked_registry_absent 复位，复位后再现视为新首现。
- 首现提示不写入升级计时语义（不改变 24 小时/体积阈值的既有起点），不加入 STORED_SIGNAL_TYPES（不自动唤起 admin run——否则提示本身就变成新的浪费形态）；消费面为告警面板展示与后续评审/处置的背景信息。
- 排除集沿用既有散件判定名单（.fenix/、系统临时目录等），不另立名单，避免双源漂移。

### 2. 交付检查点（agents/implementer.md）

- 收尾检查清单新增一条：交付引入运行时落盘路径（日志、dump、产物目录）且落在仓库树内时，同提交追加对应 .gitignore 覆盖或将默认落盘路径移出仓库树（树内固定位置如 build/ 已忽略的可复用既有规则）；提交前 git status 自查零 untracked 产物。
- 措辞为 MUST 级检查项，与既有「不动 .debug/ 等既有产物」类条款并列，不引入新的评审环节。

### 3. 测试（tests/test_stray_first_sight_prevention.py）

- 首现触发：新目录集合、低于 entry 阈值也提示；gitignore 已覆盖不提示。
- 去重与复位：同目录仅一次；目录消失复位后再现重提示；跨重启不重复。
- 非回归：既有 stale/escalated 升级路径、阈值语义、登记表复位行为不变。

## 风险与对策

- 提示泛滥：同目录仅一次 + 复位门槛（目录消失才复位）约束量级；info 级不自动唤起，最坏情况是告警面板多一行。
- 误报首现：排除集复用既有名单；check-ignore 命中即跳过，不会对已免疫目录重复提示。
- 与 evo-recurring-stray-remediation 交互：该 spec 的 untrack 根治执行器消费的是 stale/escalated 信号，本 SPEC 的 first_sight 信号不在其消费面内，两者无注册表冲突；若首现提示被采纳为预防性 ignore，复发处置强制的触发频次自然下降。