# ADR-374：计划内排水窗缺省 300 秒与 SIGKILL 等待回退的路径限定

date: 2026-11-17
status: accepted

## Context

计划内重启的排水窗沿夹紧链推导：`agents.run_drain_max_seconds` 缺省 60，planned 分支按 min(值, supervisor SIGKILL 等待 − 10s) 夹紧；本部署 `admin.shutdown_drain_seconds=0`（快速停机申报）使 SIGKILL 等待回退 60s、有效排水窗仅 50s。悬空超时强制重启的触发边沿是主树 core/ 变更、必然撞上在飞 run，50 秒窗内 SIGKILL 掉了运行 106 分钟的全仓审查 run，剩余覆盖 22 小时后才被续审接管——同类事故已四次成灾。夹紧链上单提任何一处缺省都会被静默夹回，须逐点核对链上全部消费点后才能安全改值。

## Decision

1. `agents.run_drain_max_seconds` 缺省提至 300；配置一致性校验按同口径推导有效排水窗，低于申报值时输出含申报值与推导值的显式 WARNING（不阻断启动）——静默夹回必须显式留痕。
2. SIGKILL 等待回退值的调整只作用于 planned restart 收口路径：shutdown≤0 回退 310（目标窗 300 + 终止余量 10），daemon 与 supervisor 双侧同字面常量建模（supervisor 不能反向 import core，以常量 + 注释互指防漂移）。
3. stop 停机、supervisor 自身停机、启动收编三路径维持 60s 回退不变：shutdown=0 是部署对快速停机的显式申报，回退值全局提大会破坏该语义。
4. 不改夹紧语义本身：大窗 = 旧代码生效更慢的代价，由在飞车道旗标批边界响应对冲（ADR-375），不以缩短窗为解法。

## Consequences

- 缺省部署与 shutdown=0 部署的有效排水窗均 ≥ 300s；有效值低于申报值时启动日志必有告警留痕，部署侧覆盖值仍由运维面负责同调。
- planned 与非规划停机的 SIGKILL 等待语义永久分叉：后续触碰 SIGKILL 等待的 SPEC 必须按路径分叉对账，禁止全局改回退值。
- 大排水窗延长了强制重启后新代码的生效延迟，是接受的成本；批边界自检属尽力而为，不承诺全保。
