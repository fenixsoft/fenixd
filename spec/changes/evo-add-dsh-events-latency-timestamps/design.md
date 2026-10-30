## Context
- 投影层：core/agent_runner/harness/dsh_adapter.py DshEventProjector.ingest :283-317、_project 投影表 :339-482；投影产出事件现无 timestamp。
- 消费面：latency.py:87-97 配对取 entry['timestamp']；在线旁路 runner.py:6433-6443；事后分析 bin/analyze_run_latency.py——三面共用同一事件形态，补时间戳一改全通。
- 告警发射点：runner.py:7032-7045（rounds==0 且 turn_count>0 时无条件触发），现无去重，累计 178 条。

## Goals / Non-Goals
- Goals：dsh 事件可配对；告警收敛；主链与维护链观测一次恢复。
- Non-Goals：不改 dsh 侧事件产生器（打点在 fenixd 读侧投影层）；不改延迟统计口径与停滞阈值；不动 evo-api-stall-signal-grading 的分级聚合。

## Design
- ingest 入口统一记 time.time() 到达时刻并随事件透传投影表，投影产出事件带 timestamp；dump 文件维持原样（不加字段，避免体积膨胀）。
- 告警去重复用进程级已告警集合范式（参照既有单实例去重模式），键为（harness,事件形态）。
- 文案改为「事件流缺时间戳/无法配对」如实描述。

## Risks / Trade-offs
- 到达时刻≠API 发起时刻，样本含投影排队延迟——对停滞（>60s）量级判断影响可忽略，后续如需精确可由 dsh 侧补事件内时钟。
- dump 与转录双落盘路径均从投影产出取事件，时间戳自然一致，无双源分歧。