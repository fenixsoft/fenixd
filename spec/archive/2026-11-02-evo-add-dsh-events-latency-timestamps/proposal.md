## Why
产品主链 dsh 化后停滞与延迟观测结构性失效：fenix-prototype 全链 6 run（441 轮次、最大 187k 输入 token）0 延迟样本；根因单一——dsh 事件流全行无时间戳字段，既有配对函数（latency.py 已兼容 dsh 事件形态）无从出样。失明 WARNING 无去重累计 178 条/120+ run/14 天。一处投影层改动即可同时恢复在线旁路、转录落盘、事后分析三个消费面。

## What Changes
1. DshEventProjector 投影产出事件统一打到达时刻 timestamp。
2. 失明 WARNING 按（harness,事件形态）一次性去重防刷屏，并修正文案（真实根因是时间戳缺失非 tool_result 识别）。
3. 契约测试：投影事件携带 timestamp；dsh 事件流经配对函数产出 >0 延迟样本。

## Impact
- core/agent_runner/harness/dsh_adapter.py、core/agent_runner/runner.py
- tests/test_dsh_projection.py、tests/test_run_latency_stats.py 补用例
- latency.py 无需改码（顶层 tool_result 兼容分支已覆盖 dsh 投影形态）