# Proposal: fix-knowledge-backfill-reconstruction —— 回填聚合语义修订与史前能力复原

## Why

`add-knowledge-atlas-maintenance` 落地的回填车道（`core/knowledge_backfill.py`）按**归档粒度**分批（`build_batches` 按 domain_map 把归档名分到域批次），存在两个会在一次性回填中造成实际损害的语义缺陷：

1. **顺序承重未钉死**：蒸馏合并语义是「后写覆盖前写」，同一能力被多个归档先后修改（dashboard-spec-table ×6）时，最终页面取决于处理顺序。归档粒度批次下，批内按名排序（非日期序）、跨能力交叉，最终态正确性靠运气。
2. **跨域归档与重复蒸馏**：一个归档常触碰多域能力，按域分批归档粒度导致其只落一个批（其余域的能力改动被稀释）或语义混乱；且逐归档重放会对同一能力页反复重写（×6 归档 = 6 次中间态重写）。

此外存在**覆盖面缺口**：归档目录全部始于 2026-09-02（当天批量归档存量），而仓库首提交 2026-08-16「迁移 fenixd 框架至独立工程」之前的框架基础能力（验证引擎、状态机、派发、工作区管理等，08-16~09-01 共 672 个提交的沉淀（`git log --since=2026-08-16 --until=2026-09-02` 实测，含合并提交），部分能力可上溯至迁移前工程）没有任何 delta spec 覆盖——只按归档链蒸馏会漏掉整个地基。

讨论定案（2026-09-27 会话）：回填改**方案 B 能力聚合全链蒸馏**，并补**史前能力复原**段。

## What Changes

- **回填单元从归档改为能力（方案 B）**：机械扫描建立「能力 → 触碰它的全部归档 delta（按日期升序）」链索引；每个能力一个蒸馏单元，LLM 一次读该能力完整演变链直接写出最终态页面（rev = 触碰归档数、sources = 全链、溯源按时间序）。批次 = 域内**能力**集合（`build_batches` 改能力粒度），页间独立 → 批次顺序与正确性解耦、可并行、断点续跑按能力粒度。
- **史前能力复原段**：回填自举阶段新增 prehistoric 复原——LLM 读 git 历史（首提交至 2026-09-02 前，重点 08-16~09-01 的 637 条提交）与当前代码骨架，产出史前能力清单；与归档链覆盖的能力求差：**未被归档覆盖**的能力产史前能力页；**已被覆盖**的能力其史前基线作为链头输入聚合蒸馏。史前页同样受 150 行硬顶与风格契约。
- **marker 契约扩展 `origin` 字段**：能力页 marker 增加可选 `origin=archive`（缺省）| `origin=prehistoric`；prehistoric 页的 sources 允许 git 区间锚点（`git:<起>-..<止>` 形态），`validate_knowledge` 的 sources 校验按 origin 分支放行；溯源段首行为史前复原行。
- **台账 v2**：`BackfillLedger` 条目从归档粒度扩为双维度——`capability:<名>`（能力页蒸馏）与 `adr:<归档名>`（该归档 design.md 的 ADR 抽取扫描），各自 pending/distilled/failed，断点重入按两维度独立续跑。
- **回填收敛前增量蒸馏排队**：`dispatch_distill` 检测回填台账存在 pending 条目时不派发增量 run，改为把该归档登记进回填台账（pending），由回填车道统一按聚合语义消化——`spec/knowledge/` 在回填期只有回填一个写者，彻底消除并发写窗口。
- **自举重跑清理 fixture 遗留**：当前 `spec/knowledge/domains/` 存在 e2e fixture 域（如 `zn-demo-domain`），真实聚类自举重跑时以真实结果重建域清单并清理遗留域。

## Capabilities

### 新能力
- `knowledge-backfill-chain-aggregation`：能力聚合全链蒸馏语义（链索引、聚合成文、能力粒度批次与断点、增量排队）
- `knowledge-prehistoric-bootstrap`：史前能力复原（git 考古 + 求差、史前页形态、marker origin 契约、基线作为链头）

## Impact

- **修改文件**：`core/knowledge_backfill.py`（链索引/聚合批次/台账 v2/史前段/排队协作）、`core/knowledge.py`（`parse_marker`/`validate_knowledge` origin 分支、`dispatch_distill` 排队登记）、`core/knowledge_prompts/backfill.md`（改聚合式提示词）、`tests/test_knowledge_backfill.py`、`tests/test_knowledge.py`
- **新增文件**：`core/knowledge_prompts/prehistoric.md`（史前复原提示词）
- **不修改**：增量蒸馏（`distill.md`）提示词与归档触发链路（排队逻辑在 dispatch 侧）；audit/graph 车道；Dashboard 前端
- **风险**：git 考古的史前清单质量依赖提交信息与代码骨架的可读性（08-16 起提交信息质量高，可支撑）；聚合 run 的单能力链上下文大于单 delta（能力链 ≤6 份 delta，量级可控）
