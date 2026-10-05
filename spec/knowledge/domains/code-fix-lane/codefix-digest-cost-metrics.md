# code-fix 消化链成本度量（工具构成指标与链级 rollup）

<!-- knowledge: capability=codefix-digest-cost-metrics rev=2
     sources=spec/archive/2026-10-06-evo-add-codefix-digest-cost-metrics,spec/archive/2026-10-06-evo-fix-codefix-rollup-archive-read -->

为 code-fix 消化链提供可归因、可对账的成本度量：run 侧把「轮」拆解为工具构成与纯文本行，链侧在链收尾输出覆盖全部 run 的链级 rollup，自省直接引用链级口径，不再人工 grep 台账对账。

## 规则

### run 工具构成指标
- run 终局的 context metrics 在既有 `turns` 之外并列统计两组字段，随 `metric_type=run_metrics` 日志行与落盘一并输出（与逐 run 上下文经济性指标同点落盘，见 [agent-run-token-economy](../cost-observability/agent-run-token-economy.md)）：
  - `tool_uses`：tool_use 按工具名计数的直方图（Read/Edit/Bash/Grep/Agent 等）；
  - `text_turns`：无 tool_use 的 assistant 纯文本/思考行计数。
- 既有 `turns` 语义不变：仍计全部 assistant 事件。三者并存，`turns` MUST NOT 单独当工作量口径（近半「轮」可为纯文本/思考行）；「读代码/改代码/自检/纯文本」的构成归因以 `tool_uses` 直方图 + `text_turns` 为准。
- 统计按转录事件逐事件累计，与 rounds/stall 统计同口径；跨 attempt 计数不串数。
- metrics 落盘失败仅记日志，MUST NOT 阻断 run 终态（成功/失败/取消三路径同，沿用 context metrics 落盘失败既有处理）。

### 消化链级 rollup
- 消化链（同一审查台账的批次链）走到末批（`is_chain_last_batch` 判定命中，与链选批同口径，见 [codefix-affinity-batching](codefix-affinity-batching.md)）或链中途终局（失败/跳批）时，输出一行结构化链级 rollup 日志并随链状态落盘，字段含：链内 run 总数、总轮数、总 tool_use 数、resolved/ignored 条数、条均轮数。
- 「覆盖链中全部 run 不漏样本」由**链级持久 run 清单**机械达成：随链状态逐 run 累积 run_id，rollup 以该清单逐 run 读取转录的 run_metrics 行汇总。进度文件既有的瞬时 `run_id` 字段（批收尾即清除）与台账核销记录（不携带 run_id）均 MUST NOT 充当「链内全部 run」的事实源。
- run 转录读取为**双路径回退**：先读顶层 `.fenix/runs/<run_id>.jsonl`，缺失回退 retention 归档副本 `.fenix/runs/archive/<run_id>.jsonl`；回退顺序即取者优先级，两处并存时取顶层（retention 去重语义下顶层即最新副本）。消化链常横跨数小时而 retention 周期远短于此，链终局时多数 run 已移档，单路径只读顶层等价于漏样本归零。
- 归零语义限于「顶层与归档两处皆缺」：该 run 按零贡献，且 MUST NOT 中断链终局（fail-open）。
- 条目计数以审查台账核销（resolved/ignored）为准，rollup 条数 MUST 与台账一致。
- 链中途终局同样输出截至当前全部已发生 run 的累计 rollup；跳批不免除已发生 run 的计数。
- rollup 不依赖内存态：链跨 daemon 重启后仍以台账核销与 run 归档计数为准。

### 批结构参数维持现状
- 选批装箱策略与 `batch_size`/target 配置值不随本度量调整，severity 预聚类不引入：轮数大头是难条目固有取证成本与批固定开销摊薄，预聚类不动难条目成本、批变小反而恶化固定开销摊薄。批结构参数待链级 rollup 数据积累后再评估。

## 溯源

- 2026-10-06 evo-add-codefix-digest-cost-metrics（spec/archive/2026-10-06-evo-add-codefix-digest-cost-metrics） — 新建本页：run context metrics 新增 `tool_uses` 工具直方图与 `text_turns` 纯文本行计数（turns 语义不变、落盘失败不阻断终态）；消化链末批/中途终局输出链级 rollup（run 数/总轮数/总 tool_use/resolved+ignored 条数/条均轮数），链级持久 run 清单逐 run 读归档计数保证不漏样本；批结构参数维持现状、severity 预聚类不立项。
- 2026-10-06 evo-fix-codefix-rollup-archive-read（spec/archive/2026-10-06-evo-fix-codefix-rollup-archive-read） — 修改本页：rollup 的 run 转录读取改为双路径回退（顶层→`.fenix/runs/archive/` 归档副本、并存取顶层），归零语义收窄为「两处皆缺」且不中断链终局，兑现「不漏样本」契约。
