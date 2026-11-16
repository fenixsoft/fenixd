# 提案：自省聚合改按终态时刻归窗

## 背景与问题

每日自省（self-review）的窗口消费全部按「run 起点是否落在 [window_start, window_end]」归窗（core/self_review.py:245，_iter_window_runs 与 _bounded_per_run_scan 两处同口径实现）。夜间全仓代码审查与自省在 admin_monitor 同一轮巡检里固定先审查后自省（core/admin_monitor.py:2030-2072），两车道 run_at 同为 00:00——窗口起点系统性晚于审查 run 起点，起点早于窗口起点亚秒级的 run 被整只排除。

已发生损失（三晚连续、已回源量化）：

- 11-14 窗漏 code-review-1794585799：停滞 2847.1 秒（30 次/max 281.2 秒）
- 11-15 窗漏 code-review-1794499313：停滞 207.7 秒（2 次/max 104.2 秒）
- 11-16 窗漏 code-review-1794672254：停滞 452.6 秒（6 次/max 112.9 秒；该 run 134.3 分钟/113.47 美元的全仓审查）

累计漏计观测 3507.4 秒 ≈ 58.5 分钟；runs 统计同缝少计（本窗落盘摘要「总 run 数: 11」按终态口径应为 12）。第 4 例已在形成：code-review-1794758591 起点早于现窗口锚点 0.82 秒，其 69.2 秒停滞按现判据将再漏。

## 目标

1. 窗口归属键从 run 起点改为 run 终态事件时刻（自足导出：run_id 内嵌起点 + 档案 run_metrics 行 duration_s），runs 统计与停滞聚合等全部窗口消费单点改键、口径一致。
2. 在飞 run（尚无 run_metrics 终态行）回退起点判据，维持现行「上窗记在跑、本窗记终态」的单次终态入账语义。

## 非目标

- 不改窗口起点锚定语义（last_run_at）与 anchor_at=window_end 状态推进。
- 不做「固定容差带」方案（状态文件无聚合完成时刻锚，需新增隐含契约，性价比低）。
- 不改调度时点（admin.code_review.run_at 错峰属配置面运营选项，见 design 风险段，不在本 SPEC 代码面内）。

## 与存量的关系

- 起点归窗的设计来源是归档件 2026-09-25-evo-self-review-runs-archive-stats，本 SPEC 以修订其归窗口径的方式落地，不推翻其统计本体。
- 知识页 api-stall-observability（cost-observability 域）只约定聚合有界流式与降级契约，未覆盖窗口归属缝隙；落地后应经知识回填通道补记新口径。
