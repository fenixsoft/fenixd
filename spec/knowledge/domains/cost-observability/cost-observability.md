# 成本观测与金额展示
<!-- knowledge: capability=cost-observability rev=2
     sources=spec/archive/2026-09-06-add-cost-observability,spec/archive/2026-09-11-add-model-billing-cost-display -->

按 SPEC 累计 token 用量并本地计价展示金额，配预算阈值告警，使单 spec 烧钱可观测、可预警、不伪造。

## 规则

- **run 级 usage 提取与累计**：实现/验证/裁决 run 收工时从 stream-json 输出提取最终 usage（`input_tokens`、`cache_creation_input_tokens`、`cache_read_input_tokens`、`output_tokens`），累加到 STATE.md 对应 spec 的 `_tokens_in` / `_tokens_out`（跨重启持久）。usage 缺失（run 异常早夭）按 0 计并记日志。
- **Dashboard 与报告展示**：SPEC 详情展示累计 token（格式如「输入 42.0M / 输出 0.3M」）；验证报告含本验证链（planner+judge+scene 相关 LLM run）的增量 token 小节。
- **预算阈值告警**：配置 `agents.token_budget_millions`（缺省 50，0=关闭）。累计 input 达预算 80% 或 100% 时各发一次警告级 human-escalation-alerts 告警（一次性不重复）；告警不自动冻结 spec。降噪分级：预算告警仅 critical/major 进人工待处理队列；warning/minor 写入即默认标记人工已处理（留历史记录、不弹 Dashboard 待处理横幅；`impl_budget_exempt_loop` minor 同此规则，`impl_budget_exhausted` major 保持人工）。
- **金额本地计价为唯一口径**：run 成本 = 该 run 的 usage 分项 × 该 run 实际 `model@provider` 的配置单价（input/output/cache_read/cache_creation 四项）。成本 MUST 且 ONLY 以本地计算为准；不回退展示网关回传金额，网关回传累计保留在 STATE `_cost_usd` 但退出展示。
- **不伪造金额**：该 run 的模型未配置价格或计费开关关闭时展示「成本不可用」而非 $0.00。
- **run 级成本计算来源**：从 run 产物尾部（`.fenix/runs/*.jsonl`，含归档与历史 run）的 result 事件提取 usage 分项、provider_marker 提取实际 `model@provider`，按 `provider+model` 精确匹配 `llm.billing.prices` 计价；历史 run 无需迁移即可补算。无 result 事件（运行中/中断/无 LLM 的 run）视为不可计价；失败重试仅最终 result 计入（与 usage 统计口径一致）。
- **SPEC 详情成本展示**：可计价 run 的成本求和；存在未计价 run 时附注「含 N 个未计价 run」；全部 run 不可计价（含开关关闭/无匹配价格）时展示「成本不可用」。展示与累计 token 同区（项目信息区），不新增独立页面。
- **时间轴节点成本标注**：可计价 run 节点显示成本标注（含其 `model@provider` 信息，llm Tag 风格）；不可计价节点不显示成本标注；标注不改变时间轴既有节点结构与交互。

## 溯源

- 史前基线 — token 成本按 run 采集、按项目与 agent 累计，Dashboard 展示并接预算控制。
- 2026-09-06 2026-09-06-add-cost-observability — 改立 per-spec usage 累计与 STATE.md 持久字段，新增 Dashboard/报告展示、预算阈值告警与降噪分级，确立「不伪造金额」口径。
- 2026-09-11 2026-09-11-add-model-billing-cost-display — 金额口径改为本地单价计算为唯一依据（网关回传展示口径已随该归档废止），新增 run 级本地计价、SPEC 详情成本展示与时间轴节点成本标注。
