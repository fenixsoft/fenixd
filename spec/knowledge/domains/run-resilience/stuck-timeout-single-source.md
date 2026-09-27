<!-- knowledge: capability=stuck-timeout-single-source rev=1 sources=spec/archive/2026-09-02-fix-stuck-threshold-unify -->

# stuck 阈值单源

stuck（记账静止）判定阈值自 run 超时单源派生：阈值恒大于 run 墙钟上限，恢复判定只可能命中「运行已死但记账残留」的孤儿，健康运行不被误判卡死重置。

## 现行规则

- stuck 判定阈值由 `agents.run_timeout_seconds` 派生：`effective_threshold = run_timeout_seconds + 600`（600s 为模块常量宽限，非配置项）；`pm_engine.check_blockers` 与 `admin_monitor` 的 stuck 检测复用同一派生助手、使用同一派生值。
- 旧配置键 `schedule.stuck_threshold_minutes` 与 `admin.stuck_threshold_minutes` 不作为生效输入；配置残留旧键时打一次性 WARNING（生命周期内去重）说明值已由超时派生，加载不阻塞、行为不变。
- `run_timeout_seconds` 缺失或 ≤0 时派生回退 3600+600=4200s，并伴随 WARNING。
- run 活性续期后 stuck 检测起始时间随之顺延：恢复永不早于运行终止，run 运行至超时整点被强杀之前的任意时刻，check_blockers 均不触发该 spec 的 stuck 恢复。
- supervision `absolute_max_seconds` 护栏封顶：生效值不得低于 run 超时加续期预算；下限派生公式与不一致时的自动对齐/阻断处置由 [timeout-supervision](timeout-supervision.md) 能力页承载。

## 溯源

- 史前复原 — 迁移期基线：stuck 阈值单源派生，旧配置键弃用，absolute_max 护栏封顶，检测基准随续期顺延
- 2026-09-02 fix-stuck-threshold-unify — 确立阈值自 run_timeout_seconds+600 单源派生、旧键弃用降级与超时缺省防御；absolute_max 联动护栏同场确立，其下限派生与对齐处置机制后由 timeout-supervision 能力页承接
