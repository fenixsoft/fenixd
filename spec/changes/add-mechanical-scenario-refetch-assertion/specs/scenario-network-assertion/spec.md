## ADDED Requirements

### Requirement: 交互步骤网络请求断言

web 场景步骤 MUST 支持可选 `expect_network` 字段（交互类步骤：click/hover/contextmenu 等），形态为 `[{"url_pattern": <子串或正则>, "min_count": <正整数>}]`；引擎在该步骤执行窗口内经 playwright 网络事件收集请求并逐项断言。断言失败 MUST 产出失败明细：期望模式、最少次数、实际捕获计数、至多 3 条实际请求 URL 样例。非交互步骤携带该字段 MUST 被场景验收拒绝（验收错误，非运行时失败）。

#### Scenario: 交互触发请求被断言通过
- **WHEN** 场景步骤 `{click: 项目筛选选项, expect_network: [{url_pattern: "/api/command-center/", min_count: 1}]}` 执行且窗口内实际发出 1 个匹配请求
- **THEN** 步骤通过，报告该步骤含网络断言通过记录

#### Scenario: 零请求缺陷被暴露
- **WHEN** 同上步骤执行但窗口内无任何匹配请求（交互未触发重拉取）
- **THEN** 步骤失败，明细含「期望 ≥1 实际 0」与捕获样例（此处为空提示），场景计入 fail——BUG-1 类缺陷机械可暴露

#### Scenario: 非交互步骤携带字段被验收拒绝
- **WHEN** 场景在非交互步骤（如 navigate/wait）携带 expect_network
- **THEN** 场景验收失败，错误指向该步骤（验收期拦截，不进运行时）

### Requirement: 契约校验白名单同步

场景验收对 expect_network 的字段形态 MUST 做结构校验（url_pattern 非空字符串、min_count 正整数），非法形态按既有验收错误通道报告（逐条、场景 id 定位）。planner 出题契约段 MUST 补能力声明与最小示例，使后续出题可自然产出 refetch 类场景。

#### Scenario: 非法形态验收报告
- **WHEN** 场景携带 `expect_network: [{"url_pattern": "", "min_count": 0}]`
- **THEN** 场景验收失败，错误逐条指出 url_pattern 非空与 min_count 为正整数

#### Scenario: planner 契约声明
- **WHEN** 后续 planner 出题轮读取契约段
- **THEN** 能力声明与示例可见，出题可产出携带 expect_network 的筛选/交互场景
