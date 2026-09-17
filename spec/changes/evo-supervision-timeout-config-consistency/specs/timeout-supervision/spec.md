# Spec Delta: timeout-supervision

## NEW Requirements

### Requirement: 统一 supervision absolute_max 下限派生口径

supervision `absolute_max_seconds` 的生效下限 MUST 由单一派生函数给出：`下限 = 生效 run_timeout_seconds + 最大续期次数 × 单次续期秒数`（当前配置 = 15000 + 2×1800 = 18600s）。该派生 MUST 同时被 config 校验层与 liveness 兜底层调用（禁止两处各自手写不同口径——现状 config.py 与 liveness.py 分别为 18600/22200）。

#### Scenario: 两处口径一致

- **WHEN** supervision 激活路径与 config 校验路径同时读取 absolute_max 下限
- **THEN** 两者返回同一派生值（断言相等），无口径漂移

### Requirement: 启动/热更新一致性校验不一致即阻断

配置加载（启动或热更新）时，MUST 校验 `absolute_max_seconds ≥ 生效超时 + 续期总额`；不一致时 MUST：
- 输出明确 ERROR（含两侧配置值、下限、修正建议：抬升 absolute_max 或下调 run_timeout）；
- 可选自动对齐（将 absolute_max 抬升至下限并持久化）；
- 在启用 supervision 的部署中 MUST fail-fast 阻断（拒绝继续加载/启动），MUST NOT 仅告警后静默兜底生效。

**背景（实测依据）**：fenixd.log 5 条 ERROR（09-15T15:49:54Z/16:19:54Z、09-16T08:32:50Z/09:02:50Z/09:32:51Z，行 13181/13218/14985/15018/15051），config.yaml:22=15000/:27=14400 未对齐；config.py:1241-1269 现状为 ERROR+返回兜底不阻断。

#### Scenario: 不一致时启动阻断

- **WHEN** 配置加载发现 absolute_max(14400) < 下限(18600)
- **THEN** 启动/加载返回失败并输出 ERROR 与修正建议（fail-fast），不静默按兜底继续

#### Scenario: 一致时正常启动

- **WHEN** absolute_max ≥ 下限（自动对齐或手工调平后）
- **THEN** 无 ERROR、supervision 以显式配置值生效