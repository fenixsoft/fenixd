# 真相源目录契约与能力页格式

<!-- knowledge: capability=knowledge-atlas-directory rev=6
     sources=spec/archive/2026-10-05-add-knowledge-atlas,spec/archive/2026-10-05-fix-knowledge-backfill-reconstruction,spec/changes/add-knowledge-anchor-lint-and-prune -->

`spec/knowledge/` 是项目知识真相源：只装「系统现在是什么规则」的常驻知识层；归档 SPEC 继续承担历史职责，两者以溯源链接互指。

## 规则

- 目录结构：`index.md`（总目录，列全部能力域与增厚简介——每域 2~3 句、覆盖该域主要能力面，素材取各域 `_domain.md` 既有简介与能力清单；简介列保持单行单元格且不含裸竖线 `|`；记忆回填轨迹不落 index（2026-11-08 用户指令：首页人类不可读账目迁出——折叠轨迹以 `log.md` 编年账与各能力页「溯源」段 `_inbox/done/` 来源行承载，index 只保留域导航））、`domains/<域>/<能力>.md`（一能力一页，域为能力的业务聚类）、`adr/index.md` + `adr/ADR-NNN-<标题>.md`（决策索引与条目）、`README.md`（目录契约说明）。全目录 git tracked；首次蒸馏前允许只含 README.md 骨架。能力域由蒸馏 run 自动聚类生成，不预置人工清单；`_domain.md` 与 `index.md` 是导航层，由蒸馏 run 维护。
- 能力页结构（Markdown，人类可读性优先）：H1 能力名（中文表述）→ 紧随的 HTML 注释 marker → 角色一句话 → `## 规则`（当前生效业务规则）→ `## 关键行为`（可选）→ `## 代码锚点`（可选，见下）→ `## 溯源`（来源列表）。
- 代码锚点段：置于 `## 规则` 之后、`## 溯源` 之前，按四类固定标签承载实现定位——主实现（文件路径）/ 单源符号（`路径:符号` 形态）/ 消费方（谁调用/挂载）/ 守卫测试（钉住本行为的测试文件）。粒度纪律：一律文件级路径 + 符号名，禁行号（必腐）；段内路径 MUST 指向盘上真实存在的仓库内文件。新建能力页（蒸馏折叠与回填车道产出）MUST 带锚点段；纯契约/流程类能力（无实现载体）允许缺省并在段位写一行「无独立实现载体」；存量页按触达增量补，不做全量回填批次。锚点段纳入 marker 之外的机器校验面：`check_anchor_references` 只校验段内路径盘上存在性（`路径:<纯数字>` 行号形态报格式违规），由 audit 车道消费、进体检报告病灶⑥待人工/定向转写档——不并入 `validate_knowledge` 硬门（防一处陈旧锚点阻塞全树折叠校验），悬空不机械自删（修复需语义判断）。
- 退役即删不墓碑：能力主体从产品删除时，其能力页从真相源**直接删除**（MUST NOT 保留页面加退役注记的墓碑形态——墓碑页每次会话持续支付读取成本；历史由 git 历史 + `spec/archive/` 承载）。同批动作：`_domain.md` 表行移除、表尾追加一行退役注记（退役日期 + spec/archive 或 git 历史指针，唯一墓碑形态）、相关 ADR 状态翻 retired、`index.md` 能力数量更新、`log.md` 登记；删除前 grep 该 capability 名在其余知识页/ADR/提示词中的引用并收口。完整操作序列照单执行 `knowledge-retirement-runbook` 能力页。
- 新能力页命名禁世代前缀：MUST NOT 使用 `v2-`/`v3-` 式世代前缀，一律功能名（命名机械校验面不覆盖——蒸馏车道复核与 spec 评审判命违规）。
- 域导航页 `_domain.md` 可含「症状速查」段（症状签名 → 能力页两列速查表），仅运维/排查密集域落此段，非强制全员。
- marker 机器接口：`<!-- knowledge: capability=<能力kebab名> rev=<整数,初始1> sources=<来源项列表> [part=<n>] [origin=archive|prehistoric] -->`，脚本据此解析能力名、版本与来源链；sources 校验按 origin 分支——archive 页（缺省）每项必须指向真实存在的归档目录，prehistoric 页允许 `git:<起始ref>-..<结束日期>` 区间锚点（契约见史前能力复原页）。
- 规则段必须是蒸馏 run 以一致语言风格重写的当前事实：禁机械搬运 delta 原文，禁「本 SPEC 新增了/修复了/原先是/改为」等历史叙述措辞，历史演变只出现在溯源段。同一能力被多个 SPEC 先后修改时，规则段只保留最终态，被覆盖的旧规则从规则段消失而非新旧并列。
- 溯源行格式 `- <归档日期> <spec名>（spec/archive/<完整目录名>/） — <该归档对本页做了什么>`；只给真实存在的归档目录加链接，史前复原与无归档的演变保持纯文本、不加链接。
- 导航层盖戳：`index.md` 第 2 行为整源盖戳行、各域 `_domain.md` 第 2 行为域盖戳行（`> 最后更新：<YYYY-MM-DD HH:MM> <时区>`，每次蒸馏刷新，时间取调度方注入的当前本地时间、不得自报）；index 能力域表恒四列（域/简介/能力数量/更新时间），`_domain.md` 能力页表恒三列（页/简介/更新时间）——被本轮重写的页刷新时间，未涉及页保持原值。
- 单页 ≤ 150 行（含 marker 与溯源段），防真相源膨胀的物理约束：超顶时蒸馏必须处置而非放行——优先拆主从分片（marker 增 `part=<n>`，主页省略、从页 2/3/…，同能力各分片 capability/rev/sources 保持一致，从页 H1 为「<能力名>（续 N）」），无法拆分则精简表述；合并语义按 capability 名聚合、整体重写该能力全部分片。

## 溯源

- 2026-10-05 add-knowledge-atlas（spec/archive/2026-10-05-add-knowledge-atlas/） — 新增本能力页：目录结构、能力页契约（marker 机器接口、规则段散文重写、溯源段）、150 行硬顶与主从分片拆页规则
- 2026-09-29 真相源溯源行链接化+导航表格化（git:0b8044d4，无归档目录） — 溯源行改链接形态、导航层改表格登记、知识页签溯源弹窗接线
- 2026-09-30 真相源更新时间盖戳+本地时区（git:77341632，无归档目录） — index/_domain 盖戳行与表格更新时间列契约，盖戳取本地时间
- 2026-10-05 fix-knowledge-backfill-reconstruction（spec/archive/2026-10-05-fix-knowledge-backfill-reconstruction/） — marker 增可选 origin 字段（archive 缺省 / prehistoric），sources 存在性校验按 origin 分支放行 git 区间锚点
- 2026-11-03 add-knowledge-consumption-discipline（spec/changes/ 实现 SPEC，暂无归档） — index 简介契约对齐增厚形态：一行简介改为 2~3 句增厚简介（覆盖主要能力面、单行单元格、不含裸竖线）
- 2026-11-04 memory 存量蒸馏投递（git:c5076028e，无归档目录） — index 目录结构契约增补「记忆回填（存量蒸馏）」节：登记隐性知识经候选区回填的状态与入库轨迹，蒸馏 run 维护该节而非删除
- 2026-11-08 v2-ui-domain-retired-1107（spec/knowledge/_inbox/done/v2-ui-domain-retired-1107.md） — index 目录结构契约改版：「记忆回填（存量蒸馏）」节从 index 迁出（人类可读性裁决），折叠轨迹唯一承载=log.md 编年账 + 能力页溯源段；index 简介行增厚口径收紧为 2~3 句遵守既有契约（dashboard-frontend 行先行改写）
- 2026-11-08 add-knowledge-anchor-lint-and-prune（spec/changes/add-knowledge-anchor-lint-and-prune/） — 能力页结构契约增补可选「代码锚点」段（四类标签/文件级禁行号/新页强制存量增量/机器校验面 check_anchor_references 由 audit 车道消费不进硬门）、退役即删不墓碑语义（域表尾一行退役注记为唯一墓碑形态）、新页世代前缀命名禁令、域导航页可选「症状速查」段
