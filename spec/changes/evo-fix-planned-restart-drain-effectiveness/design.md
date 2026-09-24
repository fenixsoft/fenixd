# design：fix-planned-restart-drain-effectiveness

## Context

2026-09-22 三次 restart_request 规划性重启杀在飞 run（fenixd.log:6689/:6839/:10150），作废约 81 分钟。核查定位的真实机理链：

- 排水机制本体早已存在：fenixd.py:3479-3530 shutdown 路径在 planned_restart 且 drain_seconds>0 时 broadcast_restart_checkpoint + drain_wait；该链路 09-10~09-19 实战排水过（fenixd.log.1 多条 Drain 日志）。
- 失效点在配置联动：core/config.py:1130-1162 get_run_drain_max_seconds 尾行 min(value, max(shutdown, 0.0))，本部署 .fenix/config.yaml:266 admin.shutdown_drain_seconds: 0 把窗口恒夹为 0；模板缺省同值。add-pipeline-throughput-governance（9b9cdf7f）把缺省提到 60s，但夹紧规则使其在本部署完全无效。
- 排水集合缺口：running_run_ids（core/agent_runner/runner.py:4845-4857）是进程内 Popen 注册表；evo/implementer 在册（runner.py:3704），而 run_impl_ocr（core/agent_runner/maintenance_runs.py:1682，subprocess.run 跑 bin/ocr_review.py 经 os.execvp 改名）不在册——17:46 重启即实例（ocr 车道丢、serving worktree 被回收，fenixd.log:12285/:12297）。
- 测试面：tests/test_interrupt_recovery_preserve.py:528-580（含 test_drain_zero_fast_path 钉死 drain=0 杀在飞）、tests/test_pipeline_throughput_governance.py:224-332（60s 缺省/夹紧/广播）。

## Goals / Non-Goals

**Goals**

1. 规划性重启的排水窗口恢复有效（豁免 shutdown=0 夹紧），快速停机语义仅限非规划性关停。
2. OCR 车道等非 agent_runner 派生进程纳入排水集合，重启不再丢弃其工作与载体。
3. 端到端回归钉住三类在飞工作跨重启存活。

**Non-Goals**

1. 不改 supervisor 侧协议（bin/fenixd_supervisor.py:412/:443 的检测与 unlink 时序保持）。
2. 不引入 /proc cwd/cmdline 扫描——对 Popen 句柄在册的进程是伪问题（execvp 同 PID），真盲区用登记制解决。
3. 不动运行时 .fenix/config.yaml（运维过渡：人工把 shutdown_drain_seconds 调正值即可先行缓解，写入 docs/help）。

## 设计决策

- **D1｜夹紧豁免按 planned_restart 分叉而非改缺省值**：在 get_run_drain_max_seconds 增加 planned 参数（或在 fenixd.py shutdown 处先行判定），planned restart 取原值、非规划性关停保持 min 夹紧——fast-shutdown 的原始意图（避免无人值守时在飞必等满窗口）不受损，D3 的意图（规划性重启排水）恢复。选在配置读取层分叉保证单源。
- **D2｜车道登记制而非进程表扫描**：与 orphaned_state 探针的 pgrep 盲区不同源——排水集合天然是「我们派生的进程」，Popen 句柄足以跟踪 execvp 改名；只要把 run_impl_ocr 的子进程注册进 runner 登记表即可。登记 API 泛化为 register/unregister，后续其它 maintenance 车道可复用。
- **D3｜超窗有序终止**：ocr 子进程超窗时先 SIGTERM 再等待短宽限后 SIGKILL（对齐 liveness.py wait_for_running_agents 语义），并写车道终态（unavailable/interrupted），使重启后归档与无主回收逻辑不再误判。
- **D4｜测试语义迁移**：test_drain_zero_fast_path 修订为 fast path 仅非规划性关停；新增端到端回归以假 evo/impl run + 假 ocr 车道（快速可终止的替身进程）驱动真实 shutdown 路径，避免测试挂真实 LLM。

## 风险

- 规划性重启最长多等 run_drain_max_seconds（缺省 60s）：重启时延可接受（陈旧自愈仅在连续空闲 120s 后触发，排水窗口通常为空转）。
- 登记制依赖车道代码自觉注册：漏注册即退回现状盲区——端到端回归对 ocr 车道做钉住，新增车道须在验收单中带登记检查。
