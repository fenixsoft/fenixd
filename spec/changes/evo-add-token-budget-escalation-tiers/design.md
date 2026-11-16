# add-token-budget-escalation-tiers 设计

## 现状锚点（已回源核实）

- core/agent_runner/token_budget.py：_check_token_budget 现有两档分支（ratio>=1.0 与 ratio>=0.8），发射点 severity 硬编码 "warning"；_send_token_alert 已有 severity 形参；幂等标志 _token_warn_80/_token_alert_100；docstring 记录 2026-09-01 降噪决策（两档均警告、不自动冻结）。
- core/admin_store.py:100：HUMAN_SEVERITIES = ("critical", "major")——major 告警天然进人工队列，本能力零改动复用。
- core/dashboard/data/admin_actions.py:2368 _exec_raise_budget：现只复位 _token_warn_80/_token_alert_100 两标志。
- core/pm_engine/verification/judge_gate.py:46 _MAX_JUDGE_RERUNS=5（spec 级）、:53 轮内真实派发阈值=2、超限冻结判定在计数分支；同函数已有读 STATE 条目字段惯例。
- core/pm_engine/verification/fastlane.py:364 子集计算（失败场景 ∪ depends_on 前置链递归 ∪ 下游）、:500 evaluate_fastlane；调用点 core/pm_engine/verification/pipeline.py:1376；fastlane 现闸门只挂 bug-found 路径。

## 设计决策

1. 95% major 档用独立幂等标志 _token_major_95，不复用 _token_warn_80（触发时机与复位语义不同）；发射直接传 severity="major"，admin_store 零改动。
2. raise_budget 复位清单改为遍历预算告警幂等标志常量集（新档加入常量集）——消除「加档忘复位」的重复隐患（本例中若 95% 档先于翻倍存在，翻倍后即永久静默）。
3. judge 联合判定做「额度压缩」而非「预算面直接冻结」：预算近满是升级信号，冻结仍由计数触顶或人工裁决触发——与「告警不自动冻结 spec」决策保持同向，制动经由既有硬闸（judge_rerun_cap）的额度收缩实现，语义是「预算近满时判定面主动省着用」。
4. 收敛切换阈值独立配置且缺省关闭：收敛复验减少子集外场景的覆盖，是治理取舍而非纯收益；默认不改行为，启用是显式项目决策。触发源挂在验证计划生成/路径选择处（pipeline.py:1376 一带），复用 fastlane 子集计算但独立于 fastlane 闸门（预算触发通道不要求 1 失败/≤3 文件）。
5. 通道优先级仲裁集中在 pipeline 判定点：场景修订重验 > 预算收敛复验 > 全量重跑/排程重验全量口径；仲裁决策落日志，验证报告注明收敛模式与子集范围——judge 与人工裁决需要知道本轮不是全量。

## 风险与缓解

- 收敛复验漏回归面（子集外场景回归未被发现）——以阈值缺省关闭 + major 档人工处置链兜底；报告注明模式与范围，裁决可要求回到全量。
- 新档幂等标志漏复位致永久静默——复位集合常量化 + 单测把守（任务 1.2 / 4.1）。
- judge 额度压缩过早导致验证不充分——压缩仅在 ratio>=近满阈值时生效，且近满本身已是 95% 量级；未近满路径零行为变化有单测把守（任务 4.2）。