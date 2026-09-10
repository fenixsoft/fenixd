# Design: fix-retry-orphan-active-runs

## Context

2026-09-10 调查定案（见 proposal.md）：活跃 Agent 23 = 2 真活跃 + 21 尸体。尸体全数产生于 runner 原地退避重试换新 `sub_run_id` 弃置旧产物文件；读侧 `classify_run` 不认 `transient_retry` 尾行且无 mtime 信号。09-05 同症状修复（interrupted 停机补写）覆盖不到运行期间换文件形态。

## Goals

- 写侧恢复「终态后置」不变量；读侧把一切无终态陈旧产物挡在活跃计数之外
- 存量 21 具尸体免清扫自动消化

## Decisions

### D1: 补写点 = transient_retry 落盘后紧跟 superseded，而非「弃置时补写」

两通道各在 `transient_retry` 事件 `append_run_line` 之后、`time.sleep(backoff)` 之前追加一条 `superseded` 事件到同一文件：

```python
append_run_line(... / f"{sub_run_id}.jsonl", {"type": "superseded", "spec": ..., "provider": ..., "timestamp": ...})
```

理由：该 while 子循环内此后**必然**不再向该文件写入（continue 换新 `sub_run_id`，runner.py:1922-1923 已核实；break 退出子循环后 attempt 层同样前进新 attempt_run_id），故「紧跟补写」与「确认弃置时补写」等价但无需追踪控制流分支，覆盖 continue 与预算耗尽 break 两条路径，零遗漏。退避 sleep 中 daemon 死亡的场景由既有 interrupted 补写兜底（追加在 superseded 之后，末行仍终态）。

字段：`type/spec/provider/timestamp`，与 `transient_retry` 事件字段同形（少 backoff_seconds/retry_number）。

### D2: 读侧 stale 阈值 = 模块常量 1800s，不做配置项

`_RUN_STALE_SECONDS = 1800`：退避档上限 120s + agent 单 turn（长构建/长测试）余量。live run 每 turn 写事件（实测在飞文件持续更新），30 分钟无写入必非在飞。不做 `.fenix/config.yaml` 配置项——避免触发「新增配置必须带 Dashboard 界面」约束，且该阈值是产物语义而非运维调参。

### D3: stale 判定挂在 get_runs 的 status 组装处，classify_run 保持纯函数

`classify_run(lines)` 是纯行序列函数（多处复用、有单测），不注入 mtime 依赖；`get_runs` 持有 `stat.st_mtime`，在 `classify_run` 结果之上做陈旧改判：

```python
status = classify_run(lines)
if status in ("running", "empty") and (now - stat.st_mtime) > _RUN_STALE_SECONDS:
    status = "stale"
```

`_RUN_TERMINAL_STATUS_MAP` 增 `"superseded": "superseded"`（事件类型 → 状态），stale 不进该映射（非事件类型）。

### D4: 前端 stale 渲染灰色

`detail.tsx` 时间轴 run 节点（`st === 'running' || st === 'empty'` 同区域）：`st === 'stale'` → dotColor 灰（gray），归入非在飞非错误分支。全库仅此一处 run status 消费点（已核实），overview 卡片 active_runs 为纯数字不受影响。

### D5: 存量消化走读侧，不写清扫脚本

21 具尸体 mtime 均 ≥11h ≫ 1800s，读侧兜底自动判 stale。产物文件保持原样（留作考古证据，符合 fenixd 产物不清洗惯例）。

## Risks

- **真活跃长静默误判**：单 turn 超 30 分钟且零事件写入的在飞 run 会被误判 stale。缓解：事件流含 tool_use/结果每 turn 落盘，超 30min 静默的 turn 罕见；即使误判也只影响显示（run 实际完成时 result 落盘改回终态）。
- **`transient_retry` 事件自身语义**：该事件在本 SPEC 后逻辑上「永不成为末行」（写侧紧跟 superseded；历史存量由 stale 兜底），读侧无需为其单列映射。
- **测试 mtime 控制**：stale 场景用 `os.utime` 构造陈旧 mtime，勿 sleep 等真实时间。
