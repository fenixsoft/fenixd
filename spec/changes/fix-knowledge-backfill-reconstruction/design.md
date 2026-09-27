# Design: fix-knowledge-backfill-reconstruction

## Context

`add-knowledge-atlas-maintenance` 已 pushed（回填车道 `core/knowledge_backfill.py` 落地：`BackfillLedger` 归档粒度台账、`build_batches` 按域分归档批 ≤20、`run_backfill` 主流程、`_validate_with_repair` 校验闭环）。两个语义缺陷（顺序承重未钉死、跨域归档稀释）+ 一个覆盖缺口（09-02 前史前能力无归档覆盖，08-16 迁移提交起 672 提交（实测）的地基不在任何 delta 里）。会话定案方案 B：能力聚合全链蒸馏 + 史前复原 + 回填期增量排队。

## Goals / Non-Goals

**Goals**
- 蒸馏单元归档→能力，链索引机械可算，批序无关
- 台账 v2 双维度（capability/adr），断点独立续跑
- 史前复原段 + marker `origin` 契约 + validate 分支放行
- 回填期 `dispatch_distill` 排队登记，单写者
- 自举重跑清理 fixture 域遗留（zn-demo-domain 等）

**Non-Goals**
- 不改增量蒸馏提示词（`distill.md`）与归档触发链路；不改 audit/graph 车道；不动 Dashboard
- 不追求史前清单 100% 完备——宁缺勿滥，audit 车道后续可补

## Decisions

### D1: 链索引纯机械，聚类才用 LLM

链索引 = 遍历 `spec/archive/*/specs/` 目录名（能力名）× 归档日期（目录名前缀排序），纯文件系统扫描零 LLM；能力的域归属沿用既有自举聚类 run（但聚类对象从归档名改为能力名）。史前候选求差 = 归档链能力全集（机械）与 LLM 史前清单的集合差。LLM 只承担两件事：能力→域聚类、史前清单与史前页成文。

### D2: 台账条目键从归档名改为带前缀复合键

`BackfillLedger` 条目键 `capability:<名>` / `adr:<归档名>`；旧归档粒度台账文件（`.fenix/knowledge_backfill.jsonl` 若存在旧条目）首次重入时作废重建（回填尚未真跑过，无迁移负担，设计上允许丢弃——台账是运行时进度非数据资产）。旧 domain_map 文件（`.fenix/knowledge_backfill_domains.json`）当前同样不存在（实测），v2 首次自举即以能力名为键重建，无残留格式风险。ADR 扫描保持归档粒度（design.md 是归档级产物），页蒸馏改能力粒度，两维度天然正交。

### D3: 排队 = 登记进台账而非内存队列

`dispatch_distill` 检测台账有 pending 即不派发，把归档登记为 pending 条目后返回（fail-open 语义不变）。不做内存队列/锁——回填重入天然消化 pending，重启安全（台账在盘）。收敛判据 = 台账无 pending 且无 failed 待重试。排队登记落在 `core/knowledge.py` 侧：`core.knowledge_backfill` 顶层不 import `core.knowledge`（仅函数内懒导入），故 `core.knowledge` 导入 `BackfillLedger` 与台账路径常量不构成导入环；登记写入复用原子回写。

### D4: prehistoric 锚点用 `git:<起始ref>-..<结束日期>` 文本形态

sources 项形如 `git:44e1443b-..2026-09-02`；validate 分支：`origin=prehistoric` 时校验锚点格式（正则）+ 起始 ref `git cat-file -e` 可解析，不查归档目录。不用裸 commit 区间 `a..b` 形态是为了与归档路径项在视觉/解析上都无歧义（`git:` 前缀显式分流）。史前提示词（`prehistoric.md`）输入 = `git log --format` 提交群（标题行）+ `core/` 顶层模块清单 + 既有归档能力全集（求差用），输出 = 史前能力清单 JSON + 各页散文。

## Risks / Trade-offs

- 史前清单可能漏/滥：漏由 audit 车道后续补；滥由「宁缺勿滥」判据入提示词 + 150 行硬顶兜底。
- 聚合 run 单能力链上下文变大：链长 ≤6 份 delta（实测最大重复度），量级可控。
- 旧台账作废：回填从未真跑（仍手工激活未触发），无真实进度可丢。

## Migration Plan

- 回填车道尚未消费（SPEC 手工激活、回填未触发），本修订落地后回填首次真跑即聚合语义，无数据迁移。
- fixture 域清理随自举重跑自然完成。
