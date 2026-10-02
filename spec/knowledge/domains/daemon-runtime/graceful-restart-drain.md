<!-- knowledge: capability=graceful-restart-drain rev=1 sources=spec/archive/2026-09-27-add-pipeline-throughput-governance -->

# 优雅重启排水窗口

daemon restart 流程等待在飞 run 排水的时长上限与 checkpoint 广播契约，消解「重启白等半小时」的窗口错配。

## 现行规则

- restart 排水等待上限由 `agents.run_drain_max_seconds` 单源专管（代码缺省 60s），超窗后按既有强杀路径收场；常规停机仍走 `admin.shutdown_drain_seconds` 语义不变。
- 排水窗口生效值必须 ≤ `admin.shutdown_drain_seconds`（缺省 1800）：supervisor 的 SIGKILL 等待 = `shutdown_drain_seconds + 120s` 余量，满足该不等式即保证 supervisor 不会先于 daemon 的排水窗口强杀；非法值在配置加载期拒绝，不把缺省值变成地雷。
- 显式配置优先于代码缺省，可人工调大给长排水留裕量；缺省组合下「重启到新 daemon 就绪」无 1800s 级空等，被强杀的 run 走既有恢复路径（保留分支续做）。
- restart 触发、停止新派发后，daemon 向每个在飞 run 广播一次 checkpoint 信号（写 run 控制文件）：有响应语义的 run 按既有语义尽快落盘进度声明收尾，无响应语义的 run best-effort 忽略。
- checkpoint 广播不阻塞排水等待（写后即返回），不产生新的失败终态或打回；信号未读即被强杀的 run 处理与未广播时完全一致，无新增告警、无状态损坏。

## 溯源

- 2026-09-27 add-pipeline-throughput-governance（spec/archive/2026-09-27-add-pipeline-throughput-governance） — 新增 restart 专用排水窗口配置并与 supervisor SIGKILL 宽限协调；restart 触发时向在飞 run 广播 checkpoint 信号
