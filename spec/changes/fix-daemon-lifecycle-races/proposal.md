# Proposal: fix-daemon-lifecycle-races

## Why

2026-09-06 自省与调查确认 daemon 生命周期存在三组竞态，已造成实际损失且敞口仍在：
（1）supervisor 旧进程 60s SIGKILL 截断 daemon 新排水逻辑（1800s 窗口），在途 run 永久无终态、claude 孤儿进程与新 daemon 并行重验同一 spec，当日 5 run 中 2 个被 SIGKILL、verify 全量重跑 3 次；（2）`pushed→pushed` 幂等自迁移报 ERROR 假告警 40 条（每次 done→pushed 双路径并发必触发），稀释 ERROR 信噪比并掩盖真实非法迁移（09-06T02:13 `implemented→verified` 竞态导致整轮 verifier 重复派发）。

## What Changes

- **排水路径终态保证**：daemon 收 SIGTERM 进入排水时，对在途 run 先落「排水开始标记」（draining 标记），daemon 被强杀后由新 daemon 启动扫描发现「标记在场 + run 无终态」补写 interrupted 终态；排水的自然收工路径不受影响
- **排水窗口一致性自检**：daemon 启动时校验 `admin.shutdown_drain_seconds` 与 supervisor 侧 SIGKILL 等待窗口（drain+120s）配置可达性，不一致（supervisor 代码/配置陈旧）打 WARNING 告警，提示重启 supervisor
- **重验计数持久化**：重启恢复路径（testing→implemented 重验）递增持久化计数器（参照 `_impl_run_budget_used` 的 STATE 字段方式），达到阈值冻结 blocked 等 admin 裁决，堵死「毒 spec 借反复重启无限重验」敞口
- **状态机幂等自迁移**：`transition()` 对 `old==new` 判为幂等自迁移，降级 INFO 直接返回 True（不进 VALID_TRANSITIONS 拒绝分支），ERROR 保留给真实非法迁移
- **done→pushed 双路径去重**：根治 `_on_spec_done` 同步直调（engine.py:363）与 event_bus spec_done 事件的双路径并发——per-spec 互斥 + `_auto_approve` 的 status 检查与 `transition(pushed)` 闭入同一临界区（check-then-act 原子化）
- **stale-verdict 竞态收编**：`stale/foreign verifier result replayed` 防护把 spec 拨回 implemented 前，登记/取消在飞 verify run；在飞旧 verify run 完成时若 spec 已被重置，结果静默丢弃（DEBUG）而非走失败迁移 + 重复派发

## Capabilities

### New Capabilities

- `daemon-drain-integrity`: 排水路径的 run 终态完整性——SIGTERM 排水标记、强杀后终态补写、drain 窗口与 supervisor 宽限一致性自检
- `verify-recovery-budget`: 重启恢复重验的持久化预算计数与超限冻结
- `state-transition-idempotency`: 状态机对幂等自迁移（old==new）的降级处理
- `done-push-dedup`: done→pushed 自动审批链路的单飞（single-flight）去重
- `stale-verdict-race-guard`: stale-result 重置与在飞 verify run 完成的竞态收编

### Modified Capabilities

（无——`spec/specs/` 当前无活跃能力声明；既有排水/terminate 行为由归档 change `fix-graceful-shutdown-agents` 与活跃 change `add-interrupt-recovery-preserve` 的实现承载，本 SPEC 为其行为修复补全）

## Impact

- **代码**：`fenixd.py`（shutdown 排水序列 + 启动自检）、`core/agent_runner/runner.py`（draining 标记写入、run 完成路径收编判定）、`core/agent_runner/liveness.py`（终态补写扫描）、`core/state_machine.py`（transition 幂等分支、恢复计数器字段）、`core/pm_engine/engine.py`（_on_spec_done 单飞、_auto_approve 原子化）、`core/pm_engine/verification.py`（stale-result 拨回与在飞 run 收编）、`bin/fenixd_supervisor.py`（一致性自检配合项，如守恒不变）
- **状态契约**：STATE.md 新增内部字段（`_verify_redo_count` 命名待 design 定，`_` 前缀内部字段解析已支持，见 `state_machine.py:140-142`）
- **运维**：S1（重启 supervisor 进程 PID 1821119）已于立项前执行，代码层自检为长期防线
- **风险面**：shutdown 路径与状态机并发语义改动，回归需覆盖排水超时/强杀/自然收工三态与并发双触发场景
