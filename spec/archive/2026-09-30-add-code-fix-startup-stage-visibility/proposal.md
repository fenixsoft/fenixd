# Proposal: add-code-fix-startup-stage-visibility

## Why

code-fix 批进入「修复中」后、首条处置落盘前，存在一个无任何条级显示的窗口：

- 实测（2026-09-24）：第 3 批重试 run 空档 65 秒，第 4 批 run 空档 6 分 39 秒。
- 空档构成 = claude 进程内部启动开销：SessionStart hook + init + 首次网络往返
  （固定 ~1 分钟）+ 网关首响应长尾（方差部分，两批相差 5.5 分钟，与 planner
  车道已知的网关长尾同源）。编排侧本身仅 ~3 秒（建树 + 写进度 + spawn）。
- 期间 `item_done=null`，前端按 2026-09-23 口径整段不渲染「本批已处置」行，
  用户感知为「卡死 / 无进展」，已两次引发人工排查。

## What Changes

- `core/code_fix.py` 读侧（`read_progress` 合成段）新增**启动阶段推断**：
  当批处于 `fixing`/`retrying` 且 out 产物零有效行时，读 run 转录文件
  （`.fenix/runs/<run_id>.jsonl`）末行事件类型，合成 `startup_stage`
  字段（阶段短语 + 已等待时长）。
- 前端 `CodeFixProgressCard` 在 `item_done=null` 且 `startup_stage` 非空时
  渲染准备段；`item_done=null` 且 `startup_stage` 为空时维持既有「整段
  不渲染」口径（不回退 2026-09-23 决定）。
- **零写侧 / agent 协议改动**：不改 prompt、不改 out 产物契约、不改编排
  时序；纯读侧合成 + 前端渲染。

## Capabilities

### 1. code-fix-startup-stage-visibility

准备期可见性：批启动后用户能在进度卡看到「agent 正在做什么阶段」而非空白，
包括等待 agent 进程启动、会话初始化、模型分析分组三个粗粒度阶段与已等待时长。

## Impact

- 代码：`core/code_fix.py`（读侧合成）、`core/dashboard/static/src/services/dashboard.ts`（TS 类型）、
  `core/dashboard/static/src/pages/projects/components/CodeFixProgressCard.tsx`（渲染）。
- 数据层 `core/dashboard/data/code_review.py` 的转导对合成字段原样透传，预期零改动（白名单外字段直接透出）。
- 非目标：不治理网关首响应长尾本身（那是 failover/限流课题）；不改写侧协议；
  不承诺阶段 100% 精确（粗粒度即可，用户验收口径「可以不推进 100%，但不能没有显示」）。
