# add-token-budget-escalation-tiers 设计

## 现状锚点（已回源核实）

- core/agent_runner/token_budget.py：_check_token_budget 现有两档分支（ratio>=1.0 与 ratio>=0.8 的 elif 链，:419-448），发射点 severity 硬编码 "warning"；_send_token_alert 已有 severity 形参（:467）；幂等标志 _token_warn_80/_token_alert_100；docstring 记录 2026-09-01 降噪决策（两档均警告、不自动冻结，:302）。
- core/admin_store.py:100：HUMAN_SEVERITIES = ("critical", "major")——major 告警天然进人工队列，本能力零改动复用。
- core/dashboard/data/admin_actions.py:2388 _exec_raise_budget：现只复位 _token_warn_80/_token_alert_100 两标志（:2428）。
- core/dashboard/data/config_admin.py：agents.* 受管键三面登记（user 缺省登记 :42-58、_AGENTS_SOURCE_KEYS 来源/回显 :160-172、缺省回显段 :783+）+ 前置校验分支（token_budget_millions 范式 :1795-1806）；:163-166 注释明言缺登记会被 _deep_merge_managed 静默丢写（impl_run_budget_max 同款失败先例）。
- core/pm_engine/verification/judge_gate.py:46 _MAX_JUDGE_RERUNS=5（spec 级）、:52 轮内真实派发阈值 _JUDGE_ROUND_MAX_REAL_DISPATCHES=2、超限冻结判定在计数分支；同函数已有读 STATE 条目字段惯例（:906 已读 _tokens_in）。
- core/pm_engine/verification/fastlane.py:363 subset_scenario_ids（失败场景 ∪ depends_on 前置链递归 ∪ 下游；签名单 failed_id，预算通道多失败场景须取并集）、:403 merge_subset_report（子集报告并入前次全量报告先例）、:500 evaluate_fastlane；调用点 core/pm_engine/verification/pipeline.py:1376；fastlane 现闸门只挂 bug-found 路径。

## 设计决策

1. 95% major 档用独立幂等标志 _token_major_95，不复用 _token_warn_80（触发时机与复位语义不同）；发射直接传 severity="major"，admin_store 零改动。major 档判定为独立条件（ratio>=0.95 且标志未置位即发射，含 ratio 已越过 100% 的跳变补发），不挂在 ratio>=1.0 分支的 elif 链之下——现有分支结构（:419 ratio>=1.0 无条件接管 → :448 elif ratio>=0.8）下若把 95% 档放链中，单轮跳变越过 95% 直达 100% 将永不进人工止损通道。与 80% 档「越过 100% 静默补写不补发」的降噪口径刻意不同：80% 是观测降噪，major 是人工止损入口。
2. raise_budget 复位清单改为遍历预算告警幂等标志常量集（新档加入常量集）——消除「加档忘复位」的重复隐患（本例中若 95% 档先于翻倍存在，翻倍后即永久静默）。
3. judge 联合判定做「额度压缩」而非「预算面直接冻结」：预算近满是升级信号，冻结仍由计数触顶或人工裁决触发——与「告警不自动冻结 spec」决策保持同向，制动经由既有硬闸（judge_rerun_cap）的额度收缩实现，语义是「预算近满时判定面主动省着用」。
4. 收敛切换阈值独立配置且缺省关闭：收敛复验减少子集外场景的覆盖，是治理取舍而非纯收益；默认不改行为，启用是显式项目决策。触发源挂在验证计划生成/路径选择处（pipeline.py:1376 一带），复用 fastlane 子集计算但独立于 fastlane 闸门（预算触发通道不要求 1 失败/≤3 文件）。子集计算按失败场景集合逐个计算取并集（subset_scenario_ids 签名单 failed_id，预算通道天然多失败）；收敛报告沿用 merge_subset_report 先例并入前次全量报告（子集外场景沿用前次结论，judge 看到的不是缩水报告）。空子集守卫：无既存失败场景可收（首轮验证、前次全绿后的排程重验）时回落全量口径并落日志，MUST NOT 以空子集出具验证结论。
5. 通道优先级仲裁集中在 pipeline 判定点：场景修订重验 > 预算收敛复验 > 全量重跑/排程重验全量口径；仲裁决策落日志，验证报告注明收敛模式与子集范围——judge 与人工裁决需要知道本轮不是全量。
6. 新配置键 agents.token_conserve_ratio 按 config_admin.py 受管 agents 键三面登记（user 缺省登记、_AGENTS_SOURCE_KEYS、缺省回显段）+ (0,1] 浮点前置校验（同 token_budget_millions :1795 范式）——漏登记的失败模式（设置页提交被 _deep_merge_managed 静默丢弃）在该文件 :163-166 有先例注释，属必改面而非可选。

## 风险与缓解

- 收敛复验漏回归面（子集外场景回归未被发现）——以阈值缺省关闭 + major 档人工处置链兜底；报告注明模式与范围，裁决可要求回到全量。
- 新档幂等标志漏复位致永久静默——复位集合常量化 + 单测把守（任务 1.2 / 4.1）。
- judge 额度压缩过早导致验证不充分——压缩仅在 ratio>=近满阈值时生效，且近满本身已是 95% 量级；未近满路径零行为变化有单测把守（任务 4.2）。
- 配置键漏登记致设置页静默丢写——三面登记入交付物 + 写入不丢/非法值拒绝单测把守（任务 3.4 / 4.4）。
- 空子集假通过——空子集回落全量守卫 + 单测把守（任务 3.1 / 4.3）。
