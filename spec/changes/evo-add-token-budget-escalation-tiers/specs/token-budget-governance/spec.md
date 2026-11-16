# token-budget-governance

spec 级 token 预算治理能力：预算消费的分级观测（告警）、判定面联动（judge 重跑额度）与近满收敛（复验子集化）。归属 fenixd 框架 agent_runner 与 pm_engine 验证链。

## 术语

- 预算比例 ratio：spec 条目 `_tokens_in` / `agents.token_budget_millions`（per-spec 计数、项目级阈值，现状口径不变）。
- 预算告警幂等标志：同档位告警的 once-per-ratio 防重发标记（现状 `_token_warn_80` / `_token_alert_100`，本能力新增 `_token_major_95`）。
- 收敛复验：只复验「失败场景 ∪ depends_on 前置链（递归）∪ 下游场景」子集的验证模式；子集计算复用 fastlane 既有基建，但不要求 fastlane 原闸门（失败场景数=1、judge 影响面≤3 文件、无争议）。
- 近满阈值：收敛与 judge 联合判定共用的 ratio 阈值，配置键 `agents.token_conserve_ratio`，浮点 (0, 1]，缺省关闭（未配置 = 全部近满语义不生效）。

## 行为

1. 分级告警：ratio>=0.80 发 warning（现状保留）；ratio>=0.95 发 major（新增，幂等标志 `_token_major_95`）；ratio>=1.00 发 warning（现状保留）。major 经 admin_store.HUMAN_SEVERITIES 进人工处置队列，recommended_action 须列出收敛复验/冻结止损/raise_budget 三个处置选项。任何档位 MUST NOT 自动修改 spec 状态（沿用既有 design 决策：告警不自动冻结）。
2. 复位联动：raise_budget 裁决执行（admin_actions._exec_raise_budget）时复位全部预算告警幂等标志——复位集合维护为常量集（含新增档），防止后续加档再漏。
3. judge 联合判定：judge_gate 重跑上限判定读预算比例——ratio>=近满阈值时 spec 级剩余可重跑次数压缩为 1、轮内真实派发上限由 2 压缩为 1；冻结/停派文案注明「预算近满」。预算未近满时判定路径与现状完全一致。预算面本身不产生冻结（冻结仍由计数触顶或人工裁决触发）。
4. 收敛复验切换：ratio>=近满阈值且配置启用时，下一轮验证计划切收敛复验，验证报告须注明本轮为收敛模式与子集范围（供 judge 与人工裁决参考）；同轮存在场景修订重验需求时修订重验优先于预算收敛；排程重验 lane 的全量口径在近满时让位收敛子集。切换与仲裁决策落日志。
5. 缺省语义：`agents.token_conserve_ratio` 未配置时，本能力全部近满语义（judge 压缩、收敛切换）不生效，行为与现状一致——收敛模式减少验证覆盖属治理取舍，默认不改变行为。