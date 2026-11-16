# 设计：终态归窗键

## 现状

- 判据：core/self_review.py:241-245 `def _in_window(dt, window_start, window_end=None)`，`return window_start <= dt <= window_end`（闭区间）。
- 起点提取：_run_start_ts（:350-353）从 run_id 内嵌 epoch 秒正则提取（_RUN_TS_RE :189，兼容 -a1/-r1 attempt 后缀），缺失回退文件 mtime。
- 两处归属键：_iter_window_runs :1099-1101（喂 runs 统计/失败样本）、_bounded_per_run_scan :1678-1680（喂停滞聚合/深扫/midflight 离群维）。下游 collect_runs_stats、collect_failed_run_samples、_collect_api_stall_aggregates、_collect_midflight_scans、_collect_metrics_outliers 均经此二入口，单点改键自动继承。
- 窗口起点：last_run_at（.fenix/self_review_state.json），上窗锚点=聚合冻结时刻（_save_state anchor_at=window_end）。

## 数据面事实（已回源）

- events jsonl 末段形态：assistant → run_metrics（带 duration_s，无 timestamp）→ result（is_error/subtype，无 timestamp）。终态时刻 = 起点 + duration_s 可精确导出；daemon 日志侧 run_metrics 行带 timestamp 可作交叉核对（有轮转出窗风险，不作主源）。
- 在飞 run 无 run_metrics 行 → 无终态时刻，必须回退。

## 方案

新增辅助 _run_window_attr_ts(run_id, run_file) 返回归属时刻：

1. 起点 = _run_start_ts(run_id)（保留 mtime 回退）。
2. 在档案末段读 run_metrics 行 duration_s（秒，float；attempt 多段档案取末段最后一条 run_metrics 行）；解析成功且大于 0 → 返回起点 + duration_s（终态时刻）。
3. 无 run_metrics 行/解析失败 → 回退起点时刻，并计一次降级痕迹（logger.debug 级，不进告警面）。

_iter_window_runs 与 _bounded_per_run_scan 的 `if not _in_window(...)` 改用该辅助返回值；谓词与闭区间语义不变。

## 边界与语义

- 在飞 run：回退起点 → 现行为保持（起点在窗内的在跑 run 继续计入 running 桶）；终态落本窗时按终态入账一次，不双计。
- 跨窗终态 run（起点上窗、终态本窗）：整 run 归本窗，活动级可见性后移属单次归账取舍（上窗已按在跑可见）。
- attempt 后缀 run id：_RUN_TS_RE 兼容不变。
- 时区：全链 aware UTC（timelib from_epoch），duration_s 与起点同源无钟差。

## 测试策略

- fixture 形态参照 tests/test_api_stall_signal_grading.py 的 _write_run/_stall_events（真实 user 包裹、逐事件 timestamp、run_id 内嵌 epoch 控制窗口归属）与 tests/test_self_review_window_snapshot.py 的边界断言风格。
- 核心用例：跨缝 run（起点早窗口起点亚秒级、终态深入窗内 → 两节均计入）；在飞回退；缺 duration_s 降级；跨窗终态单次入账；attempt 后缀兼容。

## 风险

- duration_s 单位为秒（float），秒粒度起点带来的余量对百秒级窗口问题无关紧要。
- 归属键提取为每候选 run 一次档案末段有界读取：_bounded_per_run_scan 侧本就逐 item 尾扫，预算量级不变；_iter_window_runs 侧由现状零内容读取变为每候选 run（含被窗外排除者）一次末段读，仍为单 run 常量级、行数有界。
- 运营面建议（非本 SPEC 代码面）：admin.code_review.run_at 与 self_review.run_at 同为 00:00 是缝隙根，错峰一分钟可立即缓解；该键已由归档件 2026-10-15-add-code-review-run-at 落地，属配置面决策，交人工裁量。
- 与在途 spec 无文件碰撞面（改动集中在 core/self_review.py 与新测试文件）。
