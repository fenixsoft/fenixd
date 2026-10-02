<!-- knowledge: capability=self-review-midflight-signals rev=1 sources=spec/archive/2026-10-03-add-self-review-midflight-signals -->

# 自省中途信号采集（含成功 run）

自省数据摘要的第六数据源：采集窗口内全部车道 run（含终态成功者）的中途浪费与险情机械化信号，补足终态分类（见 [self-review](self-review.md)）看不到的过程信息——成功收尾的 run 仍可能中途经历大量空转轮次、API 停滞、出错后被编排层救回。

## 现行规则

- 采集范围同 run 统计口径：窗口内全部 run（当前目录 ∪ 归档并集，排除 `review-` 前缀，口径同 `collect_runs_stats`），终态成功的 run 同样入选；窗口归属沿用 run_id 内嵌时间戳（缺失回退产物文件 mtime）与聚合入口冻结的窗口快照。
- 初筛零事件流读取：全部 run 先经 run_metrics 日志索引（`core.dashboard.data.runs` 公共访问器）做量化初筛，初筛阶段禁止读取任何 run 事件流文件；初筛维度为 `turns`、`cost_usd`、`duration_seconds`。
- 离群判定按 `agent_type` 分组：run 指标 > 组内窗口中位数 × 3 即离群，成功与失败 run 同口径；不同 agent_type 的量级不可比，禁止全局基线。倍数 3 与最小样本数等为模块顶常量（宁漏勿噪的保守值），可按实测调参。
- 样本不足不出假离群：组内有效样本 < 3 时该维度跳过（2 个样本互为彼此的离群对照无意义）；某维度全组值为 0/缺失时跳过（部分 provider 不回传 cost_usd，不产假离群）。
- 索引缺失不判离群：run_metrics 索引查不到的 run（旧日志轮转出窗）跳过初筛，不视为离群也不报错。
- 深扫仅限离群 run：无离群 run 时深扫环节整体跳过；深扫覆盖事件流全程（停滞与中途 error 分布在转录中段，尾部窗口会复刻终态分类盲区）。
- 深扫采集两类信号：停滞信号复用 `core.agent_runner.latency` 纯函数（`latency_samples_from_events` + `latency_stats`），报告 stall 计数与最长往返秒数，阈值沿用 `LATENCY_STALL_SECONDS=60.0`；中途 error/stderr 事件记计数 + 首条摘要（截断，当前 ≤140 字符）。
- 深扫必须流式逐行解析（逐行 `readline` + 单行 `json.loads`，坏行跳过），禁止将整文件读入内存（单行事件可达数 MB）；单 run 深扫行数上限 20000 行，超限停止并标注 `truncated`，不抛异常。
- 编排救回痕迹按「关键词 → 组件」成对归集：`provider switched`（agent_runner，换道）、`in-place retry`（agent_runner，transient 退避续跑）、`gave up`（pm_engine，派发收尾 error）。泛词 retry 不得单独成模式（会卷入 event_bus 无关行），组件错配行不卷入；关键词清单为模块常量并注释来源日志语句，日志文案变更时单点维护。
- 痕迹不按 run_id 关联：相关日志行的 run_id 口径不统一（部分行只有 spec 名），按关键词归组计数 + 每组最多 5 条样本（时间戳 + 摘要截断）已足够自省 LLM 与 runs 统计、失败样本交叉核对；不引入第三个 run_id 解析口径。
- 日志容错：日志文件缺失或解析失败时痕迹小节降级为空（不阻断自省）；窗口早于当前日志起点（轮转）时按日志起点截断（对齐既有日志节口径）。
- 摘要注入形态：`collect_daily_summary` 在既有五节后追加「## 6. 中途信号（含成功 run）」，含初筛离群 / 深扫 / 救回痕迹三小节；三类信号各有产出才渲染对应小节，全部为空时渲染占位行（「（窗口内无中途信号）」）。
- 降噪与只读铁律：中途信号不产生 admin 告警（告警降噪：合成兜底静默化）、不写 run 产物文件、不触发任何写操作。
- 语义引导：`agents/self-review.md` 同步承载第六节说明——中途信号作为 waste / improvements 的证据来源，成功 run 的中途浪费同样可立项；引用时遵守「含证据 / 含调查评估」质量标准。
- 故障降级：采集任一环节异常（索引不可用、事件流损坏、latency 模块导入失败）降级为对应小节空产出 + `logger.warning`（含异常原文），不阻断 `collect_daily_summary` 返回与其余五节产出（对齐自省「任一源读取失败降级为空段」契约）。

## 关键行为

流水线四步：run_metrics 量化初筛（全量、零事件流读取）→ 仅离群 run 流式深扫事件流（停滞 + 中途 error/stderr）→ fenixd.log 救回痕迹关键词归集 → 三小节注入数据摘要第六节。初筛离群的典型形态是「成功但轮次/耗时离群」（如组中位 10 轮、某成功 run 45 轮），此类 run 是中途浪费立项的主要来源。

## 溯源

- 2026-10-03 add-self-review-midflight-signals（spec/archive/2026-10-03-add-self-review-midflight-signals） — 新增第六数据源：量化离群初筛（同 agent_type 中位 ×3、样本 <3 跳过）、离群 run 事件流流式深扫（stall/中途 error、2 万行截断）、编排救回痕迹关键词归集；只进摘要不进告警，采集器故障降级不阻断自省
