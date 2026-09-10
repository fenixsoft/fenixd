# Proposal: fix-retry-orphan-active-runs

## Why

Dashboard 概览「活跃 Agent」长期虚高：2026-09-10 实测显示 23 个，真实活跃仅 2 个（21 具尸体计入）。

根因双层：

1. **写侧**：runner 原地退避重试（provider 瞬断通道 `runner.py:2175-2197`、artifact-gate 通道 `runner.py:2047-2070`）写完 `transient_retry` 事件后 `continue`，重试 attempt 因 `transient_retries` 递增换新 `sub_run_id`（`runner.py:1922-1923`）重开新产物文件——旧文件末行永久停在 `transient_retry`，无人补写终态，打破 `classify_run` 依赖的「终态后置」不变量。每个 run 每经历一次原地重试即弃置一具「running」尸体（实测典型家族 8 文件 6 尸）。
2. **读侧**：`classify_run`（`data.py:2252`）只认 `result/error/interrupted/cancelled` 四终态，`transient_retry` 尾行落兜底判 `running`；且无任何 mtime 陈旧度信号——停更 3 天的死文件照样计入活跃。`project_summary`（`data.py:2540`）按 `status in ("running", "empty")` 求和全数中招。

09-05 的「活跃 Agent 数虚高」修复（`_RUN_TERMINAL_STATUS_MAP` + interrupted 停机补写）只覆盖 daemon 停机屠杀变体；本次尸体产生于 daemon 正常运行期间（重试换文件），interrupted 补写永远够不到。同类症状、新缺口。

## What Changes

方案 C（写侧根治 + 读侧兜底，双管）：

1. **写侧补写 `superseded` 终态**：两处原地重试通道在 `transient_retry` 事件落盘后、`continue`/`break` 弃置当前产物文件前，向同一文件补写 `superseded` 终态事件（语义：本文件到此为止，重试在新文件继续），恢复「终态后置」不变量。
2. **读侧 `superseded` 终态映射**：`_RUN_TERMINAL_STATUS_MAP` 增 `superseded → superseded`。
3. **读侧 mtime 陈旧兜底**：末行非终态（running/empty）且产物 mtime 停更超过阈值（模块常量，30 分钟）→ 判新状态 `stale`（弃置/断尾，读侧专属枚举，非事件类型）。消化全部存量尸体 + 拦截一切未知断尾形态（如进程被杀残留普通对话尾行）。
4. **前端兼容**：时间轴 run 节点 status 渲染补 `stale` 分支（灰色，区别于 running 蓝 / error 红）。

## Capabilities

- `run-superseded-terminal`：原地重试弃置产物的终态补写与读侧陈旧兜底

## Impact

- 代码：`core/agent_runner/runner.py`（两处补写点）、`core/dashboard/data.py`（终态映射 + 陈旧兜底）、`core/dashboard/static/src/pages/projects/detail.tsx`（stale 渲染）
- 存量数据：21 具尸体文件无需清扫脚本，读侧 mtime 兜底自动消化
- 无配置项新增（阈值用模块常量，不触「新增配置必须带界面」约束）
- 消费方：`project_summary` 活跃计数自动剔除（只认 running/empty）；时间轴/运行历史列表新增 stale 展示态
