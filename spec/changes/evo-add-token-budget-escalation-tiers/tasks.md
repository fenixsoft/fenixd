## Deliverables

```yaml
- path: core/agent_runner/token_budget.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/pm_engine/verification/judge_gate.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/pm_engine/verification/fastlane.py
  kind: modify
- path: tests/test_token_budget_escalation.py
  kind: new
```

## 1. token 预算告警分级

- [x] 1.1 core/agent_runner/token_budget.py：_check_token_budget 新增 ratio>=0.95 的 major 档（独立幂等标志 _token_major_95），发射经 _send_token_alert 传 severity="major"（现有 80%/100% 两档发射保持 warning 不变），major 经 admin_store.HUMAN_SEVERITIES 进人工队列；major 档 recommended_action 列出收敛复验/冻结止损/raise_budget 三个处置选项，保留「告警不自动冻结 spec」语义；major 判定为独立条件（ratio>=0.95 且标志未置位即发射，含 ratio 一步越过 95% 直达 >=100% 的跳变补发），不挂在 ratio>=1.0 分支的 elif 链之下
- [x] 1.2 core/dashboard/data/admin_actions.py：_exec_raise_budget 的幂等标志复位集合改为遍历预算告警标志常量集并把 _token_major_95 纳入，防止预算翻倍后 95% 档告警永久静默

## 2. judge 重跑上限联合判定

- [x] 2.1 core/pm_engine/verification/judge_gate.py：重跑上限计数判定处追加预算联合分支——STATE 条目 _tokens_in 对 agents.token_budget_millions 的 ratio 达到 agents.token_conserve_ratio 阈值（配置启用）时，spec 级剩余可重跑次数压缩为 1、轮内真实派发上限由 2 压缩为 1，冻结/停派文案注明「预算近满」
- [x] 2.2 core/pm_engine/verification/judge_gate.py：预算未近满或配置未启用时判定路径与现状完全一致（零行为回归）

## 3. 预算近满收敛复验

- [x] 3.1 core/pm_engine/verification/pipeline.py：验证计划生成/路径选择点接入预算触发源——新增配置键 agents.token_conserve_ratio（浮点 (0,1]，缺省关闭），ratio 达阈值时下一轮验证切收敛复验，验证报告注明收敛模式与子集范围；收敛报告沿用 fastlane.merge_subset_report 先例并入前次全量报告（子集外场景沿用前次结论）；空子集守卫——无既存失败场景可收（首轮验证/前次全绿后的排程重验）时回落全量口径并落日志，MUST NOT 以空子集出具验证结论
- [x] 3.2 core/pm_engine/verification/fastlane.py：子集重验计算（失败场景 ∪ depends_on 前置链 ∪ 下游场景）抽出供预算触发通道复用的入口；多失败场景按失败集合逐个计算取并集（subset_scenario_ids 现签名为单 failed_id）；预算触发通道独立于 fastlane 原闸门判定（不要求失败场景数=1 / 影响面≤3 文件 / 无争议），fastlane 原路径行为不回归
- [x] 3.3 core/pm_engine/verification/pipeline.py：收敛复验与既有排程重验/场景修订重验通道的优先级仲裁（场景修订重验 > 预算收敛复验 > 全量重跑），仲裁决策落日志
- [x] 3.4 core/dashboard/data/config_admin.py：agents.token_conserve_ratio 按受管 agents 键三面登记（user 缺省登记、_AGENTS_SOURCE_KEYS 来源/回显、缺省回显段），并按 (0,1] 浮点做前置校验（非法值拒绝不落盘，同 token_budget_millions 校验范式）——漏登记时设置页提交被 _deep_merge_managed 静默丢弃（config_admin.py 内 impl_run_budget_max 同款先例注释）

## 4. 测试

- [ ] 4.1 tests/test_token_budget_escalation.py：95% major 档触发与幂等（同比例只发一次、进人工 severity）、跳变越过 95% 直达 >=100% 时 major 补发、80%/100% 两档旧行为不回归、「告警不自动冻结」语义保持、_exec_raise_budget 复位含新标志（翻倍后可再次触发）
- [ ] 4.2 tests/test_token_budget_escalation.py：judge 联合判定——近满且配置启用时剩余重跑压 1/轮内停派提前/文案注明预算近满，未近满或未配置时零行为变化
- [ ] 4.3 tests/test_token_budget_escalation.py：收敛复验触发（达阈值切子集、子集=失败 ∪ 前置链 ∪ 下游且多失败取并集、报告为 merge_subset_report 合并态并注明模式）、空子集回落全量且不以空子集出结论、缺省关闭语义、与场景修订重验/排程重验的优先级仲裁
- [ ] 4.4 tests/test_token_budget_escalation.py：agents.token_conserve_ratio 设置页写入不丢失（_deep_merge_managed 透传、来源标注与回显非 undefined）、非法值（越界/非数值/bool）拒绝不落盘
