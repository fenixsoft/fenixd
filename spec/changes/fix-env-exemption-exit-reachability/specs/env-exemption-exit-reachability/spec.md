# env-exemption-exit-reachability 规格

## ADDED Requirements

### Requirement: 级二握手首次命中即升级

env 豁免握手（`_handle_env_exemption_handshake` 级二命中：judge 裁决后验证失败全部归类 env）在**首次**命中时 MUST：

1. 写 inconclusive_loop SIGNAL 到 admin store（signal_type 与既有 B7 一致，保住 `latest_resolved_disposition(spec, "inconclusive_loop")` 放行查询锚点）；
2. 经 `escalation_notifier` 发 human-escalation-alert（severity=major，choices 由注册表按 signal_type 自动附加）；
3. spec 停在 implemented、`tester_run` 清空、写 error 说明等待人工裁决，**不再 enqueue verifier 自动重验**；
4. SIGNAL/告警 evidence MUST 含本轮失败签名摘要与 `_inconclusive_attempts` 当前值。

自动重验轮数计数停止增长；人工经 choices 处置是唯一出路（与「豁免不得自我批准」语义闭环）。

#### Scenario: 首次级二命中直接转人工不重验

- **WHEN** judge 裁决 verified（bugs=0）且全部失败归类 env（env 断言 N 条 + blocked-env 场景 M 个），AdminStore 无放行处置记录
- **THEN** 写入 inconclusive_loop SIGNAL 一条 + human-escalation-alert 一条（choices 含 grant_env_exemption/manual_fixed_reverify/abandon）
- **AND** spec 状态为 implemented、无 verifier 入队、`_inconclusive_attempts` = 1 不再递增

#### Scenario: 授予豁免后放行

- **WHEN** 人工对上述告警选择 grant_env_exemption
- **THEN** AdminStore 落 kind=DISPOSITION 记录（signal_type=inconclusive_loop、result 指向放行、created 晚于 SIGNAL）
- **AND** 验证链重置重验后 judge 再判全 env verified 时，握手守卫查得放行记录且时效校验通过 → 放行走既有 verified 链，报告带 `admin_disposition_backlink`

### Requirement: 级一失败签名一致提前升级

`_handle_env_blocked_inconclusive`（summary.blocked_env > 0 且 failed+errors = 0 的环境性失联）保留自动重验，但：

- 重验上限改由 `verify_engine.inconclusive_max_attempts` 配置（缺省 **2**）；
- 本轮失败场景集 + 各场景失败签名（归一化，同 `_normalize_fail_signature` 口径：数字→N、去引号、折叠空白）与上一轮签名基准完全一致时，**不等计数到顶立即升级**（写 inconclusive_loop SIGNAL + 人工告警），停止自动重验。基准由上一轮 inconclusive 处置点回写的 spec STATE 字段 `_last_inconclusive_signature` 承载（MUST NOT 以 `fail_history.json` 为基准：其条目仅存场景 id 集且仅在归因失败轮追加、inconclusive 轮不落台账）；基准缺失（首轮/重置后）按首轮处理，不提前升级。blocked-env 场景从未执行、无失败断言，其签名退化为「场景 id 集 + blocked 计数」。

#### Scenario: 签名一致跳过剩余重验

- **WHEN** 第 1 次重验后 blocked-env 场景集与签名和上一轮完全一致
- **THEN** 不再入队第 2 次重验，直接写 SIGNAL + 人工告警，spec 停止自动重验

#### Scenario: 签名变化继续自愈重试

- **WHEN** 本轮 blocked-env 场景集或任一签名与上一轮不同（环境部分恢复/新失败形态）
- **AND** 未达重验上限
- **THEN** 按既有路径入队重验，不升级

### Requirement: judge 生命周期预算隔离

握手进入 inconclusive 处置时 MUST 置 STATE 旗标 `_in_inconclusive_reverify=True`；`_judge_dispatch_gate` 读到旗标时：

- 本次派发计入 `_judge_inconclusive_dispatches`（独立计数器，上限 = `inconclusive_max_attempts` 配置值，到顶升级复用 `_judge_round_escalate` 同款人工升级）；
- **不递增** `_judge_rerun_count`。

旗标清除点：judge 申报结论非全 env（bug-found / verified 放行 / scenario-repaired 等正常路由恢复）时清除并恢复正计；verified 落定时 `_judge_inconclusive_dispatches` 与 `_judge_rerun_count` 一并清零；人工 reset_verification 清零清单包含新计数器与旗标。

#### Scenario: 重验轮不烧生命周期预算

- **WHEN** `_judge_rerun_count` 已为 4，旗标置位后的重验轮进入 judge gate
- **THEN** `_judge_rerun_count` 保持 4，`_judge_inconclusive_dispatches` +1，judge 正常派发，不触发 judge_rerun_cap 冻结

#### Scenario: verified 落定双计数器清零

- **WHEN** 验证通过落定 verified
- **THEN** `_judge_rerun_count`、`_judge_inconclusive_dispatches`、`_in_inconclusive_reverify` 全部清零/清除

### Requirement: inconclusive_loop 裁决选项注册

`ADJUDICATION_CHOICES` 注册表 MUST 注册 `inconclusive_loop` 信号选项集（按序）：

1. `grant_env_exemption`——「授予 env 豁免」：写 DISPOSITION 放行记录（result 显式指向 env 豁免放行、note 落审计）+ 重置验证重跑；执行器在 `execute_adjudication_choice` 映射实现；
2. `manual_fixed_reverify`——「人工已修环境·重置重验」：复用既有 reset_verification 动作；
3. `abandon`——「撤销丢弃」（destructive，复用共享选项）。
4. 一键处置可达性 MUST：`VERIFY_CHAIN_SIGNAL_TYPES` 追加 `inconclusive_loop`，且 `reset_verification` 前置状态门放行本能力域停车形态（`implemented` + `_inconclusive_attempts`>0 + inconclusive 停车 error 文案特征）——现门禁仅放行 frozen/blocked，不扩展则 `grant_env_exemption` / `manual_fixed_reverify` 在前置校验即被拒绝，选项集接线形同虚设。

#### Scenario: 选项集接线生效

- **WHEN** inconclusive_loop 人工告警落盘
- **THEN** 告警记录 choices 快照为上述三项（order 一致），alert-resolve 端点对 choice_id=grant_env_exemption 执行 DISPOSITION 落库 + 验证重置，返回 steps 含放行记录 id
