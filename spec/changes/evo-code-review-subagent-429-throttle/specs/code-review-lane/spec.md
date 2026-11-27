# 能力规格：全仓审查车道并发与 429 韧性（增量：子代理级节流）

## ADDED Requirements

### Requirement: 在飞上限缺省降档（含一键两用通道与前端同源）

系统 MUST 将 `verify.repo_code_review_concurrency` 缺省值从 4 降为 2：core/config.py `get_repo_code_review_concurrency` 缺省常量与 prompt_builder 注入的 fail-open 回退值同步降为 2。配置键语义不变（正整数；一键两用于提示词侧并行扇出上限与 `ocr scan --concurrency <n>` 缺省并行度），已显式配置的项目不受影响；ocr scan 通道缺省并行度同步降为 2 属声明内接受面。设置页前端缺省常量（QualityPanel.tsx `REPO_REVIEW_DEFAULT_CONCURRENCY`，源码注释声明与 ConfigLoader 缺省同源）MUST 同步改 2，保持空值回显与描述文案和后端生效值不漂移。

#### Scenario: 未显式配置时生效 2
- **WHEN** 项目未显式配置 `verify.repo_code_review_concurrency`
- **THEN** 审查 prompt 注入的在飞上限为 2、fail-open 回退为 2、ocr scan `--concurrency` 缺省并行度为 2，设置页空值回显与描述文案展示 2

#### Scenario: 显式配置不受影响
- **WHEN** 项目显式配置 `verify.repo_code_review_concurrency=4`
- **THEN** 扇出上限与 ocr scan 并行度均按 4 生效，与引入本需求前一致

### Requirement: 派发契约内建 429 记忆与止损（注入全仓审查 run prompt）

全仓审查 run prompt MUST 携带 429 处置条款：①任一子代理死于 429（错误文本含 429 或 1302）后，本 run 后续子代理派发一律串行（在飞 1），不得恢复高并发；②重派前按 60s、120s、240s 指数退避等待，等待期间继续自审未派发文件（不违反既有「禁 async 等待收工」——轮询等待不是收工）；③连续 3 个及以上子代理因 429 在派发后 60 秒内死亡时，停止派发子代理，转为主循环自行逐文件审查，并在完成统计行末追加标记 `[review_429_storm=true; failed_shards=<n>]`（标记是 run 主体唯一的额外输出通道，产物与分片写路径契约不动）。

#### Scenario: 渲染的审查 prompt 含处置条款全文
- **WHEN** prompt_builder 为全仓审查 run 渲染 prompt
- **THEN** 渲染结果包含 429 处置条款全文（串行降档、指数退避、止损转自审、完成统计行标记格式）

#### Scenario: 风暴后自审兜底正常收场
- **WHEN** run 主体按止损规则转自审并完成全部文件审查
- **THEN** run 正常收场、完成统计行携带 `review_429_storm=true` 标记与死亡分片数，产物硬门按既有口径通过

### Requirement: 风暴标记解析回填与 admin 告警

框架 MUST 在审查 run 收尾解析完成统计行的 `review_429_storm` 标记并回填结果信封新字段（`review_429_storm` bool、`failed_shards` int；run 主体漏报时保持缺省值，MUST NOT 产生假阳性），admin_monitor MUST 在终态消费该标记产生恰好一条 admin 告警（同 run 去重）：evidence 含死亡分片数与时间线，建议文案包含「检查同账户并发：注意多项目全仓审查窗口重叠，建议错峰排程」。该消费与既有 run 级 `ratelimit_redispatch` 终局重派按 run 终态天然互斥（run 被打杀时 `not run_ok`，风暴标记无从产生），MUST NOT 出现重复告警面。

#### Scenario: 风暴标记触发恰好一条告警
- **WHEN** 审查 run 终态 result 携带 `review_429_storm=true`
- **THEN** admin_monitor 产生恰好一条 admin 告警，evidence 含死亡分片数与错峰建议文案，重复终态不重复告警

#### Scenario: 无标记不告警且既有防线不变
- **WHEN** 审查 run 正常收场且完成统计行无 `review_429_storm` 标记，或 run 被 429 打死（not run_ok）
- **THEN** 不产生风暴告警，前者零副作用、后者走既有 run 级 ratelimit_redispatch 终局重派，行为与引入本需求前一致

## 验收

- prompt_builder 渲染的审查 prompt 含 429 处置条款全文。
- 未显式配置时，在飞上限取 2（含 fail-open 回退与 ocr scan 一键两用通道），前端缺省常量同源取 2。
- 携带 `review_429_storm=true` 的终态 result 触发恰好一条 admin 告警，重复终态不重复告警。
