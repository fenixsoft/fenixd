# Planner 提效三件套 — 路由地图注入 / 生成节流 / 延迟直方图

## Why

planner 单轮 30-70 分钟零产出已实证为「大轮次任务 × 网关长尾延迟」的必然（2026-09-05 转录分析：54-148 次工具调用 × 中位 1-10s + ~25% 轮次撞 60-185s 长尾停顿，双峰与轮次位置无关=缓存未命中/网关排队签名；成功对照轮同款画像 77 轮 28 分钟）。三个杠杆互不替代：**减少轮次**（路由地图把逐轮 grep 源码取证压缩为读一份索引）、**降低并发互挤**（planner 阶段节流，用户可选开关）、**让长尾可见**（run 级 API 延迟直方图，替代事后转录考古）。

## What Changes

- **路由地图注入（②）**：项目声明生成器 `bin/gen-route-map.py`，框架在 planner 启动前对 impl worktree 执行并产出 `<worktree>/.fenix/route-map.md`（HEAD 键控复用，HEAD 变更即重生成）；prompt 注入该索引，措辞为「已知入口索引、非穷尽清单」——spec 涉及但地图未覆盖的入口 planner 仍须自行取证。生成器缺失/失败 fail-open（回退现状逐轮 grep）。dashboard 自带生成器作参考实现与自检样例。
- **planner 生成节流（③）**：planner 阶段（`run_planner`）加跨管线信号量，配置键 `verify.planner_max_concurrent`（0/缺省=不节流）。**开关与注解放设置页「并发度」页签**（ParallelSettingsPanel），注解简要说明作用与代价供用户选择（配置键与 UI 同步铁律）。节流等待不得触发 dispatch_stalled 误报。
- **API 延迟直方图（④）**：`_run_claude` 流式循环读侧统计每轮 API 等待（事件 timestamp 已在盘），run 结束打摘要日志（轮数/中位/p90/max/长尾>60s 计数）；失败 run 将摘要附入证据上下文供 admin/人工诊断「卡死 vs 慢」；不做独立人工告警（告警降噪铁律）；附事后分析脚本可扫任意历史转录。

## Capabilities

### New Capabilities

- `planner-route-map`: 路由地图生成协议（项目声明生成器、impl worktree 为源、HEAD 键控复用、fail-open）与 prompt 注入（索引措辞、抽查豁免、静态地图兼容——无生成器项目可人工提交 `.fenix/route-map.md`）
- `planner-generation-throttle`: planner 阶段跨管线并发上限（信号量、配置键、设置页开关与注解、节流等待与 recovery watch 的相容性）
- `run-latency-observability`: run 级 API 延迟统计（在线摘要日志、失败证据附加、事后分析脚本；不含独立告警）

### Modified Capabilities

（无——归档能力 `parallelism-config`/`priority-parallel-scheduler` 的全局并发调度语义不变（节流是管线内新增的第二道门）；`stuck-timeout-single-source`/`post-recovery-patrol` 的卡死判定阈值与语义不变（本 SPEC 仅要求新等待形态不被误判）；`agent-run-artifacts`/`agent-cost-control` 不变（延迟统计是新增读侧产物）。）

## Impact

- **代码**：`core/pm_engine/verification.py`（阶段1 前置生成地图 + 信号量包裹 run_planner）、`core/agent_runner/prompt_builder.py`（route-map 段注入）、`core/agent_runner/runner.py`（流式循环延迟统计 + run 末摘要）、`core/dashboard/static/src/pages/settings/components/ParallelSettingsPanel.tsx`（节流开关+注解）、`core/dashboard/static/src/services/dashboard.ts`（配置读写）
- **新文件**：`bin/gen-route-map.py`（dashboard 项目生成器参考实现）、`bin/analyze_run_latency.py`（事后分析脚本）、`.fenix/route-map.md`（运行时产物，gitignore）
- **测试**：`tests/test_planner_route_map.py`、`tests/test_planner_throttle.py`、`tests/test_run_latency_stats.py`（new）+ prompt/verify 相关回归
