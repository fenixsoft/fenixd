# docs-safeguards-chapter 能力规范

## ADDED Requirements

### Requirement: 保障机制专章的存在与章节编号迁移

帮助文档 MUST 新增 `docs/help/07-safeguards.md`（「保障机制」章），插入为第 07 章；原 07–10 章 MUST 顺延重命名为 08–11（07-dashboard.md→08-dashboard.md、08-config.md→09-config.md、09-artifacts.md→10-artifacts.md、10-faq.md→11-faq.md），使用 git 保留文件历史。README 的完整目录表 MUST 反映 11 章新编号并含新章条目。

#### Scenario: 新章就位且重编号完成

- **WHEN** 检查 docs/help/ 目录
- **THEN** `07-safeguards.md` 存在且为唯一新增章节文件；`08-dashboard.md`、`09-config.md`、`10-artifacts.md`、`11-faq.md` 存在；旧的 `07-dashboard.md`、`08-config.md`、`09-artifacts.md`、`10-faq.md` 不存在

#### Scenario: 交叉引用零断链

- **WHEN** 对 docs/help/ 全目录 grep 旧文件名（`07-dashboard.md`、`08-config.md`、`09-artifacts.md`、`10-faq.md`）
- **THEN** 零命中（含 `#锚点` 形式的链接）；README 导语与目录表中的链接全部指向新编号

### Requirement: 机制覆盖面与内容准确性

新章 MUST 覆盖五类保障机制：lint（交付物声明 lint、晋升 lint、任务格式解析）、门禁（产物硬门如 plan-ready/verdict、晋升门、环境门、verdict 读侧 fail-closed 等状态机转移门）、守卫（收工守卫对账、PreToolUse hook 拦截、场景出题分批等运行时守护）、自愈（boot recovery、restart 协议、run sweeper、watchdog、autostash 回收等恢复链路）、告警（分级流向、escalation 冷却）。该清单为起点不设上限：实现时 MUST 对照代码盘点，发现未列机制应纳入、已退役机制不得写入。章内出现的模块名、文件名、配置键、hook 名 MUST 在仓库中真实存在。

#### Scenario: 五类机制齐全且控制点三要素完整

- **WHEN** 阅读新章
- **THEN** lint/门禁/守卫/自愈/告警五类各有实质小节；每个机制条目说清目的（防御哪类真实事故）、原理（怎么工作）、控制点（在哪拦截/检查什么/违规后果）三要素

#### Scenario: 机制名可 grep 实证

- **WHEN** 抽取章内提到的配置键、模块/文件名、hook 名逐一在仓库 grep
- **THEN** 全部真实存在，零幻觉条目

### Requirement: 与 06 章分工边界

新章 MUST 与 06 章「调度与治理规则」按「原理/参数」分层：新章讲机制的目的、原理与控制点，不展开运维参数数值（预算数量、退避秒数、告警阈值等）；参数口径留在 06 章。两章 MUST 互相交叉引用。

#### Scenario: 参数口径不重复

- **WHEN** 对比新章与 06 章
- **THEN** 新章不含 06 章已覆盖的参数数值展开（预算数值、退避秒数、阈值表）；两章正文互有指向对方的链接

### Requirement: 写作质量——流畅散文体

新章 MUST 以面向人类的流畅散文体写作：每个机制小节以连贯段落充分展开论证，段落不得以一两句话草草收束；章节间有叙事衔接（从事故类型引出机制层次、从机制层次引出下一类）；表格与列表只作辅助汇总，MUST NOT 以清单罗列为章节主体。

#### Scenario: 段落充分展开而非罗列

- **WHEN** 审读新章正文
- **THEN** 机制讲解均为多句连贯段落（一段之内有因果/递进衔接而非并列短句堆叠）；连续的纯清单式短行不构成任何小节的主体表达
