## 1. 章节编号迁移与断链清零

- [ ] 1.1 git mv 重命名四文件：07-dashboard.md→08-dashboard.md、08-config.md→09-config.md、09-artifacts.md→10-artifacts.md、10-faq.md→11-faq.md
- [ ] 1.2 修订 docs/help/ 全部交叉引用（11 个文件约 35 处，含 `08-config.md#hooks`、`08-config.md#模板值与代码缺省不一致` 等 `#锚点` 链接），完成后 grep 四个旧文件名全目录零命中
- [ ] 1.3 README 导语段落与「完整目录」表更新为 11 章新编号，目录表新增第 07 章「保障机制」条目（一句话简介）

## 2. 机制盘点与第 07 章写作

- [ ] 2.1 对照代码盘点五类机制全集：`core/deliverables.py`（声明 lint/收工守卫）、`core/pm_engine/promotion.py`（晋升 lint）、`core/verdict_check.py`（产物硬门）、`core/state_machine.py`（转移门）、`core/verify_engine/env_gate.py`（环境门）、`.fenix/hooks/`（PreToolUse 拦截/出题分批）、恢复/清扫/watchdog/重启协议自愈链路、`core/alert_lifecycle.py` 与 `core/admin_monitor.py`（告警）；逐项核对模块、配置键、触发点与违规后果，剔除已退役机制
- [ ] 2.2 撰写 `docs/help/07-safeguards.md`：lint/门禁/守卫/自愈/告警五类各成小节，每个机制条目讲清目的（防御哪类真实事故）、原理（怎么工作）、控制点（在哪拦截/检查什么/违规后果）三要素；散文体充分展开——段落多句连贯、有因果与递进衔接，不得以短句罗列或清单为小节主体（表格仅作辅助汇总）；机制之间以纵深防御叙事衔接
- [ ] 2.3 章内提及的每个配置键、模块/文件名、hook 名逐一 grep 实证存在，零幻觉条目

## 3. 与 06 章分工边界与收尾校验

- [ ] 3.1 新章不展开运维参数数值（预算数量、退避秒数、告警阈值等），以交叉引用指向 06 章；06 章加指向新章的交叉链接（头部或相关小节）
- [ ] 3.2 全章通读终检：五类机制齐全、控制点三要素完整、文风符合散文体要求（无罗列主体、无草草收束的短段落）、docs/help/ 全目录无旧编号断链

## Deliverables

```yaml
- path: docs/help/07-safeguards.md
  kind: new
- path: docs/help/08-dashboard.md
  kind: new
- path: docs/help/09-config.md
  kind: new
- path: docs/help/10-artifacts.md
  kind: new
- path: docs/help/11-faq.md
  kind: new
- path: docs/help/README.md
  kind: modify
- path: docs/help/01-quick-start.md
  kind: modify
- path: docs/help/02-concepts.md
  kind: modify
- path: docs/help/03-lifecycle.md
  kind: modify
- path: docs/help/04-cli.md
  kind: modify
- path: docs/help/05-verification.md
  kind: modify
- path: docs/help/06-governance.md
  kind: modify
```
