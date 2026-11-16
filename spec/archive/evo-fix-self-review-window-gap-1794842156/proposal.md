## Why

每日自省聚合与夜间全仓 code-review 挂同一 run_once 巡检节拍，且检查点顺序由代码注释强制审查先于自省（core/admin_monitor.py:1989-1996——self_review 收尾会把 last_run_at 覆写为本次聚合冻结的 window_end，审查必须先行）。审查 run 恒早于窗口锚点亚秒级起跑（实测三夜差 51-777 毫秒），而 core/self_review.py 的窗口归属判据按 run 起点时刻过滤（:1678-1680 取 run_id 内嵌整秒 epoch，:245 window_start <= dt <= window_end），起点早零点几秒即被排除；上一窗聚合执行时该 run 尚在飞、无终态产物不列——两窗都不可见。后果：每晚规模最大的 run（本窗实例 1382 轮/121.7 美元/约 3 小时）的停滞与轮次成本永久漏计，已实损连续两晚 50.9 分钟（2847.1+207.7 秒），第三晚（code-review-1794672254，起点早锚点 0.056 秒）判据上已注定再入缝隙；停滞趋势叙事被失真序列扭曲（「连续回落」实为回升）。api-stall-observability 能力页（rev2）未覆盖窗口归属语义，属确定性可修的观测缺口。

## What Changes

- run 级聚合（数据摘要第 2 节 runs 统计与第 6 节逐 run api-stall 行共用同一扫描面）的窗口归属判据从「run 起点时刻落入窗口」改为「run 终态事件时刻落入窗口」，终态时刻取 run jsonl 产物文件 mtime（终态行写完即定格，归档搬移不变）。
- 聚合时刻仍在飞的 run 不列终态统计；起点晚于 window_start 的在飞 run 维持既有「在跑」口径，起点早于锚点且仍在飞的 run 待其终态落入后续窗时按终态归窗补列。窗口按锚点链 [window_start, window_end] 顺序分区，任一已终态 run 恰归一窗，天然去重不重计。
- 不改调度节拍与检查点顺序、不改停滞采样与分级阈值（LATENCY_STALL_SECONDS=60 等原样）、不改摘要渲染契约（rev2 有界流式/降级原样）。

## Capabilities

### Modified Capabilities

- `api-stall-observability`: 聚合窗口归属判据改为终态归窗——消除夜间审查与自省同节拍派发造成的亚秒起点缝隙，runs 统计与停滞聚合两出口同源生效，在飞补列与跨窗去重语义成文。

## Impact

- `core/self_review.py`（_bounded_per_run_scan 归窗谓词单点改造；第 2 节与第 6 节共用该扫描面）
- `tests/test_self_review_window_attribution.py`（新增：三场景回归测试）