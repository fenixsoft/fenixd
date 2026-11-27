<!-- knowledge: capability=repo-review-concurrency rev=1 sources=spec/archive/2026-09-30-add-code-review-concurrency-and-429-resilience -->

# 全仓审查并发约束

全仓审查 run 的并行审查度由单一配置键约束，同时注入子代理扇出上限与 ocr scan 并行度两个通道，防止多通道并发打爆同一 provider 账号。

## 现行规则

- 配置键 `verify.repo_code_review_concurrency`：正整数，缺省 2（evo-code-review-subagent-429-throttle 由 4 降档——账户级 429 风暴防线，一键两用的 `ocr scan --concurrency` 缺省并行度同步降为 2）。读取为 fail-open 单点缺省——仅接受正整数 `int`（`bool` 不算），键缺失/verify 节缺失/str/非整值 float/≤0 一律回退缺省 2，脏值不中断派发；该键不进 `resolve_config` 缺省填充列表，缺省只由读取器单点提供。
- 管辖范围：只控制**全仓审查** run（`review_kind` 为 `manual_full` / `manual_window` / `scheduled`）的并行审查度；implement 任务内审查由 `verify.impl_code_review_concurrency`（缺省 4）控制，两键独立、互不串扰。
- 并发双通道注入：全仓审查 run 派发时并发值同时注入两处——① 提示词（`agents/code-review.md`）写入并行扇出上限条款：主 agent 同时在飞的审查子代理数 MUST ≤ 该值（波次滚动推进，是波内并发上限而非任务总数上限）；② `ocr scan` 命令 MUST 带 `--concurrency <n>`（ocr 不传参时其内部缺省为 8，不受本键约束）。
- 设置界面：Dashboard 设置页 QualityPanel 提供「全仓审查并发」输入项，与「SPEC 审查并发」（`verify.impl_code_review_concurrency`）并列展示、分别保存；缺省同源面由 QualityPanel 前端常量 `REPO_REVIEW_DEFAULT_CONCURRENCY` 与读取器缺省共同维护（该键当前已不在 `.fenix/config.template.yaml`，原「模板示例值=缺省值」约束自然失效）。

## 溯源

- 2026-09-30 add-code-review-concurrency-and-429-resilience（spec/archive/2026-09-30-add-code-review-concurrency-and-429-resilience） — 新增全仓审查并发键（缺省 4，fail-open）与提示词扇出上限、ocr scan `--concurrency` 双通道注入，及设置页配套；起因是全仓审查多通道并发无上限打死网关账号
- 2026-11-27 evo-code-review-subagent-429-throttle（spec/changes/evo-code-review-subagent-429-throttle） — 缺省 4→2 降档（含 fail-open 回退与前端常量同源）；派发契约新增 429 处置条款（串行降档/60-120-240s 指数退避/连续 3 秒死止损转自审/完成统计行 `[review_429_storm=true; failed_shards=<n>]` 标记）；收尾解析标记回填 CodeReviewResult 并由 admin_monitor 落恰好一条告警（merge_signal 按 run 去重）
