# token-budget-governance

spec 级 token 预算治理能力：预算消费的分级观测（告警）、判定面联动（judge 重跑额度）与近满收敛（复验子集化）。归属 fenixd 框架 agent_runner 与 pm_engine 验证链。

## 术语

- 预算比例 ratio：spec 条目 `_tokens_in` / `agents.token_budget_millions`（per-spec 计数、项目级阈值，现状口径不变）。
- 预算告警幂等标志：同档位告警的 once-per-ratio 防重发标记（现状 `_token_warn_80` / `_token_alert_100`，本能力新增 `_token_major_95`）。
- 收敛复验：只复验「失败场景 ∪ depends_on 前置链（递归）∪ 下游场景」子集的验证模式；子集计算复用 fastlane 既有基建（`subset_scenario_ids` / `merge_subset_report`），但不要求 fastlane 原闸门（失败场景数=1、judge 影响面≤3 文件、无争议）。
- 近满阈值：收敛与 judge 联合判定共用的 ratio 阈值，配置键 `agents.token_conserve_ratio`，浮点 (0, 1]，缺省关闭（未配置 = 全部近满语义不生效）。

## ADDED Requirements

### Requirement: token 预算告警分级（95% major 档）

`_check_token_budget` 新增 ratio>=0.95 的 major 档：独立幂等标志 `_token_major_95`（不复用 `_token_warn_80`，触发时机与复位语义不同），发射经 `_send_token_alert` 传 severity="major"（现有 80%/100% 两档发射保持 warning 不变）。major 经 `admin_store.HUMAN_SEVERITIES` 进人工处置队列，recommended_action 须列出收敛复验/冻结止损/raise_budget 三个处置选项。任何档位 MUST NOT 自动修改 spec 状态（沿用既有 design 决策：告警不自动冻结）。

major 档判定为独立条件（ratio>=0.95 且 `_token_major_95` 未置位即发射），MUST NOT 挂在 ratio>=1.0 分支之下的 elif 链内：单轮大幅消费使 ratio 一步越过 95% 直达 >=100% 时 major 仍补发，保证止损通道不因跳变静默。这与 80% 档「越过 100% 后静默补写 flag、不补发告警」的降噪口径刻意不同——major 是人工止损入口，跳变静默等于通道缺失。

#### Scenario: ratio>=0.95 触发 major 且幂等

- **WHEN** ratio 首次达到 0.95
- **THEN** 发射 severity="major" 告警并置位 `_token_major_95`，告警进人工处置队列（HUMAN_SEVERITIES），recommended_action 含收敛复验/冻结止损/raise_budget 三个选项
- **AND** 同档位后续轮次（ratio 仍 >=0.95）不再重复发射

#### Scenario: 跳变越过 95% 不静默

- **WHEN** 两次预算检查之间 ratio 从 <0.95 一步升至 >=1.0
- **THEN** 100% 档告警照常发射（现状口径），且 major 档同轮补发（`_token_major_95` 未置位）

#### Scenario: 旧两档与不冻结语义不回归

- **WHEN** ratio 处于 [0.80, 0.95) 或 >=1.0
- **THEN** 80%/100% 两档的发射行为、severity=warning、幂等标志语义与现状完全一致；任何档位发射均不修改 spec 状态

### Requirement: raise_budget 复位联动

`_exec_raise_budget` 的幂等标志复位集合维护为常量集（含 `_token_major_95` 在内的全部预算告警标志），执行时遍历复位，防止后续加档再漏复位。

#### Scenario: 预算翻倍后 95% 档可再次触发

- **WHEN** `_exec_raise_budget` 执行（预算翻倍、ratio 回落）
- **THEN** 全部预算告警幂等标志（含 `_token_major_95`）被复位；预算再次烧至 95% 时 major 档可正常再次触发

### Requirement: judge 重跑额度预算联合压缩

judge_gate 重跑上限判定读预算比例：ratio>=`agents.token_conserve_ratio`（配置启用）时，spec 级剩余可重跑次数压缩为 1、轮内真实派发上限由 2 压缩为 1，冻结/停派文案注明「预算近满」。预算面本身不产生冻结（冻结仍由计数触顶或人工裁决触发）。

#### Scenario: 近满且配置启用时额度压缩

- **WHEN** STATE 条目 `_tokens_in` / `agents.token_budget_millions` 的 ratio 达到配置阈值且配置启用
- **THEN** spec 级剩余可重跑次数压缩为 1、轮内真实派发上限压缩为 1，冻结/停派文案注明「预算近满」

#### Scenario: 未近满或未配置零回归

- **WHEN** ratio 未达阈值，或 `agents.token_conserve_ratio` 未配置
- **THEN** judge 判定路径与现状完全一致（spec 级硬上限 5、轮内派发阈值 2 均不变）

### Requirement: 预算近满收敛复验

ratio>=`agents.token_conserve_ratio` 且配置启用时，下一轮验证计划切收敛复验：子集 = 失败场景 ∪ depends_on 前置链（递归）∪ 下游场景，多失败场景时对各失败场景分别计算取并集。验证报告沿用 `merge_subset_report` 先例将子集结果并入前次全量报告（子集外场景沿用前次结论），并注明本轮为收敛模式与子集范围（供 judge 与人工裁决参考）。

收敛子集为空（无既存失败场景可收，如首轮验证或前次全绿后的排程重验）时，本轮 MUST 回落全量口径并落日志，MUST NOT 以空子集出具验证结论。

同轮存在场景修订重验需求时修订重验优先于预算收敛；排程重验 lane 的全量口径在近满时让位收敛子集；切换与仲裁决策落日志。

#### Scenario: 达阈值切子集并注明模式

- **WHEN** ratio 达到配置阈值、配置启用、且本轮为存在既存验证结论的重验轮（有失败场景可收）
- **THEN** 验证计划切收敛子集（失败 ∪ 前置链 ∪ 下游，多失败取并集），报告为子集结果并入前次全量报告的合并态，并注明收敛模式与子集范围

#### Scenario: 空子集回落全量

- **WHEN** 近满触发收敛但既存结论中无失败场景可收（子集为空）
- **THEN** 本轮回落全量口径并落日志，不以空子集出具验证结论

#### Scenario: 通道优先级仲裁落日志

- **WHEN** 同轮同时存在场景修订重验需求与预算收敛触发（或排程重验与预算收敛并存）
- **THEN** 按「场景修订重验 > 预算收敛复验 > 全量重跑（排程重验让位收敛子集）」仲裁，仲裁决策落日志

#### Scenario: 缺省关闭零回归

- **WHEN** `agents.token_conserve_ratio` 未配置
- **THEN** judge 压缩与收敛切换全部不生效，行为与现状一致

### Requirement: 配置键受管登记

`agents.token_conserve_ratio` 须在 dashboard 配置面按受管 agents 键登记（user 缺省登记、`_AGENTS_SOURCE_KEYS` 来源标注与回显、缺省回显段三处一致），并按 (0, 1] 浮点做前置校验（非法值拒绝不落盘，同 `agents.token_budget_millions` 校验范式）。缺登记时设置页提交会被 `_deep_merge_managed` 静默丢弃（既有失败模式，见 config_admin.py 内 `impl_run_budget_max` 同款注释）。

#### Scenario: 设置页写入不丢失

- **WHEN** 用户经设置页提交 `agents.token_conserve_ratio` 合法值（如 0.95）
- **THEN** 值落盘生效，来源标注与数值回显正常（不为 undefined / 不弹回缺省）

#### Scenario: 非法值拒绝

- **WHEN** 提交值不在 (0, 1] 浮点集合（如 1.5、0、"0.95" 字符串、bool）
- **THEN** 前置校验拒绝、不落盘，返回明确错误文案
