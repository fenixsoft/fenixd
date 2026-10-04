## ADDED Requirements

### Requirement: 真相源目录结构

系统 SHALL 在仓库内维护 `spec/knowledge/` 作为项目知识真相源目录，结构为：`index.md`（总目录，列出全部能力域及各域一行简介与链接）、`domains/<域>/<能力>.md`（一个能力一页，域为能力的业务聚类）、`adr/index.md`（ADR 索引：编号、状态、一句话）与 `adr/ADR-NNN-<标题>.md`（决策条目）、`README.md`（目录契约说明）。能力域清单由蒸馏 agent 自动聚类生成，不预先人工定义。`spec/knowledge/` SHALL 入库（git tracked），首次蒸馏运行前允许只含 README.md 骨架。

#### Scenario: 首次初始化后目录骨架存在且入库

- **WHEN** 本 SPEC 实现合并后查看仓库
- **THEN** `spec/knowledge/README.md` 存在且说明目录契约，`spec/knowledge/` 已被 git 跟踪；`index.md`、`domains/`、`adr/` 尚不存在时不视为违规（它们由首个蒸馏 run 产出）

#### Scenario: 能力页按域归位

- **WHEN** 蒸馏 run 处理一个归档 SPEC 且其 delta 涉及能力 `scheduled-spec-pickup`
- **THEN** 该能力的规则落位于 `spec/knowledge/domains/<某域>/scheduled-spec-pickup.md`，`index.md` 中能沿「域 → 能力」两级链接导航到该页

### Requirement: 能力页契约（人类可读性优先）

能力页 SHALL 为 Markdown 文件并遵循统一结构：H1 标题为能力名（中文表述）、紧随其后的 HTML 注释 marker（机器接口）、角色一句话、`## 规则` 段（当前生效的业务规则）、`## 关键行为` 段（主干行为，可选）、`## 溯源` 段（来源列表）。规则内容 SHALL 为蒸馏 agent 以一致语言风格**重写的当前事实**，MUST NOT 机械搬运 delta 原文或保留「本 SPEC 新增了」等历史叙述措辞；历史演变过程只允许出现在溯源段。溯源段每行 SHALL 为 `- <归档日期> <归档目录名> — <该归档对本页做了什么>` 格式，链接目标为 `spec/archive/<日期-名>/`。

marker SHALL 为紧随 H1 的 HTML 注释，格式固定为：

```
<!-- knowledge: capability=<能力kebab名> rev=<整数,初始1>
     sources=spec/archive/<名1>[,spec/archive/<名2>...] -->
```

#### Scenario: 能力页内容可读且无历史措辞

- **WHEN** 人类读者打开任一能力页
- **THEN** 页面以散文陈述「系统现在如何工作」，读到的规则不含「新增了/修复了/原先是」等变更叙述；该能力的演变历史只在溯源段可见

能力页因 150 行硬顶拆为主从分片时，marker SHALL 增加可选 `part=<n>` 字段：同能力各分片 capability 名保持一致，主页省略 part、从页 `part=2/3/...`，rev 与 sources 主从一致；合并语义按 capability 名聚合、整体重写该能力全部分片。

#### Scenario: marker 机器可解析

- **WHEN** 校验脚本解析某能力页 marker
- **THEN** 能提取出 capability 名、rev 整数、sources 列表，且 sources 中每个路径都指向真实存在的 `spec/archive/` 子目录

### Requirement: 单页行数硬顶

单个能力页文件 SHALL 不超过 150 行（含 marker 与溯源段）。蒸馏产出的页面超顶时，蒸馏管线 SHALL 处置而非放行：优先将能力拆为多页（主从页互链），无法拆分时精简规则表述。该上限是防真相源膨胀的物理约束。

#### Scenario: 蒸馏产出超顶页被拦截

- **WHEN** 蒸馏 run 产出的能力页超过 150 行且收尾校验运行
- **THEN** 校验报告违规，蒸馏 run 必须拆页或精简后重写该页，最终落盘版本不超过 150 行
