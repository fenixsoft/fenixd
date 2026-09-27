# 知识真相源存量回填（能力聚合全链蒸馏）

你在 Fenix 项目主树根目录下工作。本次任务是「存量回填车道」的一个 run：把 `spec/archive/`
下的存量归档 SPEC 按**能力聚合**语义蒸馏进真相源 `spec/knowledge/`。

## 契约单源

目录契约、marker 格式与合并语义以 `core/knowledge_prompts/distill.md` 为准，本文件不重复
定义，只追加回填模式附加段。要点重申（与 distill.md 冲突时以 distill.md 为准）：

- 真相源目录：`spec/knowledge/index.md`、`spec/knowledge/domains/<域>/_domain.md`、
  `spec/knowledge/domains/<域>/<能力>.md`、`spec/knowledge/adr/`。
- 能力页 marker（HTML 注释，机器可解析）：
  `<!-- knowledge: capability=<能力名> rev=<N> sources=spec/archive/<归档名>,...> -->`。
- 硬顶：单页（含 marker 与溯源段）不超过 150 行；超顶须拆主从分片或精简。
- 风格禁令：禁历史叙述措辞（「曾经/后来/当时/最初」），只写现行规则；ADR 判据只收
  「跨 SPEC 影响架构走向」的机制选型，不收单 SPEC 内布局/命名取舍。

## 聚合语义（本车道核心，区别于增量蒸馏）

回填的蒸馏单元是**能力**，不是归档：一个能力的完整演变链（触碰它的全部归档 delta，
按日期升序）一次读入、**一次成文最终态页面**。禁止逐归档重放——那会产生 ×N 次中间态
重写；页内只允许出现最终生效的规则，中间态、被后续归档推翻或废除的规则一律不写。

- `rev` = 触碰该能力的归档数（链长）；
- `sources` = 全链归档路径（按日期升序完整列出，`spec/archive/<归档名>` 形态）；
- 溯源段按时间序逐行列出每个归档对该能力的贡献一句话；若该能力含史前基线，溯源段
  **首行**为史前复原行；
- delta 声明删除的规则 → 从规则段移除，仅溯源段留「已随 <归档名> 废除」行。

## 本次运行模式

{{MODE_LINE}}

## 模式一：聚类自举（bootstrap）

输入：下方完整**能力清单**（由归档链索引机械产出的全部归档 `specs/<能力>/` 目录名
并集）。逐个抽读相关归档的 `proposal.md` 标题/首段理解能力语义即可，不必通读全文。

产出（全部落盘后本 run 即结束，不要 git commit）：

1. `spec/knowledge/index.md`：真相源导航页，列出全部域与各域一句话简介；
2. 每域一份 `spec/knowledge/domains/<域>/_domain.md`：域导航页，列出该域全部能力页
   占位链接（能力页由后续批次产出，可先列条目链接）；
3. 域归位清单：把下方能力清单中的**每一个**能力分配到恰好一个域，写入
   `{{DOMAIN_MAP_PATH}}`，JSON 对象形如 `{"<能力名>": "<域目录名>", ...}`——
   域目录名用业务语言的 kebab-case 短语（如 `dashboard-ux`、`verify-pipeline`）；
   清单必须全覆盖、无遗漏、无重复。

能力清单（共 {{CAPABILITY_COUNT}} 个）：

{{CAPABILITY_LIST}}

## 模式二：能力聚合蒸馏批次（batch）

输入：本批**能力**清单（见下，每个能力标注其完整演变链，含史前基线的另附基线内容）。
逐能力把最终态页面一次成文进真相源。

批量模式附加规则：

- 逐能力按链序（日期升序）通读全部链上归档的 `specs/<能力>/spec.md` delta 与
  `proposal.md`，按上方聚合语义一次写出该能力的最终态页面（rev=链长、sources 全链、
  溯源按时间序）；
- 链头含史前基线的能力：把基线内容视为链的起点一并聚合，溯源段首行为史前复原行；
- 能力页落到域归位清单（`{{DOMAIN_MAP_PATH}}`）指定的域；清单缺项的能力，按能力语义
  自行归入最贴近的既有域；
- 不要修改 `spec/knowledge/` 之外的任何文件；不要执行 git 操作（提交由框架完成）。

本批能力清单（共 {{BATCH_SIZE}} 个）：

{{BATCH_LIST}}

## 模式三：ADR 抽取批次（adr）

输入：本批**归档**清单（均含 `design.md`）。逐归档读取 `design.md`，抽取「跨 SPEC
影响架构走向」的机制选型决策，产出 ADR 条目：

- 产物：`spec/knowledge/adr/ADR-NNN-<标题>.md`——三段式（Context/Decision/
  Consequences），头部 `date:` 与 `status: accepted` 行；编号接续 `adr/` 目录既有
  最大编号（无既有条目则从 001 起）；
- 同一决策被多个归档重复记录 → 合并为一个条目，以最终口径为准；
- 非架构级取舍（单 SPEC 内布局/命名/文案）→ 不抽取，跳过即可，不算失败；
- 同步维护 `spec/knowledge/adr/index.md`（每条目一行：编号链接、状态、一句话摘要）；
- 只动 `spec/knowledge/adr/`；已落盘 ADR 的三段正文不可改写（supersede 只允许改
  头部 status 与追加 Superseded by 行）；不要执行 git 操作。

本批归档清单（共 {{BATCH_SIZE}} 个）：

{{BATCH_LIST}}

{{VIOLATIONS_BLOCK}}

## 收尾自查（所有模式）

结束前逐项自查，任一不满足须修正后再结束：

- [ ] 新建/改动的每个能力页 marker 可解析、rev=链长、sources 完整覆盖全链且全部指向
      真实存在的 `spec/archive/<名>` 目录；
- [ ] 页内无中间态规则残留（被推翻/废除的规则不出现在规则段）；
- [ ] 单页不超 150 行；
- [ ] `index.md`、各域 `_domain.md` 与 `adr/index.md` 的链接全部可解析；
- [ ] 未触碰 `spec/knowledge/` 之外的文件。
