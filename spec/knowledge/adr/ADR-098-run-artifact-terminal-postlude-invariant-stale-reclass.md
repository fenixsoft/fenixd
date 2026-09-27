# ADR-098：run 产物终态后置不变量，读侧 stale 兜底

date: 2026-09-16
status: accepted

## Context

原地退避重试换新 sub_run_id 时弃置旧产物文件且不写终态，读侧行序列分类不认 transient_retry 尾行也无 mtime 信号——弃置产物全部计入活跃计数（实测 23 活跃中 21 具尸体）。停机补写机制只覆盖 daemon 死亡形态，覆盖不到运行期换文件形态。

## Decision

- 写侧不变量「终态后置」：任何弃置产物文件前必补写终态行——superseded 事件紧跟 transient_retry 事件落盘（同一文件 O_APPEND）。该点之后控制流必然不再向该文件写入（continue 换新 sub_run_id / break 前进新 attempt），故「紧跟补写」与「确认弃置时补写」等价但零控制流分支追踪，continue 与预算耗尽 break 两路径全覆盖。
- 退避 sleep 中 daemon 死亡的极端场景由既有 interrupted 补写兜底（追加在 superseded 之后，末行仍终态）。
- 读侧兜底：无终态且 mtime 停更超阈值（模块常量 1800s = 退避档上限 + 单长 turn 余量，不进配置——属产物语义非运维调参）改判 stale，挡在活跃计数之外；改判挂在持有 stat 的读侧组装处，行序列分类函数保持纯函数不注入 mtime 依赖。
- superseded 进终态映射表；transient_retry 在本不变量后逻辑上永不成为末行，读侧不为其单列映射。
- 存量尸体免清扫自动消化（读侧改判），产物文件原样保留作考古证据（产物不清洗惯例），不写清扫脚本。

## Consequences

- 活跃计数失真消失；真活跃长静默（单 turn >30min 且零事件写入）可能误判 stale，但仅影响显示，run 实际完成时 result 落盘改回终态自愈。
- 事件流每 turn 落盘（tool_use/结果）使超 30min 静默 turn 罕见，误判面极小。
