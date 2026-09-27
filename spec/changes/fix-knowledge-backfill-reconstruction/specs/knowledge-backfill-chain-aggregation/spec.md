## ADDED Requirements

### Requirement: 能力聚合全链蒸馏

回填车道的蒸馏单元 SHALL 从归档改为**能力**：机械扫描全部归档的 `specs/<capability>/spec.md`，建立「能力 → 触碰它的全部归档 delta（按归档日期升序）」链索引；每个能力派发一次聚合蒸馏，LLM 一次读该能力完整演变链后直接写出最终态能力页（rev = 链长、sources = 全链归档、溯源段按日期升序逐行完整）。批次 SHALL 为域内能力集合（能力粒度，批规模上限沿用 ≤20），页间独立——批次执行顺序、并行度与断点重入均 MUST NOT 影响任何能力页的最终内容。

#### Scenario: 多归档能力一次成文

- **WHEN** 能力 `dashboard-spec-table` 的链含 6 个日期递增的归档 delta
- **THEN** 该能力只产出一个蒸馏单元：产出页面 rev=6、sources 含全部 6 个归档、溯源 6 行按时间序、规则段只陈述最终态（早期归档的被覆盖规则不残留）；无论该单元落在哪个批次、批次执行几次重入，产出内容一致

#### Scenario: 批次顺序无关

- **WHEN** 两个能力分属不同批次，执行顺序颠倒或两批并行
- **THEN** 两页最终内容与串行日期序执行完全一致（页间无共享状态）

### Requirement: 台账 v2 双维度断点

`BackfillLedger` SHALL 扩为双维度条目：`capability:<能力名>`（聚合页蒸馏）与 `adr:<归档名>`（该归档 design.md 的 ADR 抽取扫描），各自携带 pending/distilled/failed 状态。断点重入 SHALL 按两维度独立续跑：已 distilled 的能力页与已扫描的 ADR 不重做；`failed` 条目重入时重试且不阻塞其他条目。收敛汇报 SHALL 分别给出页维度与 ADR 维度的成败计数。

回填主流程 SHALL 对全部 `adr:pending` 条目按归档批次（≤20）派发 ADR 抽取 run：读该归档 `design.md` 产出/更新 `spec/knowledge/adr/ADR-*.md` 并登记 `adr/index.md`；无 `design.md` 的归档条目直接标 distilled（留痕跳过，不算失败）。无此执行段则 ADR 条目永久 pending——回填收敛判据永不满足，且增量蒸馏排队门不释放。

#### Scenario: 中断重入按能力续跑

- **WHEN** 回填在第 3 批中断（前 2 批的 capability 条目已 distilled），重入后某能力页蒸馏失败
- **THEN** 该能力条目标 failed，其余 pending 条目继续；已 distilled 能力页不被重写（真相源无多余改动）

#### Scenario: ADR 条目被抽取批次消化

- **WHEN** 台账存在 pending 的 `adr:<归档名>` 条目（该归档含 design.md）与一个无 design.md 归档的条目
- **THEN** 前者经 ADR 抽取批次产出/更新对应 ADR 并登记 index 后标 distilled，后者直接标 distilled（留痕跳过）；收敛时 ADR 维度无滞留 pending

### Requirement: 回填期增量蒸馏排队

回填台账存在 pending 条目期间，`dispatch_distill` 与批量入口 `dispatch_distill_batch` SHALL NOT 派发增量蒸馏 run（批量入口多归档分支不经过单条路径，须同样执行排队判定），改为把该归档登记进回填台账（新增 pending 的 capability 与 adr 条目；对应 `capability:<名>` 条目已为终态的 SHALL 重置为 pending，使链索引重扫后该能力页纳入新归档 delta 重新聚合），由回填车道按聚合语义统一消化。`spec/knowledge/` 在回填进行期 SHALL 只有回填车道一个写者。回填收敛后 `dispatch_distill` 恢复即时派发。

#### Scenario: 回填中新归档被登记而非并发写

- **WHEN** 回填运行中某 SPEC 归档触发 dispatch_distill
- **THEN** 无增量蒸馏 run 启动；该归档的能力与 ADR 条目以 pending 进入回填台账，最终被回填车道产出（页面含该归档的溯源行），全程无并发写窗口
