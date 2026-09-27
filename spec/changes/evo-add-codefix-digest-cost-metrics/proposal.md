# proposal: add-codefix-digest-cost-metrics

## 背景

add-codefix-affinity-batching（2026-09-26 23:44 落地，merge f5a959b7）生效后首个全量消化窗口（code-review-1790464976 出账 163 条）的成本复核发现：自省条目按 7 个 run 样本得出「批均降 25%、条均升 22%」，回源对账后真值更糟——同链实为 9 个 run 共 3097 轮消化 158 条 resolved（code-fix-1790469640 457 轮、code-fix-1790470847 387 轮被样本漏计），条均约 19.6 轮，为基线 11.3 的 1.7 倍。

归因抽样（730 轮与 415 轮两批）：tool_use 大头是定位取证（Bash 内 grep 89/171 与 38/82、Read 约 21-23%、sed），自检重跑少（py_compile 10-11 次、pytest 0-3 次）；且 730 个 assistant 行仅 344 个 tool_use——近半「轮」是纯文本/思考行。粗估每批固定开销约 270 轮、每条边际约 4 轮。

## 问题

成本未收敛的度量层有三个盲区，本轮自省即被误导：

- turns 指标把纯文本/思考行计入「轮」，高估工作量约一倍，也无法区分读代码/改代码/自检的构成；
- 消化链没有链级口径：一次出账的消化分布在多个 run，自省要靠人工 grep 台账 items.jsonl 对账才能发现漏计 2 个 run；
- 机制原目标「批数下降摊薄批级固定开销」（add-codefix-affinity-batching design.md:17-22）没有对照度量，落地后无人能判断兑现与否（实测 158 条仍需 9 run，未兑现）。

## 目标

- run 侧：context metrics 增加工具构成（tool_use 按名计数）与文本行（无 tool_use 的 assistant 轮）计数，让「轮数」可归因。
- 链侧：code-fix 消化链收尾输出链级 rollup（run 数、总轮数、总 tool_use、resolved/ignored 条数、条均轮数），一行结构化日志 + 状态落盘，自省直接引用，杜绝样本漏计。

## 非目标

- 不改 select_batch 装箱策略与 batch_size/target 配置值（留待 rollup 数据积累后再评估）。
- 不做严重度预聚类、不做台账 ingest 预聚类：文件亲和装箱已交付「同文件多条同批」，归因显示轮数大头是难条目固有取证成本与批固定开销摊薄，severity 预聚类对症性弱（见 design D3）。
- 不改核销/进度口径（add-codefix-commit-first-contract、add-code-fix-item-level-progress）。