# 能力：自省窗口归属（self-review-windowing）

## 概述

每日自省对 run 档案做窗口消费（runs 统计、失败样本、api-stall 停滞聚合、midflight 深扫与离群维）。窗口归属必须与「run 何时在窗内产生工作」对齐，避免同节拍车道因亚秒级派发先后被整只漏计。

## 需求

1. 归窗键：窗口归属以 run 终态事件时刻为准；终态时刻 = run 起点（run_id 内嵌 epoch）+ 档案 run_metrics 行 duration_s。
2. 在飞回退：无 run_metrics 行（run 未终态）或 duration_s 缺失/解析失败时，回退 run 起点判据并留降级痕迹；不得因此产生告警。
3. 单点同径：runs 统计（_iter_window_runs）与有界逐 run 扫描（_bounded_per_run_scan）必须走同一归属键实现，两节口径不得分叉。
4. 单次入账：同一窗聚合内同一 run 只入账一次；已终态 run 归入终态所在窗，在飞 run 按回退键入当窗 running 桶，终态后按终态键入账。跨窗沿用「上窗记在跑、本窗记终态」的快照语义——上窗 running 可见与本窗终态入账并存不视作双计。
5. 兼容：attempt 后缀 run id（-a1/-r1）与 mtime 回退路径保持；[window_start, window_end] 闭区间谓词语义不变；窗口起点锚（last_run_at）与 anchor_at=window_end 状态推进不变。
6. 有界性：归属键提取为每候选 run 一次档案末段有界读取（与既有 _bounded_per_run_scan 末段扫描同预算）。_iter_window_runs 侧由现状零内容读取变为每候选 run（含被窗外排除者）一次末段读，读取量仍为单 run 末段常量级。

## 验收

- 跨缝 run（起点早于窗口起点、终态在窗内）在 runs 统计与停滞聚合两节均可见。
- 在飞 run 行为与改造前一致（running 桶语义不变）。
- 存量窗口测试（tests/test_api_stall_signal_grading.py、tests/test_self_review_window_snapshot.py）零回归。
