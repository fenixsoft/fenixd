## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: agents/self-review.md
  kind: modify
- path: tests/test_self_review_midflight.py
  kind: new
```

## 1. 量化离群初筛

- [x] 1.1 在 core/self_review.py 新增模块级常量与采集函数：`MIDFLIGHT_OUTLIER_MULTIPLIER = 3`、`_collect_metrics_outliers(project_root, window_start, window_end) -> list[dict]`——经 `core.dashboard.data.runs` 公共访问器（延迟导入，对齐 `_run_terminal_success` 先例）读窗口内全量 run_metrics，按 agent_type 分组对 turns/cost_usd/duration_seconds 三维度做「组中位数 × 3」离群判定；组内该维度有效样本 < 3 或全组 0/缺失时该维度跳过；输出样本含 run_id/path（事件流文件路径，取自 `_collect_run_files` 并集）/agent_type/terminal/离群维度值/组中位数
- [x] 1.2 同函数接入窗口归属与 run 文件并集：复用 `_collect_run_files` + `_run_start_ts` + `_in_window`，排除 `review-` 前缀，window_end 为入口冻结快照（对齐 `collect_runs_stats` 快照化契约）；索引查不到的 run 跳过不报错
- [x] 1.3 tests/test_self_review_midflight.py 新增初筛用例：成功但 turns 离群入选（附组中位对照）、样本 < 3 组跳过、cost 全组缺失跳过、索引异常返回空 list

## 2. 离群 run 事件流深扫

- [x] 2.1 在 core/self_review.py 新增 `_scan_run_midflight(path, max_lines=20000) -> dict`：逐行 readline + 单行 json.loads（失败跳过）构建事件生成器喂 `core.agent_runner.latency.latency_samples_from_events`（延迟导入）取样本，`latency_stats` 算 stall 计数与 max；同遍累计 error/stderr 事件计数与首条摘要（≤140 字符）；超 20000 行停止并置 truncated 标记；MUST NOT 整文件读入内存
- [x] 2.2 新增 `_collect_midflight_scans(project_root, outliers, window_start, window_end) -> list[dict]`：仅对 1.1 产出的离群 run 逐个以其 path（1.1 输出携带的事件流文件路径）调 2.1，输出含 run_id/stall/max_gap/中途error与stderr计数/摘要/truncated；无离群 run 时返回空；path 不存在/读取失败按该 run 空产出跳过，不阻断其余 run
- [x] 2.3 tests/test_self_review_midflight.py 新增深扫用例：真实 stream-json 形态夹具（user 包裹 tool_result block，禁用顶层 tool_result 合成形态作主用例）成功 run 的 stall=3 与 stderr=2 被采集、超限截断标注 truncated、单行坏 JSON 跳过不抛异常

## 3. 编排层救回痕迹归集

- [x] 3.1 在 core/self_review.py 新增模块级常量 `_RESCUE_TRACE_PATTERNS` 与 `_collect_rescue_traces(project_root, window_start, window_end) -> dict`：流式扫描窗口内 .fenix/logs/fenixd.log 行，按「关键词 → 组件」成对过滤、归组计数 + 每组至多 5 条样本（时间戳 + message 截断）；日志缺失/解析失败降级空 dict。模式清单以 2026-09-25 实测文案为准（评审取证）：`provider switched`（agent_runner，如 "provider switched inferaiapi.com → corealgos.com for '<spec>'"）、`gave up`（pm_engine，如 "Failed to create worktree (gave up: …)"）、`in-place retry`（agent_runner Artifact gate 续跑行）。关键词与组件 MUST 成对绑定——泛词 `retry` 单独成模式会卷入 event_bus 大量无关行（实测 1156 条）；`do_continue`/`no longer exists`/`fresh create` 当前日志零命中，不得作为主模式（可注释留作兜底）。窗口早于当前日志起点（轮转）时按日志起点截断（对齐既有第 4 节「仅扫 fenixd.log」口径），不强制回扫 .1
- [x] 3.2 tests/test_self_review_midflight.py 新增归集用例：窗口内混合痕迹按组计数正确、样本条数截断至 5、窗口外行不计入、日志文件缺失返回空

## 4. 摘要注入与提示词

- [x] 4.1 在 core/self_review.py 的 collect_daily_summary 既有第 5 节后追加「## 6. 中途信号（含成功 run）」：依次渲染初筛离群样本、深扫结果、救回痕迹三小节（各有产出才渲染对应小节），全空时渲染占位行；调用侧 try/except 任一环节异常降级空产出 + logger.warning 不阻断
- [x] 4.2 更新 agents/self-review.md：数据摘要说明增加第六节语义（中途信号=含成功 run 的过程性证据）与条目引导（作为 waste/improvements 证据来源，量化离群与停滞可立项；不改铁律与既有任务结构）
- [x] 4.3 tests/test_self_review_midflight.py 新增注入用例：混合信号渲染三小节、全空渲染占位行、某环节抛异常时摘要仍完整返回且其余五节不受影响
