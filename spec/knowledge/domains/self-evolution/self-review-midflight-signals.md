<!-- knowledge: capability=self-review-midflight-signals rev=4 sources=spec/archive/2026-10-03-add-self-review-midflight-signals,spec/archive/2026-10-05-evo-reduce-cli-stderr-noise-attribution,spec/archive/2026-10-08-evo-split-self-review-stderr-noise-count,spec/archive/2026-10-30-evo-add-run-metrics-lane-baseline -->

# 自省中途信号采集（含成功 run）

自省数据摘要的第六数据源：采集窗口内全部车道 run（含终态成功者）的中途浪费与险情机械化信号，补足终态分类（见 [self-review](self-review.md)）看不到的过程信息——成功收尾的 run 仍可能中途经历大量空转轮次、API 停滞、出错后被编排层救回。

## 现行规则

- 采集范围同 run 统计口径：窗口内全部 run（当前目录 ∪ 归档并集，排除 `review-` 前缀，口径同 `collect_runs_stats`），终态成功的 run 同样入选；窗口归属沿用 run_id 内嵌时间戳（缺失回退产物文件 mtime）与聚合入口冻结的窗口快照。
- 初筛零事件流读取：全部 run 先经 run_metrics 日志索引（`core.dashboard.data.runs` 公共访问器）做量化初筛，初筛阶段禁止读取任何 run 事件流文件；初筛维度为 `turns`、`cost_usd`、`duration_seconds`。
- 离群判定按车道分组，成功与失败 run 同口径；不同车道的量级不可比，禁止全局基线。车道归属证据分层：指标行 `agent_type` 字段优先；缺失时以 run_id 前缀经 `infer_run_agent_type` 推断——前缀表 `RUN_ID_AGENT_PREFIXES` 为唯一真源（dashboard 时间线归属同源受益），`evo-` 前缀归 evolution，未识别前缀按共享回退归 agent，无车道混合组形态不存在。倍数 3 与最小样本数等为模块顶常量（宁漏勿噪的保守值），可按实测调参。
- 批量车道基线取近期批分布：批量相关车道（如 code-fix）的 turns 基线为同车道窗口内最近 10 个有效批（不含当前 run、按时间倒序）的 P90——正常长批落在分布内不出旗标，超分布的异常批仍被标出；有效样本不足最小样本阈值时回退窗口中位（非批量车道基线恒为窗口中位）；「同链」解析（run_id 可解析 spec 段时优先取同链批）是可选增强，不作默认依赖。
- 定向重试轮不入常态分布：按 run_id 后缀 `-r<n>`/`-a<n>` 辨识（与 dashboard 剥后缀同口径），单独标注并排除出基线样本；无后缀不可辨时不排除、保守入基线。
- 成本维度全车道可观测：maintenance 三车道（run_evolution/run_code_review/run_code_fix）收尾补写 `_log_run_metrics` 富指标行（含 agent_type/cost_usd），context metrics 兜底行补 agent_type，成本维度借此参与各车道基线；初筛仅在写点成本不可得时交叉读 `.fenix/cost/*_tokens.json` 台账补样本（写侧主路径、读侧条件兜底），任一车道不得对成本维度整体失明。
- 样本不足不出假离群：组内有效样本 < 3 时该维度跳过（2 个样本互为彼此的离群对照无意义）；某维度全组值为 0/缺失时跳过（部分 provider 不回传 cost_usd，不产假离群）。
- 索引缺失不判离群：run_metrics 索引查不到的 run（旧日志轮转出窗）跳过初筛，不视为离群也不报错。
- 深扫仅限离群 run：无离群 run 时深扫环节整体跳过；深扫覆盖事件流全程（停滞与中途 error 分布在转录中段，尾部窗口会复刻终态分类盲区）。
- 深扫采集两类信号：停滞信号复用 `core.agent_runner.latency` 纯函数（`latency_samples_from_events` + `latency_stats`），报告 stall 计数与最长往返秒数，阈值沿用 `LATENCY_STALL_SECONDS=60.0`；中途 error/stderr 事件记计数 + 首条摘要（截断 ≤140 字符）。stderr 摘要与计数按噪声分离：首条摘要跳过 CLI 启动期诊断噪声行（判别单源经 provider_circuit 的 `is_cli_stderr_noise` 入口，禁止在 self_review 内复制 pattern，见 [cli-stderr-noise-filtering](../run-resilience/cli-stderr-noise-filtering.md)），全噪声置空；`stderr_count` 只计非噪声行，噪声行单独计入 `stderr_noise_count`。
- 深扫行以非噪声 stderr 计数渲染：「中途stderr=」取 `stderr_count`（非噪声口径），`stderr_noise_count > 0` 时同行追加「（另 N 条已知 CLI 启动噪声）」注记，噪声为 0 不出注记——「全噪声」与「无 stderr」在摘要上可区分，恒在的启动噪声不再冒充中途信号；计数分离不触碰 run 产物 jsonl 的 stderr 原始事件（不过滤、取证现场完整），瞬断/切换分类判据仍读原始 stderr 信号。
- 深扫必须流式逐行解析（逐行 `readline` + 单行 `json.loads`，坏行跳过），禁止将整文件读入内存（单行事件可达数 MB）；单 run 深扫行数上限 20000 行，超限停止并标注 `truncated`，不抛异常。
- 编排救回痕迹按「关键词 → 组件」成对归集：`provider switched`（agent_runner，换道）、`in-place retry`（agent_runner，transient 退避续跑）、`gave up`（pm_engine，派发收尾 error）。泛词 retry 不得单独成模式（会卷入 event_bus 无关行），组件错配行不卷入；关键词清单为模块常量并注释来源日志语句，日志文案变更时单点维护。
- 痕迹不按 run_id 关联：相关日志行的 run_id 口径不统一（部分行只有 spec 名），按关键词归组计数 + 每组最多 5 条样本（时间戳 + 摘要截断）已足够自省 LLM 与 runs 统计、失败样本交叉核对；不引入第三个 run_id 解析口径。
- 日志容错：日志文件缺失或解析失败时痕迹小节降级为空（不阻断自省）；窗口早于当前日志起点（轮转）时按日志起点截断（对齐既有日志节口径）。
- 摘要注入形态：`collect_daily_summary` 在既有五节后追加「## 6. 中途信号（含成功 run）」，含初筛离群 / 深扫 / 救回痕迹三小节；三类信号各有产出才渲染对应小节，全部为空时渲染占位行（「（窗口内无中途信号）」）。
- 降噪与只读铁律：中途信号不产生 admin 告警（告警降噪：合成兜底静默化）、不写 run 产物文件、不触发任何写操作。
- 语义引导：`agents/self-review.md` 同步承载第六节说明——中途信号作为 waste / improvements 的证据来源，成功 run 的中途浪费同样可立项；引用时遵守「含证据 / 含调查评估」质量标准。
- 故障降级：采集任一环节异常（索引不可用、事件流损坏、latency 模块导入失败）降级为对应小节空产出 + `logger.warning`（含异常原文），不阻断 `collect_daily_summary` 返回与其余五节产出（对齐自省「任一源读取失败降级为空段」契约）。

## 关键行为

流水线四步：run_metrics 量化初筛（全量、零事件流读取）→ 仅离群 run 流式深扫事件流（停滞 + 中途 error/stderr）→ fenixd.log 救回痕迹关键词归集 → 三小节注入数据摘要第六节。初筛基线按车道取口径：非批量车道为组内窗口中位，批量车道（如 code-fix）为近期批分布 P90。初筛离群的典型形态是「成功但轮次/耗时/成本超分布」（如组中位 10 轮、某成功 run 45 轮），此类 run 是中途浪费立项的主要来源。

## 溯源

- 2026-10-03 add-self-review-midflight-signals（spec/archive/2026-10-03-add-self-review-midflight-signals） — 新增第六数据源：量化离群初筛（同 agent_type 中位 ×3、样本 <3 跳过）、离群 run 事件流流式深扫（stall/中途 error、2 万行截断）、编排救回痕迹关键词归集；只进摘要不进告警，采集器故障降级不阻断自省
- 2026-10-05 evo-reduce-cli-stderr-noise-attribution（spec/archive/2026-10-05-evo-reduce-cli-stderr-noise-attribution） — 修订深扫 stderr 采集：首条摘要跳过 CLI 启动期诊断噪声行、全噪声置空，判别统一走框架噪声常量
- 2026-10-08 evo-split-self-review-stderr-noise-count（spec/archive/2026-10-08-evo-split-self-review-stderr-noise-count） — 修订深扫 stderr 计数口径：`stderr_count` 只计非噪声行、噪声行单列 `stderr_noise_count`，深扫行追加「另 N 条已知 CLI 启动噪声」注记；取代 cli-stderr-noise-filtering 侧「stderr 计数保留全量」计数条款（first_stderr 降噪与全噪声置空语义不受影响）
- 2026-10-30 evo-add-run-metrics-lane-baseline（spec/archive/2026-10-30-evo-add-run-metrics-lane-baseline） — 修订初筛基线语义：分组键在指标行缺 agent_type 时按 run_id 前缀推断（`evo-` 前缀入共享前缀表，归 evolution）、批量车道 turns 基线改组内近 10 批 P90 分布（样本不足回退窗口中位）、定向重试轮按 `-r`/`-a` 后缀排除出基线样本；maintenance 三车道收尾补富指标行（agent_type/cost_usd）、context 兜底行补 agent_type，成本维度全车道可观测（读侧成本台账交叉读仅为写点不可得的条件兜底）
