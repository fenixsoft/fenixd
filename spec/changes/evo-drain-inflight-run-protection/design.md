# Design: drain-inflight-run-protection

## 背景锚点（回源核实）

- 排水窗推导：agents.run_drain_max_seconds 缺省 60（core/config.py:2375/2402），计划内重启被 min(值, SIGKILL 等待−10s) 夹紧（core/config.py:2424-2432，PLANNED_DRAIN_TERMINATE_MARGIN_SECONDS=10 config.py:35）；SIGKILL 等待=admin.shutdown_drain_seconds+120（bin/fenixd_supervisor.py:158）。本部署 .fenix/config.yaml:112 shutdown=0 → 有效 50s（日志 17:47:34.088Z drain window 50.0s 实证）。
- 旗标无读者：broadcast_restart_checkpoint（core/agent_runner/runner.py:10249）排水前置位 1/1，代码注释自证无读取方；drain-preserve（fenixd.py:6635）对 code-review 明文 skip（fenixd.py:6667）。
- 锚消费受闸：writeoff 锚剃余续审在 core/admin_monitor.py:2194-2325，消费点嵌每日周期函数、last_run_date 同日闸在 :2100；AdminMonitor 5 分钟 tick 已在。
- reason 硬编码：core/agent_runner/maintenance_runs.py:2798。

## 方案

1. 排水窗：改 core/config.py 缺省（run_drain 60→300；shutdown_drain_seconds 按夹紧口径联动调整缺省/回退使缺省部署有效窗≥300），并在 :1375-1388 一致性门追加「有效值低于申报值」显式告警分支；不改夹紧语义本身（大窗=旧代码生效更慢的代价由旗标响应对冲）。部署侧覆盖值由运维面同步，框架只保证缺省与告警。
2. 旗标消费：code-review run 波次循环（core/agent_runner/maintenance_runs.py）每波次边界读旗标文件；置位则收尾当前波次退出。旗标路径与 broadcast_restart_checkpoint 单源（runner.py 导出常量/helper，避免两处字面路径漂移）。
3. 锚即时消费：从每日周期函数抽出锚检查为独立方法，挂 AdminMonitor 既有 5 分钟 tick；绕过 :2100 同日闸的条件=「writeoff 锚在册」；保留夜窗顺延与既有单飞/互斥闸（:1741-1766 三通道骨架复用，互斥不重派）。
4. reason 修正：maintenance_runs.py:2798 改写 writeoff_resume（与 core/admin_monitor.py:2260 对账键一致）。

## 风险

- 大排水窗=新代码生效更慢（与归档 2026-11-03-stale-code-governance-activation-window 的处置窗收敛诉求相逆）——由旗标响应把等收尾压到单波次粒度对冲。
- 锚绕闸可能重复续审——单飞闸+锚核销（续审完成后 writeoff-pending 核销，既有语义）兜底。