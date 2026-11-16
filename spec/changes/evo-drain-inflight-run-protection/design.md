# Design: drain-inflight-run-protection

## 背景锚点（回源核实，2026-11-16 spec-review 实测行号）

- 排水窗推导：agents.run_drain_max_seconds 缺省 60（core/config.py:2484 回退分支与 docstring :2424），规划性重启 planned=True 分支被 min(值, SIGKILL 等待−10s) 夹紧（core/config.py:2488-2493，PLANNED_DRAIN_TERMINATE_MARGIN_SECONDS=10 config.py:48）。SIGKILL 等待建模：shutdown>0 时 = shutdown+120（DRAIN_MARGIN_SECONDS，bin/fenixd_supervisor.py:163 与 core/config.py:2489 注释同源）；**shutdown≤0 时双侧回退缺省 60s**（bin/fenixd_supervisor.py:160 DEFAULT_SIGKILL_WAIT_SECONDS 与 core/config.py:2490）。本部署 .fenix/config.yaml:112 shutdown=0 → sigkill_wait=60 → cap=60−10=50（fenixd.log:6048「drain window 50.0s」/6049「Drain finished after 50s」实证）。
- 旗标无读者：broadcast_restart_checkpoint（core/agent_runner/runner.py:10326，由 fenixd.py:7247 排水路径调用，日志「checkpoint broadcast: 1/1」实证置位）；全库 grep 仅定义与调用两处，零读取方。drain-preserve（fenixd.py:7042-7072）按 worktree→spec 保全集提交 WIP checkpoint，code-review 车道无 worktree 结构性不在保全集（等价 skip，分片产物在 .fenix/code-review/ 下不受 WIP checkpoint 保护）。
- 锚消费受闸：writeoff 锚剃余续审在 core/admin_monitor.py:2323-2400，消费点嵌每日周期审查函数；last_run_date 同日闸在 :2227-2229（先于锚检查执行，同轮已写日期则锚检查不可达）；单飞标志与 except 复位口径在 :2255-2262。AdminMonitor 巡检周期 admin.interval_minutes 缺省 5 分钟（:1941）。
- reason 硬编码：core/agent_runner/maintenance_runs.py:2953——redispatch_of 在场即向自身 jsonl 标注 `"reason": "429 ratelimit"`，writeoff 续审复用该路径被误标；续审检索对账键 reason=writeoff_resume 在 core/admin_monitor.py:2378-2400。runner.py:5230/5253 的 429 字面是 ratelimit 车道自身登记，不在本 SPEC 改动面。

## 方案

1. 排水窗：改 core/config.py 缺省（run_drain 60→300；shutdown≤0 的 SIGKILL 等待回退值按夹紧口径联动调整，使缺省部署与 shutdown=0 部署的有效排水窗≥300），并在配置一致性校验段（core/config.py:1378-1404 一带）追加「有效值低于申报值」显式告警分支（不阻断启动）。**边界约定：SIGKILL 等待回退值的调整仅作用于 planned restart 收口路径（supervisor restart 流程与 config.py:2488-2493 planned 分支双侧同源），非规划性停机（stop flag）的 SIGKILL 等待语义不变**——shutdown=0 是部署对快速停机的显式申报，回退值全局提大会破坏该语义。不改夹紧语义本身（大窗=旧代码生效更慢的代价由旗标响应对冲）。部署侧覆盖值由运维面同步，框架只保证缺省与告警。
2. 旗标消费：**code-review run 无 Python 层波次循环**——run_code_review（core/agent_runner/maintenance_runs.py:2858）是单次 _run_agent 派发，agent 进程内自切批直写 batch_N.json 分片（maintenance_runs.py:3077 注释自证）。旗标响应以 prompt 注入实现：_build_prompt 注入「每批分片直写后检查旗标文件；置位则不再开启新批、完成已审分片与终态抢救后退出」的批边界自检指令。旗标路径与 broadcast_restart_checkpoint 单源（runner.py 导出常量/helper，避免广播与读取两处字面路径漂移）。**锚衔接约定：旗标响应退出路径 MUST 使剩余清单进入 writeoff 锚链路**（复用 error 收场抢救落账或显式写 writeoff-pending 锚）——writeoff 锚由收场抢救落账写入（core/admin_monitor.py:2744-2757 注释）、覆盖守卫仅 redispatch_of 非空时判定（admin_monitor.py:2326-2331 注释），旗标响应 run（redispatch_of=None）若以 success 收场不落锚，剩余清单将退回次日调度节拍，与「锚即时续审」目标脱节。
3. 锚即时消费：从每日周期审查函数抽出锚检查为独立方法，挂 AdminMonitor 既有巡检 tick（admin.interval_minutes 缺省 5 分钟）；绕过 :2227-2229 同日闸的条件=「writeoff 锚在册」；保留夜窗顺延与既有单飞/except 复位闸（:2255-2262 骨架复用，互斥不重派）。
4. reason 修正：maintenance_runs.py:2953 改写 writeoff_resume（与 core/admin_monitor.py:2378-2400 对账键一致）；redispatch_of 在场但真实原因为 429 的路径（runner.py:5230/5253 车道自身登记）不动。

## 风险

- 大排水窗=新代码生效更慢（与归档 2026-11-03-stale-code-governance-activation-window 的处置窗收敛诉求相逆）——由旗标响应把等收尾压到单批粒度对冲；批粒度自检为尽力而为（agent 不读旗标或单批超窗时仍可能被 SIGTERM），不承诺全保。
- 锚绕闸可能重复续审——单飞闸+锚核销（续审完成后 writeoff-pending 核销，既有语义）兜底。
- prompt 注入自检依赖 agent 遵从——批边界自检属软约束，旗标响应不达时退化为既有行为（排水窗等待/SIGTERM+抢救落账），无新增风险面。
