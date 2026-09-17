# Spec Delta: timeout-supervision

## NEW Requirements

### Requirement: 统一 supervision absolute_max 下限派生口径

supervision `absolute_max_seconds` 的下限 MUST 由**单一派生函数**给出（建议签名 `ConfigLoader.supervision_floor(config, agent_type=None, extension_budget=None)`），公式 `下限 = 生效 run_timeout_seconds + 续期预算 × extension_seconds`；config 校验层与 liveness 兜底层 MUST 调用该同一实现，禁止两处各自手写常数（现状 config.py:29 硬编码 7200 ⇒ 22200，liveness.py:777-789 手写 `max_extensions × extension_seconds` ⇒ 18600）。

- **运行时口径（liveness 兜底）**：`生效 run_timeout` = `agents.timeout_overrides.<agent_type>` 或全局 `agents.run_timeout_seconds`；`续期预算 = max_extensions`，fast-track 且 `_fast_track_scale_tier == "higher"` 时 `+2`（保持既有加成语义）。当前配置下：implementer = 15000 + 2×1800 = **18600s**，fast-track higher 档 = 15000 + 4×1800 = **22200s**。本改动 MUST NOT 改变这些运行时数值。
- **配置校验层口径（启动/热更新）**：MUST 取该部署可达的**最大**下限 = `max(全局 run_timeout_seconds, agents.timeout_overrides 全部值) + (max_extensions + 2) × extension_seconds`（+2 覆盖 fast-track higher 档加成），当前配置 = 15000 + 4×1800 = **22200s**。仅用基础预算（18600s）会漏掉 fast-track higher 档，该档运行时仍命中同文案 ERROR，「消除 ERROR 复发」不可达成。
- 该 22200s 与既有 `core/config.py:29 SUPERVISION_EXTENSION_SECONDS = 7200`（= 4×1800）及 `.fenix/config.template.yaml:108/258 absolute_max_seconds: 16200`（= 9000 + 4×1800）同口径：配置层 MUST 沿用「按最大可达续期预算」的保守性，本改动只把手写常数改为派生，MUST NOT 下调。

#### Scenario: 两处口径一致

- **WHEN** supervision 激活路径与 config 校验路径同时读取 absolute_max 下限
- **THEN** 两者由同一派生函数给出：运行时按 agent 实际预算（基础档 18600s / fast-track higher 档 22200s），配置校验层按全部署最大下限（22200s），无手写常数、无口径漂移

### Requirement: 启动/热更新一致性校验（默认自动对齐，关闭则阻断）

配置加载（启动或热更新）时 MUST 校验 `absolute_max_seconds ≥ 配置校验层下限`（见上）；`timeout_supervision.enabled=false` 或缺段时不校验。不一致时 MUST：

- 输出明确 ERROR（含两侧配置值、配置校验层下限、修正建议：抬升 absolute_max 或下调 run_timeout——后者用于保住 14400s 级别的显式硬上限）；
- **默认自动对齐**（`timeout_supervision.auto_align` 缺省 true）：将 absolute_max 抬升至下限，内存生效并持久化；持久化 MUST 复用既有配置写路径 `core.dashboard.data.write_config`（受管键白名单 + 原子写 + 配置头注释），`core/config.py` MUST NOT 直接写配置文件。该分支 MUST NOT 抛异常，以保证启动与热更新均可继续；
- **自动对齐被显式关闭**且 supervision 启用时 MUST fail-fast 阻断（启动/加载返回失败；热更新 MUST 拒绝新配置并保留旧值），MUST NOT 仅告警后静默按兜底值继续。

**顺序约定**：自动对齐分支先执行，仅当其被显式关闭时才进入阻断分支——两者不同时生效。

**背景（实测依据）**：fenixd.log 5 条 ERROR（09-15T15:49:54Z/16:19:54Z、09-16T08:32:50Z/09:02:50Z/09:32:51Z，行 13181/13218/14985/15018/15051，全部来自 liveness 运行时兜底），config.yaml:22=15000/:27=14400 未对齐；config.py:1241-1269 现状为 ERROR+返回兜底不阻断（其 guard 值 22200 仅被 runner.py:2583 用于 DEBUG 比较）。热更新既有语义已满足「失败保留旧值」：fenixd.py:512-515 try/except + config.py:252-264 失败不触碰旧 dict，MUST 复用而非新建机制。

#### Scenario: 不一致时默认自动对齐

- **WHEN** 配置加载发现 absolute_max(14400) < 配置校验层下限(22200) 且自动对齐开启（缺省）
- **THEN** 输出 ERROR（含 14400/22200 与两条修正建议），absolute_max 抬升至 22200 并持久化，加载继续；后续 liveness 运行时不再出现同文案 ERROR

#### Scenario: 关闭自动对齐时启动阻断

- **WHEN** 自动对齐被显式关闭且配置加载发现 absolute_max(14400) < 下限(22200)
- **THEN** 启动/加载返回失败并输出 ERROR 与修正建议（fail-fast），不静默按兜底继续

#### Scenario: 热更新不一致被拒绝并保留旧值

- **WHEN** 运行期配置热更新后 absolute_max < 下限，且自动对齐关闭
- **THEN** 新配置被拒绝、共享 config dict 保持旧值（既有 resolve_config_into 语义），daemon 不退出

#### Scenario: 一致时正常启动

- **WHEN** absolute_max ≥ 配置校验层下限（自动对齐或手工调平后）
- **THEN** 无 ERROR、supervision 以显式配置值生效
