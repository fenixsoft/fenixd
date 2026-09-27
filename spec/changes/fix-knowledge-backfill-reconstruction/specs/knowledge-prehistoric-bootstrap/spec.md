## ADDED Requirements

### Requirement: 史前能力复原

回填自举阶段 SHALL 包含史前复原段：LLM 读 git 历史（仓库首提交至 2026-09-02 归档批量落库之前，重点 2026-08-16 迁移至 2026-09-01 的提交群）与当前代码骨架，产出史前能力清单（能力名、一句话、当前规则要点）；与归档链索引覆盖的能力求差后：**未被归档覆盖**的史前能力产史前能力页（补齐地基）；**已被归档覆盖**的能力其史前基线 SHALL 作为该能力聚合蒸馏的链头输入（LLM 在链前先读基线再读 delta 链）。

#### Scenario: 无归档覆盖的基础能力被复原

- **WHEN** 某框架基础能力（如验证引擎的就绪探针机制）存在于代码但从未出现在任何归档 SPEC 的 specs/ 下
- **THEN** 史前复原段为其产出能力页，规则散文陈述当前行为，溯源段首行为史前复原行（git 区间锚点），该页入正确域并登记进 index

#### Scenario: 有归档覆盖的能力以史前为链头

- **WHEN** 某能力既有史前基线又含 3 个归档 delta
- **THEN** 聚合蒸馏单元输入 = 史前基线 + 3 份 delta，产出页面规则为基线被 delta 逐层覆盖后的最终态，溯源段首行为史前复原行、其后 3 行归档行

### Requirement: marker origin 契约

能力页 marker SHALL 增加可选 `origin` 字段：`origin=archive`（缺省，行为与既有契约完全一致）或 `origin=prehistoric`。prehistoric 页的 sources SHALL 允许 git 区间锚点形态（`git:<起始ref>-..<结束日期>`），`validate_knowledge` 的 sources 存在性校验 SHALL 按 origin 分支：archive 页沿用既有归档目录存在性校验；prehistoric 页校验 git 区间锚点格式且起始 ref 可解析，MUST NOT 要求归档目录存在。史前页同样 SHALL 受 150 行硬顶、禁历史措辞等全部既有页面契约约束。史前独有能力页（链索引中无任何归档 delta）的 marker rev SHALL 为 1、sources 仅含其单条 git 区间锚点。

#### Scenario: prehistoric 页通过校验

- **WHEN** validate_knowledge 检查一个 `origin=prehistoric`、sources 为 `git:44e1443b-..2026-09-02` 的能力页
- **THEN** 校验放行（锚点格式合法、起始 ref 可解析）；同页若 sources 写了不存在的归档路径或非法锚点则校验拒绝

#### Scenario: archive 页契约零回归

- **WHEN** 对既有无 origin 字段的能力页运行 validate_knowledge
- **THEN** 行为与本修订前完全一致（缺省 origin=archive，归档存在性校验照旧）
