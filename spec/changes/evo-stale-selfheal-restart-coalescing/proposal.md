# 提案：陈旧自愈跨批次合流窗（stale-selfheal-restart-coalescing）

## 背景

框架仓 /root/fenixd 的 code-fix 链以 17-27 分钟一批的节奏连发合入时，dsh daemon 的陈旧自愈（stale_code_selfheal）对每批各走一轮 600 秒空闲确认+重启：2026-10-18 在 109 分钟内 5 连重启，每批加载版本 9-17 分钟即被下一批作废；近 4 个本地日 7/4/6/5 共 22 次自愈重启（每次约 50s drain 窗+6s 停机），同型重启打断在飞 run 已发生 2 次（review-2026-10-15 自省 run 零产物报废、admin-add-dsh-dashboard-bridge-1791972347 被杀）。

前作 2026-10-05-evo-reduce-stale-code-selfheal-noise 把空闲闸从 120s 提到 600s，治理了单日 16 次重启的密集小批次（config.py:2129-2133 注释在案），但 600s 收编窗盖不住分钟级十位的批间隔；防循环冷却（1800s 滑窗 ≥3 次，config.py:2140-2144）对该形态也最多计到 2 次、达不到阈值——10-18 窗五次重启 self_triggered 全为 false，现有 stale_selfheal_loop 告警对其失明。

## 目标

- 同一陈旧悬置周期内，自愈重启最多按基础闸（600s）执行一次；后续陈旧边沿按合流闸（新增配置，缺省 1800s）等待，把「N 批连发」收敛为「末批后一次重启」。
- 陈旧边沿全部消化（磁盘代码不再超进程基线）后合流状态复位，下一次陈旧重新按基础闸。
- 合流等待期每次边沿在日志留痕（第 N 次边沿、当前生效闸值），保留离群初筛证据面。

## 非目标

- 不改 drain 语义与在飞 run 保护（fenixd.py:5622-5697 既有 planned restart 排水不动）。
- 不改关键路径 preflight 重启请求通道（core/code_stale_flag.py request_restart 不经合流闸，保持关键路径即时生效语义）。
- 不改 4h 悬空强转（max_dangling_seconds=14400）兜底与防循环冷却判定语义（冷却仍按实际重启次数计数，合流不是豁免）。
- 不做跨仓 code-fix rollup 信号通道（无现成跨仓信号，成本高可行性存疑）。

## 影响面

- fenixd.py：_maybe_stale_selfheal_tick（:2330）合流判定与状态复位。
- core/config.py：新增 stale_code_selfheal.coalesce_idle_seconds（缺省 1800，项目级可覆盖，沿用 :2239 覆盖模式）。
- tests/test_stale_selfheal_coalescing.py：新增单测。