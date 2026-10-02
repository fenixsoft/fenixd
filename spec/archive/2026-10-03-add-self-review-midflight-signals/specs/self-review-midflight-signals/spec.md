# self-review-midflight-signals 能力规格：自省中途信号采集

## 概述

自省数据摘要新增第六源「中途信号」：窗口内全部车道 run（含终态成功者）的中途浪费/险情机械化信号采集。扫描策略 = run_metrics 量化初筛 + 离群 run 事件流深扫 + 编排层救回痕迹归集。中途信号只进自省摘要，不新增 admin 告警。

## ADDED Requirements

### Requirement: 量化离群初筛（全量 run，零事件流读取）

自省 MUST 对窗口内全部 run（当前目录 ∪ 归档并集，排除 `review-` 前缀，口径同 `collect_runs_stats`）经 run_metrics 日志索引（`core.dashboard.data.runs` 公共访问器）做量化初筛，MUST NOT 在初筛阶段读取任何 run 事件流文件。初筛维度：`turns`、`cost_usd`、`duration_seconds`。

离群判定：按 `agent_type` 分组，run 指标 > 该组窗口内中位数 × 3 倍即离群（成功与失败 run 同口径）；组内样本 < 3 时该维度跳过（样本不足不出假离群）；某维度全组值为 0/缺失时跳过。run_metrics 索引查不到的 run（旧日志轮转出窗）跳过初筛，不视为离群也不报错。

#### Scenario: 成功但轮次离群的 run 入选

- **WHEN** 窗口内同 agent_type 有 4 个 run，中位 turns=10，某终态成功 run turns=45（> 30）
- **THEN** 该 run 进入中途信号样本，标注 `turns=45（组中位 10，成功收尾）`

#### Scenario: 样本不足组不判离群

- **WHEN** 窗口内某 agent_type 仅 2 个 run，其中 1 个 turns 远超另一个
- **THEN** 该组不产出离群样本（样本 < 3 跳过），不报错

### Requirement: 离群 run 事件流深扫

对初筛离群的 run（无离群 run 时该环节整体跳过），自省 MUST 流式逐行扫描其 run 事件流，采集：停滞信号（复用 `core.agent_runner.latency.latency_samples_from_events` + `latency_stats`，报告 stall 计数与最长往返秒数，阈值沿用 `LATENCY_STALL_SECONDS=60.0`）；中途 error/stderr 事件痕迹（计数 + 首条摘要截断）。扫描 MUST 流式逐行解析（单行 json.loads 失败跳过），MUST NOT 将整文件读入内存；单 run 深扫行数上限 20000 行，超限停止并标注 `truncated`。

#### Scenario: 成功 run 的中途停滞被深扫发现

- **WHEN** 某离群 run 终态成功，事件流含 3 次相邻工具结果间隔 > 60s 的样本、2 条 stderr 事件
- **THEN** 摘要该 run 行含 `stall=3 max_gap=<最长秒数> 中途stderr=2`

#### Scenario: 超限截断不阻断

- **WHEN** 某离群 run 事件流超过 20000 行
- **THEN** 扫描在第 20000 行停止，输出带 `truncated` 标注的部分结果，不抛异常

### Requirement: 编排层救回痕迹归集

自省 MUST 扫描窗口内 fenixd.log，按「关键词 → 组件」成对过滤归集编排层救回痕迹行：`provider switched`（agent_runner）、`gave up`（pm_engine）、`in-place retry`（agent_runner）。关键词与组件须按实测日志文案成对绑定，泛词 retry 不得单独成模式（会卷入 event_bus 无关行）。输出按关键词归组的计数 + 最多 5 条样本（时间戳 + 摘要截断）。日志文件缺失或解析失败时该节降级为空（不阻断自省）；窗口早于当前日志起点（轮转）时按日志起点截断（对齐既有日志节口径）。

#### Scenario: 换道与重试痕迹被归集

- **WHEN** 窗口内 fenixd.log 含 2 条 provider switched、7 条重试续跑、1 条 gave up
- **THEN** 摘要含「编排救回痕迹：provider switched=2、重试=7、gave up=1」及样本行

### Requirement: 摘要注入与降噪

`collect_daily_summary` MUST 在既有五节后追加「## 6. 中途信号（含成功 run）」；三类信号各有产出才渲染对应小节，全部为空时渲染占位行（形态对齐既有节）。中途信号 MUST NOT 产生 admin 告警、MUST NOT 写 run 产物文件、MUST NOT 触发任何写操作（对齐自省只读铁律）。`agents/self-review.md` MUST 同步说明第六节语义与条目引导（中途信号作为 waste/improvements 的证据来源，成功 run 的中途浪费同样可立项）。

#### Scenario: 全部信号为空时摘要形态稳定

- **WHEN** 窗口内无离群 run 且日志无救回痕迹
- **THEN** 第六节渲染占位行，自省流程正常完成，不产生任何告警

### Requirement: 采集器故障降级

中途信号采集任一环节异常（索引不可用、事件流损坏、latency 模块导入失败）MUST 降级为该小节空产出 + logger.warning，MUST NOT 阻断 `collect_daily_summary` 返回与其余五节产出（对齐自省「任一源读取失败降级为空段」契约）。

#### Scenario: 索引不可用时自省照常

- **WHEN** run_metrics 索引加载抛异常
- **THEN** 第六节初筛小节为空，warning 留痕，摘要其余节与自省流程不受影响
