## MODIFIED Requirements

### Requirement: 激活 = start_after 置 null 并即时唤醒派发

系统 SHALL 提供「激活」动作，将处于待激活态（`start_after == "manual"`）的 SPEC 的
`start_after` 置为 null，并写入即时唤醒文件信号（载体形态、写入语义与失败回报契约见
`scheduling-kick-signal` 能力；本 Requirement MUST NOT 硬编码信号文件路径），使 daemon
主循环在秒级粒度唤起该 SPEC 的派发，SHALL NOT 等待 30 分钟周期扫描兜底。

「秒级唤醒」SHALL 以**唤醒信号成功写出**为前提：写入失败时该 SHALL NOT 被表述为
「秒级派发」，动作方 MUST 按 `scheduling-kick-signal` 能力如实回报，该 SPEC 退回
周期扫描兜底。

激活动作 SHALL 幂等且拒绝误操作：对 `start_after` 非 `manual` 的 SPEC（含已设置定时值或 null 的）执行激活 SHALL 返回明确拒绝（`ok: false` 且附原因），SHALL NOT 修改该 SPEC 的 `start_after`（避免误清定时值）。对不在 STATE.md 的 SPEC SHALL 返回未找到。终态（done/pushed）SPEC SHALL 被拒绝。

#### Scenario: 激活待激活 SPEC

- **WHEN** 某 ready SPEC 的 `start_after` 为 `manual`，用户执行激活
- **THEN** 该 SPEC 的 `start_after` 变为 null，且写入唤醒信号；daemon 在秒级内拾取并派发

#### Scenario: 激活时信号写入失败如实告知

- **WHEN** 用户激活某待激活 SPEC，`start_after` 已置 null 但唤醒信号写入失败
- **THEN** 接口返回 `ok: true` 并携带说明「即时唤醒未生效、将由后续扫描派发」的告警字段

#### Scenario: 两 SPEC 先后激活互不阻塞

- **WHEN** 用户在同一时间窗内先后激活 SPEC A 与 SPEC B
- **THEN** 两个 SPEC 的唤醒信号均成功写入，两者都被即时派发（MUST NOT 出现后者被丢弃）

#### Scenario: 对非待激活 SPEC 激活被拒

- **WHEN** 某 SPEC 的 `start_after` 为合法时间戳（定时拾取中）或 null，执行激活
- **THEN** 返回 `ok: false` 与拒绝原因，`start_after` 保持原值不变

#### Scenario: 激活不存在的 SPEC

- **WHEN** 对不在 STATE.md 的 spec 名执行激活
- **THEN** 返回未找到，STATE.md 无变更

#### Scenario: 终态 SPEC 拒绝激活

- **WHEN** 对 status 为 done 或 pushed 的 SPEC 执行激活
- **THEN** 被拒绝并附原因，STATE.md 无变更

### Requirement: 各立项与放行入口提供手工激活选项

以下入口 SHALL 支持把新注册/放行的 SPEC 设为待激活（`start_after = "manual"`）：

- **`/fenix-new` 需求 Agent**：执行时机确认 SHALL 由二选一（立即 / 定时）扩为三选一，新增「手工激活」档；选择后注册时经 `add_spec` attrs 写入 `start_after: "manual"`
- **自进化「同意立项」**：Dashboard 弹窗执行时刻 SHALL 由二选一（立即 / 指定时间）扩为三选一，新增「手工激活」；后端 `POST /api/evolution/accept` SHALL 接受哨兵值（body 的 `start_after` 取 `"manual"`）并透传 `accept_item`
- **Dashboard「修改状态」**：对 ready 态 SPEC SHALL 提供双向操作——当前待激活时显示「激活（立即调度）」；当前非待激活时显示「设为待激活」
- **CLI**：`bin/fenix_cli.py` SHALL 提供 `activate <spec>` 子命令执行激活动作

**不在本仓库门禁范围内（人工步骤）**：`/fenix-ready` 放行时可一并选择「设为待激活」——该 skill 位于仓库外（`~/.claude/skills/fenix-ready/`，实测为**真实目录**而非指向本仓库 `skills/` 的软链；本仓库 `skills/` 下无 `fenix-ready`），**不可作为本仓库交付物**，故本条**不**是可由本仓库 gate 核对的 SHALL。其改动要点（放行确认步骤增一问「放行后立即调度 / 设为待激活」）由 `docs/help/06-governance.md` 记录，由人工在主树同步（见 tasks.md 末组「人工步骤」）。本能力的其余四个入口均为仓库内交付物，SHALL 照常受门禁核对。

#### Scenario: fenix-new 手工激活档

- **WHEN** 用户经 `/fenix-new` 立项并选择「手工激活」
- **THEN** 该 SPEC 注册后 `start_after` 为 `manual`，处于待激活态，不被自动拾取

#### Scenario: evo 同意立项手工激活档

- **WHEN** 用户在自进化「同意立项」弹窗选择「手工激活」并确认
- **THEN** 新建 SPEC 的 `start_after` 为 `manual`，不被自动拾取

#### Scenario: 修改状态弹窗设为待激活

- **WHEN** 用户对某 ready 且 `start_after` 非 manual 的 SPEC 在「修改状态」弹窗点击「设为待激活」
- **THEN** 该 SPEC 的 `start_after` 变为 `manual`，列表渲染「待激活」标记

#### Scenario: 修改状态弹窗激活动作

- **WHEN** 用户对某 ready 且 `start_after` 为 manual 的 SPEC 在「修改状态」弹窗点击「激活」
- **THEN** 该 SPEC 的 `start_after` 置 null 并被立即派发

#### Scenario: CLI 激活子命令

- **WHEN** 用户执行 `python3 bin/fenix_cli.py activate <spec>` 且该 SPEC 待激活
- **THEN** 命令成功退出（exit 0），SPEC 被激活；非待激活态时输出拒绝原因并 exit 1
