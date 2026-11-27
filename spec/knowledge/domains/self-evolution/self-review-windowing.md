# 自省窗口归属（终态归窗键）

<!-- knowledge: capability=self-review-windowing rev=1
     sources=spec/archive/2026-11-27-evo-self-review-window-terminal-attribution -->

每日自省对 run 档案做窗口消费（runs 统计、失败样本、api-stall 停滞聚合、midflight 深扫与离群维）的窗口归属键：以 run 终态事件时刻为准，使同节拍车道因派发先后亚秒级跨缝的 run 不被整只漏计。

## 规则

- **归窗键以 run 终态事件时刻为准**：终态时刻 = run 起点 + 档案末段 run_metrics 行 duration_s（秒，float），自足导出——起点取 run_id 内嵌 epoch（兼容 `-a1`/`-r1` attempt 后缀），duration_s 取档案末段最后一条 run_metrics 行（attempt 多段档案同构，末段胜出，防多段拼接档案取到前段值）。
- **在飞回退与降级留痕**：run 无 run_metrics 行（未终态）或 duration_s 缺失/非正数/解析失败时，回退 run 起点判据并留 logger.debug 级降级痕迹（不进告警面、不产告警）；起点不可辨时维持既有文件 mtime 回退（≈终态时刻），不视为新增降级。
- **单点同径**：runs 统计入口（`_iter_window_runs`）与有界逐 run 扫描入口（`_bounded_per_run_scan`）走同一归属键实现（`_run_window_attr_ts`），下游 runs 统计、失败样本、api-stall 停滞聚合、midflight 深扫与离群维等全部窗口消费口径不分叉。
- **单次入账与跨窗语义**：同一窗聚合内同一 run 只入账一次；已终态 run 整只归入终态所在窗（起点早于窗口起点、终态深入窗内的跨缝 run 在 runs 统计与停滞聚合两节均归本窗）；在飞 run 按回退键入当窗 running 桶，终态后按终态键入账——「上窗记在跑、本窗记终态」并存不视作双计。
- **谓词与锚不变**：`[window_start, window_end]` 闭区间谓词、窗口起点锚（last_run_at）与 anchor_at=window_end 状态推进、聚合入口的窗口上界固定快照（见 [self-review-window-snapshot](self-review-window-snapshot.md)）均不变。
- **有界性**：归属键提取为每候选 run 一次档案末段有界读取（终态邻近行窗口），含被窗外排除者在内仍为单 run 末段常量级。

## 代码锚点

- 归属键单源：`core/self_review.py`（`_run_window_attr_ts` / `_run_metrics_duration_s`）
- 双窗口入口同径消费：`core/self_review.py`（`_iter_window_runs` / `_bounded_per_run_scan`）
- 守卫测试：`tests/test_self_review_window_attribution.py`

## 溯源

- 2026-11-16 evo-self-review-window-terminal-attribution（spec/archive/2026-11-27-evo-self-review-window-terminal-attribution/） — 新建本能力页：归窗键由 run 起点改按终态事件时刻，治夜间全仓代码审查与自省同一巡检固定先审查后自省（两车道 run_at 同为 00:00）时审查 run 起点亚秒级早于窗口起点被整只漏计（三晚实测累计漏 3507.4s ≈ 58.5 分钟）
