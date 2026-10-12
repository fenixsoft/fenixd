# Design

## 现状与缺口

- 盘点链路：core/worktree_manager/stray_wip.py 的 untracked 盘点（source=maintree-stray-wip-sweep）产出 info 档 maintree_untracked_stray_stale（宽限 30 分钟、entry 阈值 5，stray_wip.py:85/88）→ 滞留 24 小时（UNTRACKED_ESCALATION_STALE_MINUTES=24*60，stray_wip.py:77）或体积超 500MB 升级 maintree_untracked_stray_escalated → admin_monitor.py 三表登记 → adjudication_choices.py 的 archive/ignore/delete 三裁决。
- 缺口一：stray_wip.py:768 计算 below_threshold = count < threshold，795-796 行 below_threshold 时直接返回——低于 5 entry 的散件集合不发任何信号。
- 缺口二：无「首现」概念：持久化登记表（first_seen/指纹，evo-persist-stray-escalation-clock 已落地）只服务于升级计时，目录型集合第 1 次出现与第 N 次出现行为相同。
- 缺口三：交付契约无落盘覆盖检查点：agents/implementer.md 无「运行时产物写仓库树内须同提交 ignore」要求；core/deliverables.py 的 check-ignore 方向相反（防交付路径被 ignore），不能复用。

## 方案

### 1. 首现提示（stray_wip.py + core/admin_monitor.py 两表登记）

- 归组约定（既有盘点无归组，须新增）：``_untracked_stray_entries`` 产出全量扁平文件清单（stray_wip.py:694 sorted 返回、:443 单点进 ``_untracked_signal``），首现判定按「目录型产物集合的规范化根目录」归组——同一新建产物目录下的散件条目归为一个集合；顶层散文件（无共同新建目录，如历史上入库的 build-win-configure.log 形态）不在首现提示面，仍走既有阈值流。
- 在归组结果上、below_threshold 早退（stray_wip.py:795-796）之前插入首现判定：对每个目录集合，若首现登记无该目录记录，发 info 级首现提示信号 maintree_untracked_stray_first_sight，evidence 携带目录清单、总体积、gitignore 草案行（目录路径 + 中文成因注释，对齐既有 913f41b/151ff6e 的注释风格）。ignore 豁免无须重复判定——进入 ``_untracked_signal`` 的条目已由上游 ``_untracked_stray_entries`` 排除已 ignore 与 negation 放行项（豁免①②），首现集合天然未被 .gitignore 覆盖。
- 去重键为目录路径，MUST NOT 复用条目集指纹：既有登记表按 ``_untracked_fingerprint`` 双层指纹为键（stray_wip.py:773，低于阈值=路径集哈希、越阈=含内容 sha256），集合增删或跨档切换都换键，按指纹去重会在散件增长时重复提示；且 ``_reset_untracked_registry_absent({fp})``（stray_wip.py:794）只保留当轮指纹、清除其余条目，目录级条目混入同表会被每轮清除。首现登记用独立目录键结构（同持久化文件 .fenix/stray_untracked_registry.json 承载、读写与字段适配同步），复位判据=该目录整轮不再贡献 untracked 散件条目（同 absent 复位模式），复位后再现视为新首现；同目录仅提示一次，集合内容增长（指纹漂移）不视为新首现。
- 首现提示不写入升级计时语义（不改变 24 小时/体积阈值的既有起点）。信号登记面：在 admin_monitor.py SIGNAL_SEVERITY + SIGNAL_RECOMMENDATION 两表登记（info 先例 maintree_untracked_stray_stale，admin_monitor.py:359/459；stray_wip.py:50-56 注释即两表登记约定），MUST NOT 收录 STORED_SIGNAL_TYPES（admin_monitor.py:507，不自动唤起 admin run——否则提示本身就变成新的浪费形态）；消费面为告警面板展示与后续评审/处置的背景信息。
- 排除集沿用既有散件判定名单（.fenix/、系统临时目录等），不另立名单，避免双源漂移。

### 2. 交付检查点（agents/implementer.md）

- 收尾检查清单新增一条：交付引入运行时落盘路径（日志、dump、产物目录）且落在仓库树内时，同提交追加对应 .gitignore 覆盖或将默认落盘路径移出仓库树（树内固定位置如 build/ 已忽略的可复用既有规则）；提交前 git status 自查零 untracked 产物。
- 措辞为 MUST 级检查项，与既有「不动 .debug/ 等既有产物」类条款并列，不引入新的评审环节。

### 3. 测试（tests/test_stray_first_sight_prevention.py）

- 首现触发：新目录集合、低于 entry 阈值也提示；gitignore 已覆盖不提示。
- 去重与复位：同目录仅一次；目录消失复位后再现重提示；跨重启不重复。
- 非回归：既有 stale/escalated 升级路径、阈值语义、登记表复位行为不变。

## 风险与对策

- 提示泛滥：同目录仅一次 + 复位门槛（目录整轮不再贡献散件条目才复位）约束量级；info 级不自动唤起，最坏情况是告警面板多一行。
- 误报首现：排除集复用既有名单；check-ignore 命中即跳过，不会对已免疫目录重复提示。
- 与 evo-recurring-stray-remediation 交互：该 spec 的 untrack 根治执行器消费的是 stale/escalated 信号，本 SPEC 的 first_sight 信号不在其消费面内，两者无注册表冲突；若首现提示被采纳为预防性 ignore，复发处置强制的触发频次自然下降。