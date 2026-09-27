# 知识真相源存量回填（批量蒸馏）

你在 Fenix 项目主树根目录下工作。本次任务是「存量回填车道」的一个 run：把 `spec/archive/`
下的存量归档 SPEC 按批量模式蒸馏进真相源 `spec/knowledge/`。

## 契约单源

目录契约、marker 格式与合并语义以 `core/knowledge_prompts/distill.md` 为准，本文件不重复
定义，只追加批量模式附加段。要点重申（与 distill.md 冲突时以 distill.md 为准）：

- 真相源目录：`spec/knowledge/index.md`、`spec/knowledge/domains/<域>/_domain.md`、
  `spec/knowledge/domains/<域>/<能力>.md`、`spec/knowledge/adr/`。
- 能力页 marker（HTML 注释，机器可解析）：
  `<!-- knowledge: capability=<能力名> rev=<N> sources=<归档名,归档名,...> -->`。
- 合并语义：能力页不存在 → 新建（ADDED）；已存在 → 以本次归档的 delta 重写受影响规则段
  （MODIFIED，rev 加 1，溯源段追加一行）；delta 声明删除的规则 → 移除并在溯源段留
  「已随 <归档名> 废除」行（REMOVED）。同一能力多份归档时只保留最终态规则。
- 硬顶：单页（含 marker 与溯源段）不超过 150 行；超顶须拆主从分片或精简。
- 风格禁令：禁历史叙述措辞（「曾经/后来/当时」），只写现行规则；ADR 判据只收
  「跨 SPEC 影响架构走向」的机制选型，不收单 SPEC 内布局/命名取舍。

## 本次运行模式

{{MODE_LINE}}

## 模式一：聚类自举（bootstrap）

输入：下方完整归档清单（每个归档读其 `specs/*/` 目录名与 `proposal.md` 标题/首段即可，
不必通读全文）。

产出（全部落盘后本 run 即结束，不要 git commit）：

1. `spec/knowledge/index.md`：真相源导航页，列出全部域与各域一句话简介；
2. 每域一份 `spec/knowledge/domains/<域>/_domain.md`：域导航页，列出该域全部能力页
   占位链接（能力页由后续批次产出，可先列条目链接）；
3. 域归位清单：把下方归档清单中的**每一个**归档分配到恰好一个域，写入
   `{{DOMAIN_MAP_PATH}}`，JSON 对象形如 `{"<归档名>": "<域目录名>", ...}`——
   域目录名用业务语言的 kebab-case 短语（如 `dashboard-ux`、`verify-pipeline`）；
   清单必须全覆盖、无遗漏、无重复。

归档清单（共 {{ARCHIVE_COUNT}} 个）：

{{ARCHIVE_LIST}}

## 模式二：批量蒸馏批次（batch）

输入：本批归档清单（见下）。逐个归档读取其 `specs/<capability>/spec.md` delta 与
`proposal.md`（无 `design.md` → 跳过 ADR 抽取；无 `specs/` delta → 按 proposal 摘要
口径蒸馏或留痕跳过，均不算失败），把每个归档的知识按契约合并进真相源。

批量模式附加规则：

- 一次处理本批**全部**归档，按清单顺序逐归档应用 ADDED/MODIFIED/REMOVED 语义；
- 域归位服从既有骨架：每个能力页落到域归位清单（`{{DOMAIN_MAP_PATH}}`）指定的域；
  该清单缺项的归档，按能力语义自行归入最贴近的既有域；
- 同批多个归档改同一能力页时，按清单顺序叠加合并，页内只留最终态规则；
- 不要修改 `spec/knowledge/` 之外的任何文件；不要执行 git 操作（提交由框架完成）。

本批归档清单（共 {{BATCH_SIZE}} 个）：

{{BATCH_LIST}}

{{VIOLATIONS_BLOCK}}

## 收尾自查（所有模式）

结束前逐项自查，任一不满足须修正后再结束：

- [ ] 新建/改动的每个能力页 marker 可解析、sources 全部指向真实存在的 `spec/archive/<名>` 目录；
- [ ] 单页不超 150 行；
- [ ] `index.md` 与各域 `_domain.md` 的链接全部可解析；
- [ ] 未触碰 `spec/knowledge/` 之外的文件。
