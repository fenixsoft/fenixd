# proposal：fix-planned-restart-drain-effectiveness

## Why

2026-09-22 三次 restart_request 规划性重启各 SIGTERM 一个在飞 run（fenixd.log:6689/:6839/:10150），作废对话合计约 81 分钟（run impl-add-code-review-auto-fix-1790034572-a1 在飞 47m48s、impl-fix-relocation-writeback-layer-1790038991-a1 11m40s、evo-1790079811 21m06s/235 轮）。

回源核查推翻了「机制缺失、D3 上线即闭合」的定性：

- 排水机制自 add-interrupt-recovery-preserve（daf4df7d，09-05）即存在，fenixd.log.1 中 09-10~09-19 有多条实战 Drain 日志；三次没排水的真因是生效配置 .fenix/config.yaml:266 admin.shutdown_drain_seconds: 0。
- core/config.py:1130-1162 get_run_drain_max_seconds 尾行 return min(value, max(shutdown, 0.0))——shutdown_drain_seconds=0 时任何排水窗口（含 add-pipeline-throughput-governance D3 新缺省 60s）都被夹紧为 0；.fenix/config.template.yaml:377 模板缺省亦为 0，按模板初始化的项目全部落在失效形态。9b9cdf7f 合入后本部署重启仍会秒杀在飞 run。
- 17:46:36Z 重启「未杀 run」的另一面：在飞 OCR 车道 impl-ocr-add-code-fix-item-level-progress-1790099074 同样损失——run_impl_ocr（core/agent_runner/maintenance_runs.py:1682）以 subprocess.run 跑 ocr、从不登记 runner 在飞注册表（_running_agents），根本不在排水集合，17:51:44 被归档终态、17:56:43 serving worktree 被当无主回收（fenixd.log:12285/:12297）。
- 测试缺口：tests/test_interrupt_recovery_preserve.py:573 的 test_drain_zero_fast_path 把 drain=0 杀在飞定为规格行为；不存在「真实在飞 evo+implementer+OCR 车道跨 restart_request 不被 SIGTERM」的端到端回归。

## What Changes

- **A｜规划性重启豁免快速停机夹紧**：restart_request 在场（planned restart）时排水窗口取 run_drain_max_seconds 原值；shutdown_drain_seconds: 0 的快速停机语义仅保留于非规划性关停。core/config.py 的夹紧规则与 fenixd.py shutdown 路径按规划性/非规划性分叉。
- **B｜车道级进程纳入排水集合**：runner 暴露车道级在飞登记 API，run_impl_ocr 的 ocr 子进程在飞期登记进排水集合（含超窗有序终止路径），重启排水等待其完成或有序收尾，不再被当无主回收。
- **C｜可观测性**：规划性重启但排水被配置禁用（夹紧为 0）时打 WARNING；排水启动时记录排水集合清单（在飞 run + 车道）。
- **D｜端到端回归**：真实在飞 evo 分析 run + implementer run + OCR 车道跨 restart_request，断言排水窗口内不被 SIGTERM、超窗有序终止、checkpoint 旗标广播；修订 test_drain_zero_fast_path 语义（fast path 仅非规划性关停）。

过渡缓解（人工运维步骤，非本 SPEC 交付）：在运行时 .fenix/config.yaml 将 admin.shutdown_drain_seconds 调为正值（如 60），合入前即可恢复排水。

**BREAKING**：无。非规划性关停（kill/crash/手动 stop）行为不变；规划性重启在 shutdown_drain_seconds>0 的部署上行为不变。
