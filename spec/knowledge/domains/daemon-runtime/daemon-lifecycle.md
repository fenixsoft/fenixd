# 计划内排水窗与在飞 run 保护

<!-- knowledge: capability=daemon-lifecycle rev=1
     sources=spec/changes/evo-drain-inflight-run-protection -->

计划内重启悬停期间的在飞 run 保护闭环：排水窗按 supervisor SIGKILL 等待推导且不被静默夹短；无 Python 层波次循环的维护车道（code-review）在批边界自检重启旗标、单批收尾退出并落 writeoff 锚；锚由独立周期扫描即时续审，接管剩余覆盖。

## 规则

- 计划内重启排水窗有效值 = min(`agents.run_drain_max_seconds` 申报值，supervisor SIGKILL 等待 − 10s 终止余量)；代码缺省 300 秒，缺省部署（含 `admin.shutdown_drain_seconds=0` 快速停机申报部署）的有效排水窗 ≥ 300 秒。
- SIGKILL 等待回退分叉只作用于 planned restart 收口路径：shutdown>0 时两路径同值（= shutdown + 120s 余量）；shutdown≤0 时 planned restart 回退 310 秒（目标窗 300 + 终止余量 10），stop 停机 / supervisor 自身停机 / 启动收编路径维持 60 秒回退不变——shutdown=0 是部署对快速停机的显式申报，回退值全局提大会破坏该语义。
- 配置一致性校验按同口径推导有效排水窗，低于 `agents.run_drain_max_seconds` 申报值时输出含申报值与推导值的显式 WARNING 告警（不阻断启动），杜绝部署侧覆盖被静默夹回。
- 在飞维护车道响应重启 checkpoint 旗标：code-review run 无 Python 层波次循环（单次 `_run_agent` 派发、agent 进程内自切批直写分片），旗标响应以 prompt 注入批边界自检实现——每批分片直写后读取 `broadcast_restart_checkpoint` 落位的旗标文件（路径与读取经单源常量/helper），置位则不再开启新批，完成当前批收尾（分片落盘 + 终态抢救文件写毕）即退出。自检属软约束：agent 不读旗标跑满清单时覆盖完整、锁定分支不可达，无副作用。
- 旗标响应退出路径 MUST 落 writeoff-pending 锚（success 收场亦落锚），使剩余清单进入锚即时续审链路；不以 success 静默收场遗留未接管覆盖。
- writeoff 锚即时续审：锚检查是独立周期扫描（挂 AdminMonitor 巡检 tick，`admin.interval_minutes` 缺省 5 分钟），命中未核销锚即按「本轮收集清单 − 锚 run 链累计已覆盖」剃余组装续审 manifest 派发（`redispatch_of` 指回锚 run id）；扫描不读 run_at / 同日防重，锚缺席零动作，常规派发仍由每日检查点承担（锚文件契约与核销解锁守卫详见 [审查发现台账](../code-review-lane/code-review-items.md)）。
- 绕过闸判据：last_run_date 同日防重闸语义是「当日已完成一轮」，锚在场恰证明当日未完成——周期扫描绕过同日闸与 run_at 时点门，派发前照写同日防重（续审轮即当日一轮）；夜窗顺延与单飞闸保留（预计在飞区间命中夜间静默窗本轮不派、窗末后巡检自然触发；单飞判定与置位与每日检查点同一把锁同一标志、锁内原子完成，互斥不重派）。
- 续审 run 自身再失败（429/停滞/零产物）时锚保持或由抢救重写，下一 tick 单飞闸空出后扫描自然重入，周期节拍即天然重试环，不设独立重试预算。
- 锚驱动续审 run 的档案注记 reason 恒记 `writeoff_resume`（与续审检索对账键一致），不复用 429 ratelimit 字面；ratelimit 车道自身的登记路径不受影响。

## 代码锚点

- 主实现：`core/config.py`（`get_run_drain_max_seconds` / `_planned_restart_sigkill_wait` 排水窗推导与 planned 回退、一致性校验段夹短告警）
- 旗标单源：`core/agent_runner/run_files.py`（`RESTART_CHECKPOINT_FLAG_SUFFIX` / `restart_checkpoint_flag_path` / `read_restart_checkpoint_flag`，经 runner re-export）；广播侧 `core/agent_runner/runner.py`（`broadcast_restart_checkpoint`）
- prompt 注入：`core/agent_runner/prompt_builder.py`（重启排水批边界自检段）；旗标响应收尾落锚与 reason 注记：`core/agent_runner/maintenance_runs.py`
- 锚周期扫描：`core/admin_monitor.py`（`_run_writeoff_anchor_resume_checkpoint`，挂巡检 tick）
- supervisor 同源建模：`bin/fenixd_supervisor.py`（`_sigkill_wait_seconds`；supervisor 不能反向 import core，双侧同字面常量 + 注释互指防漂移）
- 守卫测试：`tests/test_drain_inflight_run_protection.py`

## 溯源

- 2026-11-17 evo-drain-inflight-run-protection（spec/changes/evo-drain-inflight-run-protection） — 新建本能力页：排水窗缺省 60→300 与有效窗夹短显式告警、planned restart 专用 SIGKILL 回退 310（stop 停机语义不变）、code-review 批边界旗标自检响应（退出必落锚）、writeoff 锚周期扫描即时续审（绕同日闸、留夜窗/单飞闸）、续审注记 reason 由硬编码 429 ratelimit 改 writeoff_resume
