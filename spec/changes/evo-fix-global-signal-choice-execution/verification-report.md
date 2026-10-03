# 验证报告：evo-fix-global-signal-choice-execution

> ⚠️ 本报告由框架于 2026-10-03T19:34:27Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-03T19:34:27.384141+00:00+run-result@mtime1791056067430280128

## 结论：✅ 通过（verified）

**状态：verified — 15/15 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 15/15 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 5.92M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| registry-scope-declaration | 注册表作用域声明（1.1+1.3）：9 个信号桶全部裁决选项逐项显式声明 spec_scoped 字段且同信号内 id 唯一，retry_review/force_advance/abandon/skip_review_gate/reset_verification/continue_auto_fix/grant_env_exemption/revise_reproposal/freeze_stop_loss 均为 True，ignore/raise_budget/open_config/declare_no_artifacts/ack_self_heal 均为 False，非作用域动作至少存在（全局信号收口不断路）；is_global_spec 对 None/空白串/global 及其大小写空白变体判真、对具体 spec 名与 globalize 判假。出处 spec adjudication-choice-scope-guard「全局信号处置路由防护」；core/dashboard/data/adjudication_choices.py:40-46,81-88,295-336 | pass | 0/2 | - |
| executor-global-forms-reject-scoped-choice | 执行器全局守卫（1.2）：spec=None/空串/占位 'global' 三种全局形态 x retry_review（注册桶 spec-review-incomplete 内合法选项）均被 execute_adjudication_choice 拒绝执行——ok=False、error 含「全局信号」明确文案、action=retry_review、steps 为空（不触碰任何 spec 状态机）。出处 spec「全局信号选到 spec 作用域动作」；core/dashboard/data/admin_actions.py:2254-2262 | pass | 0/2 | - |
| executor-unregistered-signal-no-reverse-lookup | 反查收紧（1.1）：未注册 signal_type=daemon_errors x spec_scoped 动作 retry_review 被拒绝且 error 含「全表反查」（不再跨信号兜底放行），resolve_choice 返回 (None,'scoped-no-reverse')；非作用域动作 ack_self_heal 对未注册信号仍经全表反查可达（返回拷贝、spec_scoped=False）；解析序其余分支照旧——注册桶内未命中返回 not-in-bucket、全表无此 id 返回 unknown-choice、桶内精确命中返回动作映射。出处 spec「未注册 signal_type 不再全表反查放行」；core/dashboard/data/admin_actions.py:2234-2250、core/dashboard/data/adjudication_choices.py:304-336 | pass | 0/2 | - |
| executor-nonscoped-choice-executes-on-global | 非作用域动作对全局信号不受限（1.3）：ack_self_heal x spec='global'（未注册 daemon_errors，经全表反查）执行成功且 action=ack_self_heal、steps 非空；ignore x spec=None（token_budget 桶）与 open_config x spec='GLOBAL'（大小写变体，build_artifact_paths_missing 桶）同样执行成功——全局信号保留可用动作、执行收口不断路。出处 spec「过滤后仍有可用动作」；core/dashboard/data/admin_actions.py:2293-2308、core/dashboard/data/adjudication_choices.py:81-88 | pass | 0/2 | - |
| executor-guard-no-false-positive-real-spec | 守卫不误伤合法路径（对照）：注册桶 spec-review-incomplete 内 retry_review x 真实冻结 spec（spec-review-incomplete 形态的 blocked+冻结 STATE.md 夹具）照常执行成功——作用域守卫只拦全局形态，不回退 spec 作用域信号的既有处置流程。出处 spec 非目标「不改变 spec 作用域信号的既有处置流程」；tests/test_global_signal_choice_guard.py:186-194 | pass | 0/2 | - |
| consumer-apply-choice-global-skip-probe | 消费端跳过留痕（2.1）：真实 AdminMonitor._apply_choice_execution 直驱——全局信号（daemon_errors x spec='global'）x retry_review 返回 {ok:False, skipped:True, action:'retry_review'} 且 error 含「全局信号」，logger INFO 含「跳过执行」与动作名；对照 ack_self_heal（非作用域）同通道执行返回 ok=True 非 skipped——消费端一层先拦、执行器一层兜底的双层设防不破坏非作用域收口。出处 spec「全局信号选到 spec 作用域动作」；core/admin_monitor.py:5144-5190 | pass | 0/2 | - |
| consumer-global-skip-writeback-regression | 消费端守卫与回写纠偏回归（2.1+2.2 全链）：TestConsumerGlobalSkipAndWriteback 四态——全局信号 x retry_review 跳过后信号不置 handled、告警记录 result=failed、action_taken=retry_review、INFO 留痕、DISPOSITION 记录 error 含「choice 执行未生效」；ack_self_heal 成功闭环带 action_taken/result 留痕；非法 choice_id（执行失败）同样 result=failed 不闭环且 DISPOSITION error 含「非法 choice_id」。出处 spec「失败不回写 resolved」「执行结果留痕」；tests/test_global_signal_choice_guard.py:200-274 | pass | 0/4 | - |
| store-mark-signal-handled-trace-probe | 留痕与闭环解耦契约（2.3）：mark_signal_handled(handled=False) 只写 action_taken/result 不置 handled/handled_at（失败路径信号保留待重审）；成功路径闭环+留痕一体；缺省调用（仅 alert_id）行为与历史一致——置 handled、不写留痕字段、已处理幂等返回 False；既有语义不放宽——ESCALATION 记录不经本方法闭环（返回 False）。出处 spec「执行结果留痕」；core/admin_store.py:584-619 | pass | 0/2 | - |
| adjudication-choices-suite-regression | 既有裁决套件回归（验收 3）：tests/test_adjudication_choices.py 全量通过——注册表结构、AdminStore choices 快照、发射点接线、执行器（含本轮新增全局信号跳过/非作用域执行用例）、人工 alert-resolve 端点防护（非法 choice 400 带合法集、跨信号拒绝、重复处置 409、动作失败不标记 handled、未知告警/项目 404）不回退。出处 proposal 验收第 3 条；tests/test_adjudication_choices.py | pass | 0/4 | - |
| disposition-preprobe-reschedule-regression | 处置链邻接回归（验收 3）：tests/test_admin_disposition_failure_context.py、tests/test_signal_preprobe_handled_writeback.py（其 TestFinalDispositionWriteback 直接覆盖被 2.2 调整的终态回写门——escalate 不回写/pending 不回写/success 回写 handled/回写失败不阻塞）、tests/test_admin_disposition_reschedule.py 全量通过——回写序调整不破坏既有处置收尾主路径与预探写回逻辑。出处 proposal 验收第 3 条、design 风险第 1 条；tests/test_signal_preprobe_handled_writeback.py:340 附近 | pass | 0/3 | - |
| e2e-seed-global-form-alert-records | 端到端供数：经 AdminStore 向被测实例（project=fenixd，即验证树自身）落两条全局形态（spec 为空串）ESCALATION 告警——e2e-global-retry-review-guard（spec-review-incomplete 桶，choices 快照 3 项含 retry_review）与 e2e-global-ack-selfheal-close（build_artifact_paths_missing 桶，choices 快照 3 项含 ack_self_heal），fixed id 供后续 api 场景按 id 寻址，读回校验落地形态与未处理态。出处 spec「全局信号选到 spec 作用域动作」「过滤后仍有可用动作」；core/admin_store.py:107-118,448-456 | pass | 0/3 | - |
| e2e-manual-resolve-global-scoped-rejected-400 | 端到端·人工通道 x 全局信号 x spec 作用域动作被拒：GET /api/projects 确定被测实例项目面（含 fenixd，确定性前查），随后 POST /api/alert-resolve（project=fenixd, alert_id=e2e-global-retry-review-guard, choice_id=retry_review）——choice 落在记录 choices 快照合法集内、执行器守卫拒全局形态，端点回 400 且响应体回带动作名（告警保持未处理可重试裁决）。出处 spec「全局信号选到 spec 作用域动作」；core/dashboard/routes/alert_routes.py:446-466、core/dashboard/data/admin_actions.py:2258-2262 | pass | 0/4 | - |
| e2e-manual-ack-self-heal-global-closes-200 | 端到端·全局信号非作用域收口不断路：POST /api/alert-resolve（project=fenixd, alert_id=e2e-global-ack-selfheal-close, choice_id=ack_self_heal）——非作用域动作对全局形态不受限，执行成功回 200，响应 ok=true、action=ack_self_heal、marked=true（ESCALATION 经 mark_handled 闭环）。出处 spec「过滤后仍有可用动作」；core/dashboard/routes/alert_routes.py:468-526、core/dashboard/data/admin_actions.py:2296-2302 | pass | 0/4 | - |
| e2e-rejected-global-alert-stays-unhandled | 端到端·被拒信号保留待重审：POST 被拒（400）后读回 .fenix/admin_alerts.json——e2e-global-retry-review-guard 仍 handled=False、handled_at 空、action_taken/result 为空（人工通道失败路径不标记 handled 也不写留痕，信号可重新处置），与验收「执行被跳过/拒绝，信号终态非 resolved」对账。出处 proposal 验收第 1 条；core/dashboard/routes/alert_routes.py:459-466 | pass | 0/2 | - |
| e2e-ack-self-heal-alert-marked-handled | 端到端·非作用域收口闭环读回：读回 .fenix/admin_alerts.json——e2e-global-ack-selfheal-close 已 handled=True 且 handled_at 落值（全局信号不滞留 pending 无路可走）；action_taken/result 保持空（人工端点为非目标、mark_signal_handled 缺省调用不写留痕字段——2.3 向后兼容约束的端点级回归锚点）。出处 spec 非目标「不修改人工端点既有防护行为」、design 决策 4；core/admin_store.py:599-600 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 15 个（第 1 轮）。

- 首轮写入 15 个场景

