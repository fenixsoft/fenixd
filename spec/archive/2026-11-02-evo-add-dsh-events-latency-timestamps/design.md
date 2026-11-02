## Context
- 投影层：core/agent_runner/harness/dsh_adapter.py DshEventProjector.ingest :283-317、_project 投影表 :339-482；投影产出事件现无 timestamp。
- 消费面：latency.py:87-97 配对取 entry['timestamp']；在线旁路 runner.py:6433-6443；事后分析 bin/analyze_run_latency.py——三面共用同一事件形态，补时间戳一改全通。
- 告警发射点：runner.py:7032-7045（rounds==0 且 turn_count>0 时无条件触发），现无去重，累计 178 条。

## Goals / Non-Goals
- Goals：dsh 事件可配对；告警收敛；主链与维护链观测一次恢复。
- Non-Goals：不改 dsh 侧事件产生器（打点在 fenixd 读侧投影层）；不改延迟统计口径与停滞阈值；不动 evo-api-stall-signal-grading 的分级聚合。

## Design
- ingest 入口统一记 time.time() 到达时刻并随事件透传投影表，投影产出事件带 timestamp；dump 文件维持原样（不加字段，避免体积膨胀）。
- 告警去重状态落 AgentRunner 实例属性（如 ``self._latency_blind_warned_keys``，
  参照既有单实例去重模式 ``_daily_provider_warned``（runner.py:8693，实例级日去重）），
  键为（harness,事件形态）。生产每进程单 runner 实例拓扑下即进程内收敛；实例级使
  pytest 每用例新建 runner 天然隔离。MUST NOT 用模块级集合实现「进程级」——那会让
  tests/test_run_latency_stats.py:354 失明用例（断言 ≥1 条 WARNING）变成同进程收集
  顺序依赖：任何更早用例触发同键失明告警即把它 primed 掉。
- 文案改为「事件流缺时间戳/无法配对」如实描述。MUST 保留既有测试锁定锚点——
  「失明」标记子串与 extra 键 ``latency_rounds=0`` / ``turn_count`` / ``run_id``
  （tests/test_run_latency_stats.py:354-405 两用例按子串+extra 过滤断言）；改述根因
  （删「请检查 tool_result 事件识别」误归因）时不得丢失这些锚点，否则须同步更新该
  两用例（任务 2.3）。

## Risks / Trade-offs
- 到达时刻≠API 发起时刻，样本含投影排队延迟——对停滞（>60s）量级判断影响可忽略，后续如需精确可由 dsh 侧补事件内时钟。
- dump 与转录双落盘路径均从投影产出取事件，时间戳自然一致，无双源分歧。