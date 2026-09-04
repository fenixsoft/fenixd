# Design: fix-stuck-threshold-unify

## Context

两个旋钮在今天以最坏方式相遇：用户按实际需要把 `run_timeout_seconds` 提到 9000s，而 `stuck_threshold_minutes` 仍是 60——auto-recovery 的设计前提（阈值 < 运行寿命时只可能命中真卡死）被打破，恢复动作成为对健康运行的定时误杀。反方向的漂移（阈值 > 超时）同样有害：真死锁的发现被无限推迟。唯一安全的配置关系是"阈值恒大于超时"，而这只能靠派生保证。同日 timeout_supervision 的 absolute_max_seconds: 7200 与 9000s 超时脱钩是同一类病的第二个实例。

## Goals / Non-Goals

**Goals:**
- stuck 判定阈值单源派生自 `agents.run_timeout_seconds`，配置面只保留一个旋钮
- 旧配置键静默降级 + 一次性 WARNING
- 恢复语义校正：绝不早于 runner 自身超时杀死运行（哪怕 STATE 记账静止）
- absolute_max_seconds 与超时联动校验，防再次手工脱钩

**Non-Goals:**
- 不改 auto-recovery 的探测/重置实现本身（活进程探测属 improve-run-lifecycle-governance D4）
- 不动 daily_run_limit、merge_breaker 等其他阈值

## Decisions

- **D1 派生公式 = run_timeout_seconds + 600s 固定宽限。** 宽限是模块常量（非配置），作用是让 runner 的超时终止与恢复判定之间留出确定性时序余量，避免 150min 整点上的照片终点竞态（两个看门狗同秒触发时行为不可预测）。用户"两值一致"的意图通过"唯一旋钮 + 恒定关系"实现，而非字面相等。备选"严格相等"被否：竞态窗口会导致部分运行被恢复抢杀、上下文丢失。
- **D2 派生助手集中一处。** `config.py` 新增 `effective_stuck_threshold_seconds(config) -> float`，pm_engine.check_blockers 与 admin_monitor（经 get_admin_config 回退链）都改调它；旧键读取逻辑删除。上限保护：admin.stuck_threshold_minutes 显式配置在 D1 语义下失去意义，直接忽略并告警。
- **D3 弃用告警节流。** WARNING 每 daemon 生命周期打一次（模块级 flag），避免 30 分钟扫描刷屏。
- **D4 超时为 0/缺省的防御。** run_timeout_seconds 缺失或 ≤0 时回退 3600+600 并打 WARNING（防止有人把超时关掉导致恢复永不触发）。
- **D5 absolute_max 联动。** 校验点在 supervision 配置读取处：absolute_max < run_timeout + extension_seconds*max_extensions 时 ERROR + 按 run_timeout + 7200 兜底；未启用 supervision（enabled=false）时不校验。

## Risks / Trade-offs

- [真死锁发现变慢（阈值随超时水涨船高）] → 本就是正确取舍：活进程盲态的根治在 improve-run-lifecycle-governance D4 的存活探测，届时恢复只需看进程不需看钟
- [用户依赖旧键做更激进卡死检测] → D2 告警指明新语义；极端需求走临时调低 run_timeout 的正规旋钮

## Migration Plan

配置向后兼容（旧键被忽略）。随 daemon 重启生效；回滚 revert。config.yaml 中旧行删除 + 注释。

## Open Questions

- 无
