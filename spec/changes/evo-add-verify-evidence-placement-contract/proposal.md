# add-verify-evidence-placement-contract

## 背景

potplayer-base 主树根 verify-evidence/ 堆积 6 个 untracked 子目录＋14 个散文件（neutralize-pack-static-fingerprints 验证收尾产物，mtime 集中 10-04 00:49–01:19 本地），报告入库（ec7ec38，core/verify_report.py:961 严格单文件 pathspec）未随附原始证据。框架全域无证据落位约定：grep verify-evidence /root/fenixd/core 零命中、verify_contract.py 无证据字段——散落是验证 agent 自发行为。滞留盘点 tracked-only（core/worktree_manager/stray_wip.py:151-162），untracked 形态零告警、永久滞留；同类 tracked 散件的 admin 代查代价实测 6.6-13.5 分钟/次。

## 目标

1. 证据落位契约：验证/核查原始证据统一落 .fenix/verify-evidence/<spec>/（.fenix/* 已被消费项目忽略规则覆盖，零 .gitignore 成本），契约经验证链契约字段与指引下发。
2. untracked 散件盘点信号：maintree 盘点增补 entry 级 untracked 口径，超阈值且滞留时发一次性告警（只告警不处置），豁免 .fenix/ 有意放行项与已 ignore 路径。

## 非目标

- 不改 verify_report.py 严格单文件入库 pathspec（「随报告入库 evidence/」形态弃用——该 pathspec 有「不卷入其它 spec 在途草案」的防污染约束）。
- 不处置消费项目现存散件的一次性清理（potplayer-base 侧人工动作：现存 20 个 untracked 条目挪位）。

## 验收

- 验证 run 的证据产物默认落 .fenix/verify-evidence/<spec>/，主树根不再出现证据散件、git status 长尾不再被污染。
- 构造主树 untracked 散件：发一次告警、同指纹不重复、指纹消失自动复位；.fenix/ negation 放行项与 ignored 路径不误报；verify-evidence/ 内已 tracked 条目不误报（entry 级判定）。
- 既有 maintree stray sweep 与 verify contract 相关测试不回退。