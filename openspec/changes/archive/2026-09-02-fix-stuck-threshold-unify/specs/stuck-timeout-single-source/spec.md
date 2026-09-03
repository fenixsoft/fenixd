# spec-stuck-timeout-single-source

## ADDED Requirements

### Requirement: stuck 阈值从 run 超时单源派生
stuck 判定阈值 SHALL 由 `agents.run_timeout_seconds` 派生：`effective_threshold = run_timeout_seconds + 600`（600s 为模块常量宽限，非配置项）。`pm_engine.check_blockers` 与 `admin_monitor` 的 stuck 检测 MUST 使用该派生值；`schedule.stuck_threshold_minutes` 与 `admin.stuck_threshold_minutes` 旧键不再作为生效输入。

#### Scenario: 阈值随超时联动
- **WHEN** run_timeout_seconds=9000
- **THEN** 生效 stuck 阈值 = 9600s（160 分钟），STATE 记账静止 100 分钟的健康运行不被 auto-recovery 重置

#### Scenario: 恢复永不早于运行终止
- **WHEN** 某 implementer 运行至 run_timeout_seconds 整点被 runner 强杀
- **THEN** 在此之前任意时刻的 check_blockers 均不触发该 spec 的 stuck 恢复

### Requirement: 旧配置键弃用降级
配置中存在旧键时系统 SHALL 打一次性 WARNING（生命周期内去重）说明值已由超时派生，加载不阻塞、行为不变；`run_timeout_seconds` 缺失或 ≤0 时派生回退 3600+600 并打 WARNING。

#### Scenario: 旧键存在时的行为
- **WHEN** 配置残留 schedule.stuck_threshold_minutes: 240
- **THEN** 启动日志出现一次性弃用 WARNING，check_blockers 实际使用派生值

#### Scenario: 超时缺省防御
- **WHEN** run_timeout_seconds 未配置或为 0
- **THEN** 阈值回退 4200s 且伴随 WARNING

### Requirement: 超时上限联动护栏
timeout_supervision 的 `absolute_max_seconds`（若配置）MUST ≥ run_timeout_seconds + 单次续期上限，否则启动/热更新时打 ERROR 并按 run_timeout_seconds + 7200 兜底生效；config 默认值对齐为 14400。防止手工配置再次与超时参数脱钩。

#### Scenario: 上限低于超时被纠正
- **WHEN** 配置 absolute_max_seconds: 7200 而 run_timeout_seconds: 9000
- **THEN** 启动出现 ERROR 日志，实际生效 16200（9000+7200），supervision 激活后不会先于墙钟终止运行
