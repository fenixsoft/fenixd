# 提案：add-codefix-affinity-batching

## Why

code-fix 自动修复车道当前按 `admin.code_review_fix.batch_size`（缺省 20）把台账 open 条目**按 first_seen_at 时间序**固定分组（`core/code_fix.py` `select_batch`），完全不考虑条目间的文件亲和性。后果：

1. **同文件问题被拆散到多批**：同一文件的多个问题分布在不同批次，每批的 agent 都要对该文件重新取证、重新理解上下文——重复劳动随批数线性放大。
2. **每批固定开销与批数成正比**：每批一次 worktree 建树、一次 agent run、一次批收尾回归（verify.yaml regression 段全量跑）、一次合回核销。回归是批级大头（fenixd 自身口径约 10min/批），批数直接决定链总时长。
3. **批内并行上限成为新瓶颈的隐患**：批内子代理并发固定 ≤4（`agents/code-fix.md`），批规模固定 20 条时该值合理，但没有任何随批规模自适应的机制。

框架选批侧引入文件亲和性聚类，让「同一文件的多个问题」与「同目录的相关文件」落在同一批，由 agent 在批内一并处置（批内按文件分组并行的机制已由 add-codefix-batch-parallel 落地），可以显著减少批数、摊薄批级固定开销。配套两段式回归（中间批按触碰面定向、链末批全量兜底）进一步压缩每批回归时间，同时保留全量回归作为链收尾的合并防线。

## What Changes

- **ADDED** 选批亲和性聚类：`select_batch` 从「时间序截取前 N 条」改为「文件组不可拆 + 目录聚簇 + 目标规模浮动」的贪心装箱——同一文件的全部 open 条目必入同批；同目录文件尽可能同批；批规模以 `batch_size` 为目标值允许浮动（不再要求精确等于），设硬上限防单批失控。
- **ADDED** 批内并行波次上限自适应：批内子代理并发上限随批内文件组数分档上调（4/6/8 三档，8 为硬上限防网关限流），经 code-fix prompt 占位符注入。
- **ADDED** 回归两段式：链内**非末批**批收尾回归按批触碰面定向（verify.yaml `regression.cmd` 支持 `{test_targets}` 占位符，框架按批内改动文件映射测试路径注入；无占位符或映射为空回退全量）；链内**末批**（核销本批后无剩余 open 条目）恒走全量回归兜底。定向与全量共用主机级回归锁、JUnit 解析、硬超时机制。失败语义对齐既有回归失败/定向重试路径。
- **ADDED** 配置键 `admin.code_review_fix.targeted_regression`（严格 bool，缺省 true）+ 设置页「质量」页签开关（新增配置项必须带 Dashboard 界面）。

## Capabilities

### New Capabilities

- `codefix-affinity-batching`: code-fix 选批的文件亲和性聚类、批内波次上限自适应、批收尾回归两段式（中间批定向 / 末批全量兜底）

### Modified Capabilities

（无——既有能力的行为契约保持向后兼容：`batch_size` 键语义从「精确条数」放宽为「目标规模」，缺省值不变；排除口径、进度 total 口径（done+open）、批收尾/合回/核销路径零改动）

## Impact

- `core/code_fix.py`（modify）：`select_batch` 聚类重写；链末批判定与批收尾回归分支；触碰面→测试路径映射
- `core/agent_runner/prompt_builder.py`（modify）：`_build_code_fix_prompt` 注入波次上限占位符
- `agents/code-fix.md`（modify）：固定「并发 ≤4」改为占位符化并写明分档规则
- `core/dashboard/static/src/pages/settings/components/QualityPanel.tsx`（modify）：`targeted_regression` 开关（与 `code_review_fix_batch_size` 同区块）
- `.fenix/config.template.yaml`（modify）：`admin.code_review_fix` 段新增 `targeted_regression` 注释样例
- `.fenix/verify.yaml`（reference，gitignored 运行时文件）：fenixd 自身回归 cmd 加 `{test_targets}` 占位符方可在本仓库享受定向化—— SPEC 交付 tracked 模板与文档说明，主树运行时文件的人工同步见 design「人工步骤」
- `tests/`（new/modify）：聚类算法、末批判定、触碰面映射、占位符注入的单测
