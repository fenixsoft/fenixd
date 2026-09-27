# spec/knowledge/ —— 项目知识真相源（目录契约）

本目录是 Fenix 项目知识的**真相源**（knowledge atlas）：按能力域组织的、只装
**当前业务规则**的、人类可读性优先的常驻知识层。归档目录 `spec/archive/` 继续
承担「历史过程」职责；本目录承担「现在是什么规则」职责，两者以溯源链接连接。

- 总目录：`index.md` ——列出全部能力域及各域一行简介与链接。
- 能力页：`domains/<域>/<能力>.md` ——一个能力一页，域为能力的业务聚类
  （域清单由蒸馏 agent 自动聚类生成，不预先人工定义；域内导航页为
  `domains/<域>/_domain.md`）。
- 决策索引：`adr/index.md`（编号、状态、一句话摘要）与
  `adr/ADR-NNN-<标题>.md`（决策条目）。
- 关系图（预留）：`graph/graph.html` ——由后续 SPEC（add-knowledge-atlas-maintenance）
  生成；本目录不产出该文件。

`index.md`、`domains/`、`adr/` 由首个蒸馏 run 产出；首次运行前允许本目录只含
本 README（git 不跟踪空目录）。本目录整体入库（git tracked）。

## 能力页契约（人类可读性优先）

能力页为 Markdown 文件，统一结构：

```
# <能力名（中文表述）>
<!-- knowledge: capability=<能力kebab名> rev=<整数,初始1>
     sources=spec/archive/<名1>[,spec/archive/<名2>...] -->

<角色一句话：这个能力在系统里是干什么的>

## 规则

<当前生效的业务规则，散文重写>

## 关键行为

<主干行为（可选段）>

## 溯源

- <归档日期> <归档目录名> — <该归档对本页做了什么>
```

- **marker 是机器接口**：紧随 H1 的 HTML 注释，人读时隐形、脚本可解析。字段：
  - `capability`：能力 kebab 名（合并与主从分片聚合的键）；
  - `rev`：整数，初始 1，每次 MODIFIED 覆盖写加 1；
  - `sources`：逗号分隔的归档目录相对路径列表（`spec/archive/<名>`），每个路径
    MUST 指向真实存在的 `spec/archive/` 子目录（校验脚本拦截悬空链接）；
  - `part`：可选。单页超 150 行硬顶拆为主从分片时使用——主页省略 part、
    从页 `part=2/3/...`；同能力各分片 capability 名保持一致，rev 与 sources
    主从一致；合并语义按 capability 名聚合、整体重写该能力全部分片。
- **散文是人类接口**：`## 规则` 段是蒸馏 agent 以一致语言风格**重写的当前事实**，
  禁止机械搬运 delta 原文、禁止「本 SPEC 新增了 / 修复了 / 原先是」等历史叙述
  措辞——历史演变只允许出现在溯源段。读者打开任一能力页应读到「系统现在如何
  工作」。
- **溯源行格式**：`- <归档日期> <归档目录名> — <该归档对本页做了什么>`，链接
  目标为 `spec/archive/<日期-名>/`。REMOVED 语义在该段留一行
  「已随 <归档名> 废除」。

## 单页 150 行硬顶

单个能力页文件不超过 **150 行**（含 marker 与溯源段）。蒸馏产出超顶时蒸馏管线
处置而非放行：优先将能力拆为多页（主从页互链），无法拆分时精简规则表述。该上限
是防真相源膨胀的物理约束，校验脚本拦截超顶页（拒绝落盘）。

## ADR 索引契约

- 条目：`adr/ADR-NNN-<标题>.md`，NNN 为三位递增编号（由蒸馏管线脚本分配，避免
  并发撞号）。
- 三段式：`## Context`（问题背景）、`## Decision`（裁定）、`## Consequences`
  （后果与代价）；头部含状态行（`status: accepted | superseded`）与日期。
- 收录判据（高门槛，宁缺勿滥）：仅收录**跨 SPEC 影响架构走向**的决策——约束
  后续 SPEC 实现空间、或确立跨模块机制选型（如「车道隔离必须走 spawn 点注入」
  级别）；单 SPEC 内部实现取舍（布局、命名）不收录。一个归档 SPEC 允许零产出。
- **不可变性**：ADR 一经落盘视为不可变文档；后续蒸馏不得改写已 accepted 的 ADR
  正文（校验脚本 diff 旧正文，任何变更即违规）。
- **Supersede 链（取代不改写）**：新 ADR 推翻旧裁定时只做两处标记——旧 ADR 头部
  状态改为 `status: superseded` 并追加一行 `Superseded by: ADR-NNN(新条目)`；
  `adr/index.md` 中旧条目状态同步。旧 ADR 三段正文保持原样。
- `adr/index.md` 按编号列出全部 ADR 及状态（accepted 与 superseded 均在列，
  供溯源），含编号、标题、状态与一句话摘要。

## 蒸馏管线与校验

SPEC 归档（手工与 daemon 自动两条路径）完成后自动派发一次蒸馏 run：读归档 SPEC
的 `specs/` delta 与 `proposal.md` 摘要，按 ADDED / MODIFIED / REMOVED 语义重写
受影响能力页（后写覆盖前写，非机械拼接），更新域清单与总目录。落盘前经确定性
校验脚本（`core/knowledge.py::validate_knowledge`）检查：marker 可解析、sources
指向真实归档目录、单页 ≤150 行、index/_domain/adr 链接可解析、accepted ADR 正文
不可变、Superseded by 指向存在条目。校验通过后由管线自动提交（commit 形如
`[fenix] knowledge: distill <归档名>`）。

配置开关 `knowledge.enabled`（缺省 true，Dashboard 设置页可改）：false 时归档
不派发蒸馏，项目知识页签显示禁用占位。
