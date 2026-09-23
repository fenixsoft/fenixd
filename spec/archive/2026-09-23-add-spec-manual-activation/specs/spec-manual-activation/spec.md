## ADDED Requirements

### Requirement: start_after 哨兵值 manual 表示永不到期

系统 SHALL 支持 `start_after` 取哨兵值 `manual`，语义为「永不到期，须人工激活后方可被调度器拾取」。`start_after` 的取值域自此为三态：ISO8601 UTC 时间戳（定时拾取）/ 哨兵字符串 `manual`（待激活）/ null（无限制，立即调度），三者互斥。哨兵值 SHALL 为 `StateMachine` 模块级常量 `START_AFTER_MANUAL`（值 `"manual"`），判定 SHALL 大小写不敏感且忽略首尾空白（容错手工编辑 STATE.md）。

`start_after_pending(entry, now)` 谓词 SHALL 在时间解析**之前**显式判定哨兵值：命中 `manual` 时 SHALL 恒返回 `True`（永远视为未到期），SHALL NOT 落入 `parse_utc` 的 fail-open 分支（该分支对非法值返回「不阻塞」，与哨兵语义相反）。哨兵值 SHALL NOT 被 `parse_utc` 接受为时间。

#### Scenario: 哨兵值时谓词恒真

- **WHEN** 某 SPEC 的 `start_after` 为 `manual`，调用 `start_after_pending(entry)`
- **THEN** 返回 `True`（无论当前时间为何）

#### Scenario: 哨兵不落入 fail-open 分支

- **WHEN** 某 SPEC 的 `start_after` 为 `manual`
- **THEN** 该 SPEC 在所有派发入口（`_on_spec_ready` / dispatch 候选筛选 / recovery / admin 巡检）均被静默跳过，不被拾取

#### Scenario: 大小写与空白容错

- **WHEN** `start_after` 值为 `"Manual"`、`"MANUAL"` 或 `" manual "`（手工编辑变体）
- **THEN** 一律判定为哨兵值，`start_after_pending` 返回 `True`

#### Scenario: 存量值语义不变

- **WHEN** `start_after` 为 `null`、合法 ISO8601 时间戳或非法格式字符串（非 `manual`）
- **THEN** 行为与本次变更前完全一致（null/非法 → 不阻塞；未来时间 → 阻塞；过去时间 → 不阻塞）

### Requirement: 激活 = start_after 置 null 并即时唤醒派发

系统 SHALL 提供「激活」动作，将处于待激活态（`start_after == "manual"`）的 SPEC 的 `start_after` 置为 null，并写入既有即时唤醒文件信号 `.fenix/scheduling_kick_request.json`（与清空定时拾取同构），使 daemon 主循环在秒级粒度唤起该 SPEC 的派发，SHALL NOT 等待 30 分钟周期扫描兜底。

激活动作 SHALL 幂等且拒绝误操作：对 `start_after` 非 `manual` 的 SPEC（含已设置定时值或 null 的）执行激活 SHALL 返回明确拒绝（`ok: false` 且附原因），SHALL NOT 修改该 SPEC 的 `start_after`（避免误清定时值）。对不在 STATE.md 的 SPEC SHALL 返回未找到。终态（done/pushed）SPEC SHALL 被拒绝。

#### Scenario: 激活待激活 SPEC

- **WHEN** 某 ready SPEC 的 `start_after` 为 `manual`，用户执行激活
- **THEN** 该 SPEC 的 `start_after` 变为 null，且写入唤醒信号；daemon 在秒级内拾取并派发

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

**不在本仓库门禁范围内（人工步骤）**：`/fenix-ready` 放行时可一并选择「设为待激活」——该 skill 位于仓库外（`~/.claude/skills/fenix-ready/`，实测为**真实目录**而非指向本仓库 `skills/` 的软链；本仓库 `skills/` 下无 `fenix-ready`），**不可作为本仓库交付物**，故本条**不**是可由本仓库 gate 核对的 SHALL。其改动要点（放行确认步骤增一问「放行后立即调度 / 设为待激活」）由 `docs/help/06-governance.md` 记录，由人工在主树同步（见 tasks.md §9「人工步骤」）。本能力的其余四个入口均为仓库内交付物，SHALL 照常受门禁核对。

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

### Requirement: 待激活 SPEC 不被到期检测误判并豁免等待告警

60s 定时到期检测 `check_scheduling_deadlines` SHALL 跳过 `start_after == "manual"` 的 SPEC（其非时间值，无到期检测需求）；系统 SHALL NOT 因此将该 SPEC 判为「已到期待唤起」。待激活 SPEC SHALL 与定时拾取、冻结同属「有意等待」族——admin 无待派发巡检与孤儿 ready 恢复 SHALL 视为按计划等待，SHALL NOT 产生孤儿/异常告警。

#### Scenario: 到期检测不误判哨兵

- **WHEN** 某待激活 SPEC 连续经过多轮 60s 定时到期检测
- **THEN** 该 SPEC 不被唤起派发，`start_after` 保持 `manual`，无状态变更

#### Scenario: 待激活视作有意等待不告警

- **WHEN** 某 ready SPEC 的 `start_after` 为 `manual`，daemon 执行 admin 巡检与 recovery
- **THEN** 该 SPEC 被视为「按计划等待」，不计入孤儿（不写 error，不产生告警）
