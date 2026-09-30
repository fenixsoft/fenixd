# spec/knowledge/ —— 项目知识真相源（目录契约）

本目录是 Fenix 项目知识的**真相源**（knowledge atlas）：按能力域组织的、只装
**当前业务规则**的、人类可读性优先的常驻知识层。归档目录 `spec/archive/` 继续
承担「历史过程」职责；本目录承担「现在是什么规则」职责，两者以溯源链接连接。

- 总目录：`index.md` ——第 1 行标题恒为 `# 知识真相源`，第 2 行整源盖戳行
  `> 最后更新：<YYYY-MM-DD HH:MM> UTC`（整个真相源最后更新时间，每次蒸馏刷新）；
  「能力域」节以表格列出全部能力域（表头
  `| 能力域 | 简介 | 能力数量 | 更新时间 |`：域名链接 + 各域一行简介 +
  能力数纯数字 + 该域最后更新时间 `YYYY-MM-DD HH:MM`）。
- 能力页：`domains/<域>/<能力>.md` ——一个能力一页，域为能力的业务聚类
  （域清单由蒸馏 agent 自动聚类生成，不预先人工定义；域内导航页为
  `domains/<域>/_domain.md`：第 1 行 `# <域名>`，第 2 行该域盖戳行
  `> 最后更新：<YYYY-MM-DD HH:MM> UTC`，由蒸馏管线在域内容变化时刷新；
  「能力页」节以表格列出：表头 `| 能力页 | 简介 |`，能力页名链接 + 一句话简介）。
- **盖戳纪律**：盖戳时间由管线动态段注入的当前 UTC 时间为准（蒸馏 run 与
  回填/史前车道各自的拼装函数注入），LLM 不得自报时间；校验器
  （`validate_knowledge`）拦截标题、盖戳行与四列表的时间格式漂移。
- 决策索引：`adr/index.md`（编号、状态、一句话摘要）与
  `adr/ADR-NNN-<标题>.md`（决策条目）。
  （关系图 `graph/` 产物已随 graphify 功能取消停止生成——2026-09-29；存量目录
  保留但不再更新，亦不属于本目录契约的一部分。）

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
- **溯源行格式**：`- [<归档日期> <spec名>](spec/archive/<完整归档目录名>/) —
  <该归档对本页做了什么>`；链接文本的 spec 名为归档目录名剥日期前缀，
  dashboard 由此链接弹出归档 SPEC 文档。史前复原行、`git:` 复原行无对应
  归档目录，保持纯文本。REMOVED 语义在该段留一行
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
- `adr/index.md` 表格列出全部 ADR 及状态（accepted 与 superseded 均在列，
  供溯源）：表头 `| 编号 | 状态 | 摘要 |`，编号链接 + 状态 + 一句话摘要。

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

## 域命名映射表（首跑自举登记）

下表由存量回填首跑（模式一：聚类自举）登记，记录域目录名 → 业务含义，
是唯一一次对 README 的写入；后续蒸馏只读此表，不改本节。

| 域目录 | 业务含义 |
| --- | --- |
| project-management | 项目接入与生命周期：项目发现注册、描述、生命周期控制与冻结停机 |
| planning-generation | 规划与出题：SPEC 生成、路由地图、生成节流与 planready 产物门 |
| spec-lifecycle | SPEC 生命周期：审批、评审门、晋升、调度拾取、冻结与归档 |
| dispatch-scheduling | 调度与派发：优先级并行调度、并发度、队列治理与事件投递 |
| implementer-lane | 实现车道：implementer 任务协议、交付物声明门禁与任务进度回写 |
| verify-pipeline | 验证管线：契约、场景治理、执行引擎与验证报告 |
| verdict-adjudication | 验证裁决：judge 产物门、证据分类与裁决结果完整性 |
| code-review-lane | 代码审查：审查 agent、台账条目、实现期审查门与 OCR 并行车道 |
| code-fix-lane | 缺陷修复：code-fix 车道、CR 台账修复批与修复族收敛 |
| agent-runtime | Agent 运行时：进程托管、提示词注入、运行参数与工具效率 |
| run-resilience | 运行守护与失败韧性：超时监督、失败分类、预算与状态写入防线 |
| recovery-continuity | 中断恢复与续做：恢复保全、分支锚定、重试与断点续跑 |
| worktree-vc | 工作树与版本控制：worktree 隔离、merge-back 与 stash 冲突处置 |
| daemon-runtime | 守护进程平台：单例、健康、排水与 supervisor 托管 |
| provider-models | 模型网关与配置：provider 链、故障熔断退避、模型分配与配置分级 |
| cost-observability | 成本与可观测：成本治理、耗时与延迟观测、run 记录可读性 |
| dashboard-frontend | 仪表盘前端：页面、页签、弹窗与主题等交互体验 |
| dashboard-platform | 仪表盘服务：服务端、SSE 实时通道、增量索引与实例生命周期 |
| mobile-adaptation | 移动端适配：断点、密度与触控目标的响应式适配 |
| admin-ops | 管理员运营：admin agent、处置活动、人工裁决与告警处置 |
| self-evolution | 自省与自进化：每日自省、改进建议、陈旧代码自愈与 DFX 看护 |
| test-engineering | 测试工程：测试隔离、替身保真、回归三段与 fixture 治理 |
| codebase-structure | 代码结构治理：包结构、门面契约与巨型类/长函数拆分 |
| docs-help | 帮助与文档：帮助中心、文档机制与保障机制专章 |

域归位的机器可读清单（能力 → 域）见 `.fenix/knowledge_backfill_domains.json`。
