# 史前能力复原

<!-- knowledge: capability=knowledge-prehistoric-bootstrap rev=1
     sources=spec/archive/2026-10-05-fix-knowledge-backfill-reconstruction -->

回填自举阶段的史前复原段：把任何归档 delta 都未覆盖的框架地基能力（归档批量落库之前、无 SPEC 记录的行为）考古进真相源，补齐「只按归档链蒸馏会漏掉整个地基」的覆盖缺口。

## 规则

- 复原输入：git 历史（仓库首提交至 2026-09-02 归档批量落库之前，重点 2026-08-16 迁移至 2026-09-01 的提交群）与当前代码骨架，产出史前能力清单（能力名、一句话、当前规则要点）。清单宁缺勿滥、不求完备：漏由 audit 车道后续补，滥受 150 行硬顶兜底。
- 求差与分流：史前清单与归档链索引覆盖的能力全集求差——未被归档覆盖的史前能力产史前能力页；已被归档覆盖的能力，其史前基线作为该能力聚合蒸馏的链头输入（LLM 先读基线再读 delta 链）。
- 史前页与归档页同一契约：规则散文陈述当前行为、禁历史叙述措辞、单页 ≤150 行；溯源段首行为史前复原行（git 区间锚点，纯文本不加链接）；页面入正确域并登记 index。
- marker `origin` 契约：marker 增可选 `origin` 字段，取值 `archive`（缺省，行为与无字段时完全一致）或 `prehistoric`。史前页 sources 允许 git 区间锚点形态 `git:<起始ref>-..<结束日期>`（`git:` 前缀与归档路径项显式分流、解析无歧义）；史前独有能力页（链索引中无任何归档 delta）rev=1、sources 仅含其单条锚点。
- 校验按 origin 分支：`validate_knowledge` 对 archive 页沿用既有归档目录存在性校验；对 prehistoric 页校验锚点格式与起始 ref 可解析（git cat-file），不要求归档目录存在；git 解析预算耗尽时降级跳过 ref 解析、文末 WARNING 留痕；origin 非法取值判违规。

## 溯源

- 2026-10-05 fix-knowledge-backfill-reconstruction（spec/archive/2026-10-05-fix-knowledge-backfill-reconstruction/） — 新增本能力页：史前复原段与求差分流、史前页形态、marker origin 契约与 validate 分支放行
