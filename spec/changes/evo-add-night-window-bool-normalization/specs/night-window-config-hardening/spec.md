## ADDED Requirements

### Requirement: 窗值布尔同义化
night_quiet_window 解析单源 MUST 把布尔 false 与字符串 off 同义处理（守卫显式停用），布尔 true 及其他非法形态 MUST 显式拒判并告警，不得静默按无窗处理。

#### Scenario: 布尔 false 等价 off
- **WHEN** 配置载入 night_quiet_window: false
- **THEN** 三消费点一致得到「守卫显式停用」语义，不再走 split 解析出 None 的静默路径

### Requirement: 载入期 lint
配置载入时 MUST 对 night_quiet_window 非法值（含布尔）一次性 WARNING，指明合法形态。

#### Scenario: 载入即告警
- **WHEN** daemon 载入含非法窗值的配置
- **THEN** 启动早期出一次性 WARNING（进程级去重），不晚于首个守卫消费点

### Requirement: 消费点告警对等
审查跨窗顺延与 admin 唤起避让在窗值非法/缺失时 MUST 出与 code-fix 车道同款的告警留痕，不得静默 fail-open。

#### Scenario: 审查车道告警对等
- **WHEN** 审查派发遇到窗值解析失败
- **THEN** 记与 code-fix 车道同文案的 WARNING（进程级去重）

### Requirement: 停用态每日提醒
守卫停用（显式 off 或布尔）期间 MUST 每日至多一条聚合提醒，防长期悬置无人处置。

#### Scenario: 悬置 10 天可感知
- **WHEN** 守卫停用跨自然日
- **THEN** 每日至多一条提醒持续可见，不逐 run 刷屏