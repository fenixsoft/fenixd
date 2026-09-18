# spec-review-gate — SPEC 方案评审门禁

## ADDED Requirements

### Requirement: reviewing 状态与合法转移边

状态机 SHALL 新增第 11 个状态 `reviewing`（评审中），纳入 `SpecStatus` 枚举与 `ALL` 列表。`VALID_TRANSITIONS` SHALL 扩展为：`drafted → [ready, reviewing]`、新增 `reviewing → [ready, blocked]`、`blocked → [ready, reviewing]`。既有 `blocked → ready` 边 MUST 保留。对 `reviewing` 的非法转移（如 `reviewing → implementing`、`reviewing → implemented`）SHALL 被拒绝并记录 ERROR，MUST NOT 改写状态。

#### Scenario: drafted 可进 reviewing
- **WHEN** 对 `drafted` 状态的 SPEC 执行 `transition(spec, "reviewing")`
- **THEN** 转移成功，状态变为 `reviewing`

#### Scenario: reviewing 通过后进 ready
- **WHEN** 对 `reviewing` 状态的 SPEC 执行 `transition(spec, "ready")`
- **THEN** 转移成功，状态变为 `ready`

#### Scenario: reviewing 否决后进 blocked
- **WHEN** 对 `reviewing` 状态的 SPEC 执行 `transition(spec, "blocked")`
- **THEN** 转移成功，状态变为 `blocked`

#### Scenario: blocked 可重回 reviewing
- **WHEN** 对 `blocked` 状态的 SPEC 执行 `transition(spec, "reviewing")`
- **THEN** 转移成功，状态变为 `reviewing`

#### Scenario: 非法转移被拒
- **WHEN** 对 `reviewing` 状态的 SPEC 执行 `transition(spec, "implementing")`
- **THEN** 转移失败并记 ERROR，状态保持 `reviewing`

#### Scenario: 状态全集含 reviewing
- **WHEN** 读取 `SpecStatus` 的全部状态列表
- **THEN** 列表含 `reviewing`，总数为 11

### Requirement: 评审模式配置键

系统 SHALL 提供配置键 `gates.spec_review_mode`（枚举 `auto`/`never`），缺省值 MUST 为 `auto`。配置校验 SHALL 拒绝非枚举值并在加载时报错，错误信息 MUST 指出合法取值。该键 MUST 纳入 Dashboard 受管配置键白名单（读侧 sources 标注与写侧提取两处），支持经设置页读写与配置热更新（30s mtime 原地重载）。

`auto` 的语义为「默认全量评审，命中跳过白名单者除外」；`never` 的语义为「完全关闭评审」，此时候选 SPEC 的晋升行为 MUST 与引入本特性之前完全一致（`drafted → ready` 直通，不派发评审 run，不写评审相关 error）。

#### Scenario: 缺省值为 auto
- **WHEN** 配置文件中不存在 `gates.spec_review_mode` 键
- **THEN** getter 返回 `auto`，默认全量评审生效

#### Scenario: 显式 never 恢复旧行为
- **WHEN** `gates.spec_review_mode` 为 `never` 且某 SPEC 进入晋升链
- **THEN** 该 SPEC 直接 `transition ready` 并进入实现调度，不派发任何评审 run，STATE 无评审相关字段写入

#### Scenario: 非法值被拒
- **WHEN** 配置文件中 `gates.spec_review_mode` 为 `"always"` 或其它非枚举值
- **THEN** 配置加载校验失败并给出明确错误信息，指出合法取值为 auto/never

#### Scenario: 设置页读写与热更新
- **WHEN** 用户在设置页审批页签选择评审模式并保存
- **THEN** 值持久化到对应配置层，daemon 在热更新窗口内感知新值，无需重启

### Requirement: 评审跳过白名单

在 `gates.spec_review_mode: auto` 下，系统 SHALL 对每个进入晋升链的 SPEC 执行跳过判定。仅当下列四项**全部命中**时，该 SPEC SHALL 跳过评审直通 `ready`：

1. `.spec.yaml` 的 `mode` 为 `fast-track`
2. `specs/` 下的能力目录数 ≤ 1
3. `tasks.md` 的 Deliverables 声明段条目数 ≤ 3
4. SPEC 名 MUST NOT 以 `evo-` 开头

未命中任一条件（含四项中任一不满足）的 SPEC SHALL 进入 `reviewing`。`evo-` 前缀为**硬否决项**：即使前三项全部命中，`evo-` SPEC MUST 仍进入评审。字段缺失时的判定 MUST 保守取「不跳过」：`mode` 缺失或无法解析、无 Deliverables 声明段时，该条件 SHALL 视为不满足。

#### Scenario: 四项全中跳过评审
- **WHEN** 某 SPEC 的 mode 为 `fast-track`、能力目录 1 个、声明段 2 条、名称非 evo- 前缀
- **THEN** 该 SPEC 直接 `transition ready`，不派发评审 run

#### Scenario: evo- 前缀硬否决
- **WHEN** 某 `evo-` 前缀 SPEC 的 mode 为 `fast-track`、能力目录 1 个、声明段 2 条
- **THEN** 该 SPEC 仍进入 `reviewing` 并派发评审 run

#### Scenario: 非 fast-track 不跳过
- **WHEN** 某 SPEC 的 mode 为 `full`，其余三项均命中
- **THEN** 该 SPEC 进入 `reviewing`

#### Scenario: 能力数超阈值不跳过
- **WHEN** 某 fast-track SPEC 的能力目录数为 2
- **THEN** 该 SPEC 进入 `reviewing`

#### Scenario: 声明段缺失时保守评审
- **WHEN** 某 fast-track SPEC 无 Deliverables 声明段（条目数无法解析）
- **THEN** 跳过条件不成立，该 SPEC 进入 `reviewing`

#### Scenario: mode 缺失时保守评审
- **WHEN** 某 SPEC 的 `.spec.yaml` 无 `mode` 字段
- **THEN** 跳过条件不成立，该 SPEC 进入 `reviewing`

### Requirement: 晋升链接入与全通道覆盖

共享晋升函数 `promote_drafted` SHALL 在执行完既有软化与两道 lint 后执行评审跳过判定，并在返回值中给出下一状态（`next_status` ∈ `ready` / `reviewing`）。调用方 SHALL 依 `next_status` 执行 `transition`。

全部四条通道 MUST 覆盖同一判定：PM Engine 自动晋升（`_on_spec_drafted`）、Dashboard `POST /api/spec-promote`、CLI `bin/fenix_cli.py promote`、`/fenix-ready` skill。任一通道 MUST NOT 绕过判定直写 `ready`。

`gates.promote_mode: manual` 的闸口语义 MUST 保持不变：`manual` 时 SPEC 停留 `drafted` 不晋升、不派发、不写 error；人工放行后 MUST 同样经过评审判定。

#### Scenario: 自动晋升走出分流
- **WHEN** `gates.promote_mode` 为 `auto` 且新 SPEC 注册为 drafted 并通过 lint
- **THEN** 依跳过判定结果，该 SPEC 或直接 `ready`、或进入 `reviewing` 并派发评审 run

#### Scenario: Dashboard 通道同语义
- **WHEN** 经 `POST /api/spec-promote` 放行一个未命中白名单的 drafted SPEC
- **THEN** 该 SPEC 进入 `reviewing`（而非直接 `ready`），与自动通道结论一致

#### Scenario: CLI 通道同语义
- **WHEN** 经 `bin/fenix_cli.py promote <spec>` 放行一个未命中白名单的 drafted SPEC
- **THEN** 该 SPEC 进入 `reviewing`，与自动通道结论一致

#### Scenario: manual 闸口语义不变
- **WHEN** `gates.promote_mode` 为 `manual` 且 SPEC 注册为 drafted
- **THEN** SPEC 停留 `drafted`，不软化、不 lint、不写 error、不派发；人工放行后才走评审判定

#### Scenario: lint 违规仍停留 drafted
- **WHEN** 某 SPEC 的声明段存在 lint 违规
- **THEN** SPEC 停留 `drafted` 并写入 error，MUST NOT 进入 `reviewing`

#### Scenario: never 模式全通道直通
- **WHEN** `gates.spec_review_mode` 为 `never`
- **THEN** 四条通道的晋升行为均与引入本特性前一致，全部直通 `ready`

### Requirement: 事件总线与调度器接入

`reviewing` 状态 SHALL 接入既有的状态事件与调度机制：

- `core/event_bus.py` 的 `_status_to_event` SHALL 映射 `"reviewing": "spec_reviewing"`。
- `core/pm_engine/engine.py` 的事件处理器表 SHALL 注册 `"spec_reviewing": self._on_spec_reviewing`。
- `check_scheduling_deadlines` SHALL 对 `reviewing` 状态的 SPEC 走评审派发路径（与 `drafted` 走晋升链、其余状态走 `_on_spec_ready` 并列）。
- `_recover_one` SHALL 对 `reviewing` 状态的 SPEC 做评审派发恢复。

上述四处的合计效果 MUST 使四条晋升触发路径（`spec_drafted` 事件、`start_after` 到期唤起、full_scan recovery re-trigger、外部 drafted 写入 / scheduling_kick）在分流判定为「需评审」时均能进入 `reviewing` 并被派发。

#### Scenario: 状态事件被映射
- **WHEN** 某 SPEC 状态变为 `reviewing`
- **THEN** 状态变化被映射为事件 `spec_reviewing` 并投递给 PM Engine

#### Scenario: 事件触发派发
- **WHEN** PM Engine 收到 `spec_reviewing` 事件
- **THEN** 调用评审派发入口并派发评审 run

#### Scenario: full_scan recovery 恢复 reviewing
- **WHEN** full_scan recovery 扫描到一个停留在 `reviewing` 且无在飞 run 的 SPEC
- **THEN** 该 SPEC 被重新派发评审，MUST NOT 被静默跳过或误判为 `ready`

#### Scenario: start_after 到期后进入评审
- **WHEN** 某 drafted SPEC 的 `start_after` 到期且分流判定为需评审
- **THEN** 该 SPEC 进入 `reviewing` 并被派发

#### Scenario: 重派竞态被阻断
- **WHEN** 某 SPEC 已处于 `reviewing` 且其评审 run 正在运行
- **THEN** PM Engine MUST NOT 重复派发第二个评审 run

### Requirement: reviewing 中断态恢复

`reviewing` SHALL 属于中断态，与 `implementing` / `testing` 同口径处理：daemon 重启时 SHALL 将该状态的 SPEC 回退到 `drafted`，清空评审 run 引用并重置评审尝试计数，使其重新进入晋升链（软化与两道 lint 幂等，分流重新判定）。回退 MUST NOT 丢失评审者对 SPEC 目录已作出的修补。

#### Scenario: 重启回退到 drafted
- **WHEN** daemon 重启且某 SPEC 停留在 `reviewing`
- **THEN** 该 SPEC 状态回退为 `drafted`，评审 run 引用被清空，评审尝试计数被重置

#### Scenario: 回退后重新分流
- **WHEN** 回退后的 SPEC 重新进入晋升链
- **THEN** 分流判定重新执行；若此时命中跳过白名单则直通 `ready`，否则重新进入 `reviewing`

#### Scenario: 已作出的修补被保留
- **WHEN** 评审者在 SPEC 目录内已修改 `tasks.md` 后 daemon 崩溃重启
- **THEN** 回退过程 MUST NOT 还原该修改，重新评审基于已修补的内容进行

### Requirement: 评审 run 并发闸门

评审 run SHALL 计入 PM Engine 既有并发闸门，占用与普通 run 等价的槽位，MUST NOT 新开独立并发通道。并发上限达成时，`reviewing` 状态的 SPEC SHALL 排队等待，MUST NOT 跳过评审直接进入 `ready`。

#### Scenario: 并发满时排队
- **WHEN** 并发槽位已满且某 SPEC 进入 `reviewing`
- **THEN** 该 SPEC 保持 `reviewing` 等待槽位释放，MUST NOT 被直接放行到 `ready`

#### Scenario: 槽位释放后派发
- **WHEN** 并发槽位释放且存在等待中的 `reviewing` SPEC
- **THEN** 按既有优先级规则派发评审 run
