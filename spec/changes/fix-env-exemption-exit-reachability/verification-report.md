# 验证报告：fix-env-exemption-exit-reachability

> ⚠️ 本报告由框架于 2026-10-03T17:45:00Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-03T17:45:00.075767+00:00+run-result@mtime1791049500107179922

## 结论：✅ 通过（verified）

**状态：verified — 20/20 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 20/20 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 20 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.40M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| lvl2-first-hit-escalates-no-requeue | 级二握手首次命中即升级：judge 裁决 verified（bugs=0）且全部失败归类 env 后首次命中，写 inconclusive_loop SIGNAL 一条 + human-escalation-alert 一条（choices 含 grant_env_exemption/manual_fixed_reverify/abandon），不再入队 verifier 自动重验，_inconclusive_attempts 停在 1 不递增（spec.md Scenario: 首次级二命中直接转人工不重验；实现 core/pm_engine/verification/escalation.py:1792 _handle_verdict_env_exemption_inconclusive 首次命中即走 _escalate_inconclusive_parking，无 enqueue） | pass | 0/4 | - |
| lvl2-parking-form-no-freeze-prefix | 级二升级停车形态：spec 停 implemented、tester_run 清空、error 写等待人工裁决文案且不含 FREEZE_ERROR_PREFIX 冻结前缀（人工经 choices 解锁不走 unfreeze 通道）、_dispatch_backoff_until 置退避防 orphaned_state 误报（design.md D5；实现 escalation.py:177 _escalate_inconclusive_parking updates 段 L249-268、INCONCLUSIVE_PARKING_ERROR_MARKER=等待人工豁免或修环境裁决 escalation.py:116） | pass | 0/4 | - |
| lvl2-evidence-carries-signature-and-attempts | SIGNAL 与人工告警 evidence 含本轮失败签名摘要（场景 id 集 + 归一化签名：数字→N、去引号、折叠空白）与 _inconclusive_attempts 当前值（spec.md Requirement 1 第 4 条；实现 escalation.py:110 _inconclusive_fail_signature + L232-234 evidence 组装 签名摘要=…；签名期望形态经实测确认） | pass | 0/6 | - |
| lvl1-same-signature-early-escalate | 级一 blocked-env 签名一致提前升级：本轮 blocked 场景集与签名和上一轮基准（STATE._last_inconclusive_signature）完全一致时，不等计数到顶直接写 SIGNAL + 人工告警，不再入队第 2 次重验（spec.md Scenario: 签名一致跳过剩余重验；实现 escalation.py:364-392 提前升级分支） | pass | 0/2 | - |
| lvl1-changed-signature-continues-reverify | 级一签名变化继续自愈重试：本轮 blocked-env 场景集或任一签名与上一轮不同（环境部分恢复/新失败形态）且未达重验上限时，按既有路径入队 verifier 重验、不升级（spec.md Scenario: 签名变化继续自愈重试；实现 escalation.py:414-444 attempts<max 分支回 implemented+enqueue） | pass | 0/2 | - |
| lvl1-missing-baseline-conservative | 级一基准缺失保守处理：_last_inconclusive_signature 缺失/不可解析（首轮/重置后）按上一轮签名未知处理，不提前升级、保守走计数上限；比较基准 MUST NOT 以 fail_history.json 为基准（design.md D2、tasks 2.2；实现 escalation.py:370-371 两侧非空且完全一致才提前升级） | pass | 0/2 | - |
| lvl1-default-max-attempts-two | 级一重验上限缺省为 2：verify_engine.inconclusive_max_attempts 未配置时 escalation.py 两处读取点与 judge_gate.py 一处读取点缺省值一致为 2（tasks 2.1/3.3 防同键缺省漂移；实现 escalation.py:357、escalation.py:1366、judge_gate.py:344） | pass | 0/4 | - |
| judge-gate-counter-split-while-flag-set | judge 预算隔离分流：_judge_rerun_count 已近上限且 _in_inconclusive_reverify 旗标置位时 gate 递增 _judge_inconclusive_dispatches 且 _judge_rerun_count 保持不变，judge 正常派发、不触发 judge_rerun_cap 冻结；旗标未置时既有生命周期计数语义零变化（spec.md Scenario: 重验轮不烧生命周期预算；实现 judge_gate.py:342-355 分流） | pass | 0/4 | - |
| judge-gate-independent-counter-cap-escalates | 独立计数器到顶升级：_judge_inconclusive_dispatches 达上限（= verify_engine.inconclusive_max_attempts 配置值）时复用 _judge_round_escalate 同款人工升级停车、不冻结（spec.md Requirement 3；实现 judge_gate.py:346-349 + _judge_inconclusive_cap_escalate judge_gate.py:480） | pass | 0/2 | - |
| non-env-verdict-clears-flag-resumes-counting | 非全 env 结论清旗标恢复正计：judge 申报 bug-found / verified 放行 / scenario-repaired 等结论时经单一收口助手 _clear_inconclusive_reverify_flag 清除旗标（pipeline 绑定三调用点）并恢复 _judge_rerun_count 正计（spec.md Requirement 3 旗标清除点；实现 escalation.py:278 + pipeline.py:1027/1221/1593） | pass | 0/4 | - |
| verified-settle-clears-three-fields | verified 落定三字段清零：_judge_rerun_count、_judge_inconclusive_dispatches、_in_inconclusive_reverify 一并清零/清除（verdict_evidence 既有清零点扩展，spec.md Scenario: verified 落定双计数器清零） | pass | 0/4 | - |
| reset-verification-clears-new-fields | 人工 reset_verification 清零清单追加 _judge_inconclusive_dispatches、_in_inconclusive_reverify、_last_inconclusive_signature、_dispatch_backoff_until（tasks 3.4） | pass | 0/4 | - |
| choices-registry-three-options-runtime | ADJUDICATION_CHOICES 注册 inconclusive_loop 选项集且按序为 grant_env_exemption/manual_fixed_reverify/abandon，消费通道为 ESCALATION 不入 SIGNAL_CHANNEL_SIGNAL_TYPES（运行时导入注册表断言，tasks 4.1） | pass | 0/2 | - |
| grant-env-exemption-disposition-and-reset | grant_env_exemption 执行器：execute_adjudication_choice 执行后 AdminStore 落 kind=DISPOSITION（signal_type=inconclusive_loop、result 显式放行语义、note 落人工审计文本、created 晚于 SIGNAL）+ 验证链重置重验，返回 steps 含放行记录 id（spec.md Scenario: 授予豁免后放行） | pass | 0/4 | - |
| grant-env-exemption-fail-closed-no-reset | DISPOSITION 写失败时 fail-closed：grant_env_exemption 不执行验证重置，防「重置了却没放行」死循环复发（tasks 4.2） | pass | 0/2 | - |
| reset-gate-allows-parking-form | reset_verification 前置门兼容扩展：VERIFY_CHAIN_SIGNAL_TYPES 含 inconclusive_loop，且 implemented + _inconclusive_attempts>0 + inconclusive 停车 error 文案的停车形态可通过前置校验一键处置（不被「spec 未处于冻结/blocked 态」拒绝）（tasks 4.5） | pass | 0/2 | - |
| handshake-guard-fresh-disposition-backlink | 握手守卫放行链路：AdminStore 查得新鲜（created 晚于 SIGNAL、通过 _env_exempt_disposition_is_stale 时效校验）放行 DISPOSITION 后，judge 再判全 env verified 合法放行走既有 verified 链且报告带 admin_disposition_backlink（spec.md Scenario: 授予豁免后放行 AND 条） | pass | 0/6 | - |
| governance-help-doc-choices | 帮助文档裁决选项段含 inconclusive_loop 三选项语义与授予豁免后 verified 链路说明（docs/help/06-governance.md 交付物 L298-310；GET /api/help/doc?name=06-governance.md，出处 core/dashboard/routes/base.py:565 + core/dashboard/routes/help_routes.py:90-119） | pass | 0/7 | - |
| handshake-legacy-tests-updated-pass | 既有握手测试回归通过：tests/test_verify_env_handshake.py 中断言级二旧自动重验时序的用例已更新为新语义（test_mixed_form_all_env_assertions_first_hit_parks 取代旧 requeues 命名）且全文件 20 用例通过（tasks 5.4） | pass | 0/3 | - |
| new-tests-full-suite-pass | 新建配套测试全量通过：tests/test_env_exemption_exit_reachability.py 收集无错误、假 notifier/store 注入（_FakeLogger + MagicMock）不真调网关、全部 15 用例通过（tasks 5.1-5.3） | pass | 0/5 | - |
