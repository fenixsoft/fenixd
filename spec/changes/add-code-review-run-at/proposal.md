## Why

自省、周期代码审查、回归三条车道的触发时点同源读 `admin.self_review.run_at`（`core/admin_monitor.py` 的 `_run_code_review_checkpoint` 与 `_run_regression_checkpoint` 均以 `sr_cfg["run_at"]` 判定），当前配置 01:00 三车道齐发：全仓审查（数十文件 LLM 调用）＋回归＋自省（连带 evo 分析/规划链）同时压向 LLM 网关。2026-10-06 05:50 实测打出账户级 429 限流（错误码 1302「您的账户已达到速率限制」）：spec-review 连续 5 次 0-rounds 秒败触发熔断，同窗 evo 链路同受影响；CLI 内建重试仅 2 次亚秒间隔，无法穿越限流窗口。解耦各车道触发时点是结构性削峰，不依赖重试参数调优。

本变更仅解耦代码审查车道；回归车道同槽位的事实记录在案，另行立项（非目标）。

## What Changes

- 新增独立配置键 `admin.code_review.run_at`（本地时间 HH:MM）：`ConfigLoader.get_code_review_config` 单源读取并兜底；**缺省回退 `admin.self_review.run_at`**——未配置时行为与现状完全一致（用户定调：暂不挪时点，仅解耦配置能力，时点之后可在 Dashboard 设置页自行调整）。
- `_run_code_review_checkpoint` 触发判定从 `sr_cfg["run_at"]` 换读 `cr_cfg["run_at"]`。
- 审查窗口水位归审查车道自身（解耦的必要配套，防覆盖缺口）：`code_review_state.json` 新增 `last_run_at`（本轮审查完成时刻），`compute_window` 优先读它、缺失回退自省 `last_run_at`（存量/首跑=现状路径）。若只解耦触发时点而不动窗口来源，独立时点晚于自省时窗口只剩「自省→审查」段，两段审查之间的变更会出现无人覆盖的缺口。
- Dashboard 设置页 QualityPanel 增加触发时点字段（`config_admin.py` 透出＋前端 HH:MM 输入）。
- `.fenix/config.template.yaml` 文档化新键。

**不变式**：调度守卫不变（同自然日防重/未到不触发/`enabled` 开关）；检查点在巡检循环中仍先于自省检查点执行（防 `last_run_at` 覆写退化，既有 design D3 时序）；缺省路径（未配置新键）行为逐位等于现状。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `code-review-agent`: 「周期窗口与自省同源」需求修改——触发时点改读独立 `admin.code_review.run_at`（缺省回退自省 run_at），不再强制与自省时点对齐；审查窗口水位改由审查车道自身状态承载（回退自省）；窗口同源回退与调度守卫不变。
