# spec 级 token 预算治理

<!-- knowledge: capability=token-budget-governance rev=1
     sources=spec/changes/evo-add-token-budget-escalation-tiers -->

spec 级 token 预算的分级观测与制动体系：预算消费告警三档分级、judge 判定面联动（近满额度压缩）与近满收敛复验（验证子集化）。预算比例 ratio = spec 条目 `_tokens_in` / `agents.token_budget_millions`（per-spec 计数、项目级阈值）。

## 规则

- **告警三档**：
  - 80% warning（幂等标志 `_token_warn_80`）与 100% warning（`_token_alert_100`）：发射行为与 warning 级别不变，一次性不重复。
  - 95% major（独立幂等标志 `_token_major_95`，不复用 `_token_warn_80`）：经 `admin_store.HUMAN_SEVERITIES` 进人工处置队列，recommended_action 列出收敛复验/冻结止损/raise_budget 三个处置选项。
- **major 档判定为独立条件**：ratio>=0.95 且标志未置位即发射，不挂在 ratio>=1.0 分支的 elif 链内——单轮大幅消费使 ratio 一步越过 95% 直达 100% 时 major 同轮补发，人工止损通道不因跳变静默。这与 80% 档「越过 100% 后静默补写标志、不补发告警」的降噪口径刻意不同。
- **告警零自动冻结**：任何档位告警均不修改 spec 状态，制动经由 judge 既有硬闸的额度压缩与人工处置链实现。
- **raise_budget 复位联动**：`_exec_raise_budget` 执行（预算翻倍、ratio 回落）时遍历常量集 `TOKEN_BUDGET_ALERT_FLAGS` 复位全部预算告警幂等标志（含 95% 档）——预算再次烧至 95% 时 major 档可正常再次触发，防「加档忘复位」永久静默。
- **judge 重跑额度预算联合压缩**：配置 `agents.token_conserve_ratio`（浮点 (0,1]，缺省关闭）启用且 ratio 达阈值时，spec 级剩余可重跑次数压缩为 1、轮内真实派发上限由 2 压缩为 1，冻结/停派文案注明「预算近满」；预算面本身不产生冻结（冻结仍由计数触顶或人工裁决触发）。未近满或未配置时 judge 判定与缺省完全一致（spec 级硬上限 5、轮内派发阈值 2 不变）。
- **近满收敛复验**：ratio 达阈值且配置启用时，下一轮验证计划切收敛子集 = 失败场景 ∪ depends_on 前置链（递归）∪ 下游场景；多失败场景时对各失败场景分别计算取并集。子集计算复用 fastlane 既有基建（`subset_scenario_ids` / `merge_subset_report`）但不要求 fastlane 原闸门（失败场景数=1、judge 影响面≤3 文件、无争议）。子集结果并入前次全量报告（子集外场景沿用前次结论，judge 看到的不是缩水报告），验证报告注明收敛模式与子集范围。
- **空子集回落全量**：收敛子集为空（首轮验证、前次全绿后的排程重验等无既存失败场景可收）时，本轮回落全量口径并落日志，不以空子集出具验证结论。
- **通道优先级仲裁**：场景修订重验 > 预算收敛复验 > 全量重跑（排程重验 lane 的全量口径在近满时让位收敛子集）；仲裁决策落日志。
- **配置键受管登记**：`agents.token_conserve_ratio` 在 dashboard 配置面按受管 agents 键三面登记（user 缺省登记、`_AGENTS_SOURCE_KEYS` 来源标注与回显、缺省回显段），并按 (0,1] 浮点做前置校验（非法值拒绝不落盘，同 `agents.token_budget_millions` 校验范式）。缺登记的失败模式：设置页提交被 `_deep_merge_managed` 静默丢弃。

## 代码锚点

- 主实现：`core/agent_runner/token_budget.py`（三档发射与幂等标志常量集 TOKEN_BUDGET_ALERT_FLAGS）、`core/pm_engine/verification/judge_gate.py`（近满额度压缩）、`core/pm_engine/verification/pipeline.py`（收敛触发与通道优先级仲裁）、`core/pm_engine/verification/fastlane.py`（子集计算复用入口）
- 复位联动：`core/dashboard/data/admin_actions.py`（_exec_raise_budget）
- 配置键登记：`core/dashboard/data/config_admin.py`
- 守卫测试：`tests/test_token_budget_escalation.py`

## 溯源

- 2026-11-16 evo-add-token-budget-escalation-tiers（spec/changes/evo-add-token-budget-escalation-tiers/） — 新增本页：95% major 档与独立判定条件（跳变补发）、幂等标志常量集与 raise_budget 遍历复位、judge 近满额度压缩、预算收敛复验（子集复用 fastlane 基建、空子集回落全量、通道优先级仲裁）、token_conserve_ratio 受管登记与 (0,1] 校验。背景：单重型 spec 预算烧至 99.9% 全程仅 warning 告警，唯一人工干预 raise_budget 翻倍后续烧至 99.9M，止损通道事实缺位。
