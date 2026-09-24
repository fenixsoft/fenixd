# spec-planned-restart-drain-effectiveness

## ADDED Requirements

### Requirement: 规划性重启不受快速停机夹紧

restart_request 在场（规划性重启）时，排水窗口 MUST 取 agents.run_drain_max_seconds 原值与 supervisor SIGKILL 等待减终止收口安全余量二者的较小值（豁免 shutdown=0 夹紧，不豁免 supervisor 协调上界，见 bin/fenixd_supervisor.py `_sigkill_wait_seconds`：shutdown≤0 时 SIGKILL 等待回退 60s）；admin.shutdown_drain_seconds: 0 的快速停机联动（core/config.py get_run_drain_max_seconds 的 min 夹紧）MUST 仅作用于非规划性关停。shutdown_drain_seconds>0 的部署行为 MUST 逐字节不变。

#### Scenario: 规划性重启排水生效

- **WHEN** .fenix/restart_request 在场、admin.shutdown_drain_seconds 为 0、agents.run_drain_max_seconds 为 60、存在在飞 run
- **THEN** shutdown 路径先 drain_wait 一个正值窗口（≤ run_drain_max_seconds 原值 60 秒，且低于 supervisor SIGKILL 等待 60 秒减收口余量）而非立即 SIGTERM；窗口内自然完成的 run MUST NOT 被终止

#### Scenario: 非规划性关停快速停机语义保留

- **WHEN** 无 restart_request 且 shutdown_drain_seconds 为 0、存在在飞 run
- **THEN** 行为与现状一致（快速停机，不等待排水）

#### Scenario: 夹紧禁用可观测

- **WHEN** 规划性重启发生且排水窗口被配置夹紧为 0（本 SPEC 合入前形态）或排水集合为空
- **THEN** 日志含 WARNING/INFO 说明排水窗口取值与排水集合清单（在飞 run 与车道名）

### Requirement: 车道级进程纳入排水集合

runner MUST 提供车道级在飞登记/注销 API；run_impl_ocr 的 ocr 子进程在飞期 MUST 登记（经 os.execvp 改名不影响——按 Popen 句柄跟踪）；规划性重启排水 MUST 等待其完成，超窗时有序终止并落终态，MUST NOT 令其产物/serving worktree 被当无主回收。未经登记的车道进程行为不变。

#### Scenario: OCR 车道跨重启不被丢弃

- **WHEN** ocr 车道在飞（run_impl_ocr 的 subprocess 运行中）时发生规划性重启
- **THEN** 排水等待其完成或超窗有序终止；重启后该车道 run 有终态记录，serving worktree MUST NOT 被无主回收逻辑清除

#### Scenario: drain=0 fast path 语义收窄

- **WHEN** test_drain_zero_fast_path 所钉的 fast path 场景重放
- **THEN** fast path 仅适用于非规划性关停；规划性重启不受 shutdown=0 夹紧（既有用例同步修订）

### Requirement: 端到端回归钉住

新增回归：构造真实在飞的 evo 分析 run、implementer run 与 OCR 车道，touch .fenix/restart_request 触发规划性重启，断言 agents.run_drain_max_seconds 窗口内三者均不被 SIGTERM、自然完成或超窗有序终止、broadcast_restart_checkpoint 旗标对在册 run 广播。

#### Scenario: 三类在飞工作跨重启存活

- **WHEN** 三类在飞工作在场时触发 restart_request 规划性重启
- **THEN** 排水窗口内无任何一方被 SIGTERM；窗口耗尽后未完成者被有序终止并留终态
