# 验证报告：add-maintenance-lane-provider-failover

> ⚠️ 本报告由框架于 2026-11-10T05:51:40Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-10T05:45:58.128695+00:00+run-result@mtime1794289890495707692

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 26/27 场景通过，1 失败，0 错误（1 个真实产品 Bug）**

27 场景：26 pass / 1 fail。唯一失败场景 ring-model-rejected-both-tail-attribution 判 product-bug（major）：拒模型记账判定词表未覆盖 SPEC 验收场景要求的「HTTP 400 + result 字段拒模型正文（Model not found）」形态，_record_unrecognized_model 未被调用（两候选均无 WARNING 记账）；同场景换候选/链尾归因/冷却等功能断言全部通过。确定性证据链（SPEC 锚点 + 词表/调用点源码行）完整，免复现。

| 指标 | 数量 |
| --- | --- |
| 通过 | 26 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 14.50M |
| 本链增量 Token（输出） | 0.15M |


## 真实产品 Bug

### BUG-01（severity=major）· json_output

- 关联场景：ring-model-rejected-both-tail-attribution
- 描述：候选环对「HTTP 400 拒模型正文仅在 result 事件 result 字段」形态不调用 _record_unrecognized_model 记账——SPEC 验收场景（specs/maintenance-lane-provider-failover/spec.md:19-21）THEN 要求记账并换候选；换候选/链尾 [model-chain-unavailable] 归因/双候选 switch 冷却均达成（5/7 断言过），唯拒模型 WARNING 记账缺失（probe-p1/probe-p2 两候选均无 'Unrecognized model rejected'）。
- 根因：拒模型记账判定词表 UNRECOGNIZED_MODEL_TEXT_PATTERNS（core/agent_runner/provider_circuit.py:95-98）仅含 'unrecognized_model'/'unrecognized model' 两形态，未覆盖网关 'Model not found: <model>' 正文形态——该形态仅命中 SWITCH_ERROR_TEXT_PATTERNS 第三条（provider_circuit.py:61）走切换类链前进，runner.py:2568 is_reject 判定不命中 → runner.py:2580-2584 的 _record_unrecognized_model 调用被跳过。
- 证据（场景 ring-model-rejected-both-tail-attribution 结构化证据，引用）：
  - failed_assertions: [{"type": "json_output", "selector": "unrecognized_ledger_warn", "expected": true, "actual": false}, {"type": "json_output", "selector": "unrecognized_ledger_warn_p2", "expected": true, "actual": false}]
  - screenshots: []
  - first_failed_step: 步骤1(probe): 双候选均以 HTTP 400 + result 字段拒模型正文（Model not found）失败后，r.logger 无任何含 'Unrecognized model rejected' 的 warning——is_reject 未命中，_record_unrecognized_model 未被调用；同场景换候选/链尾归因/双冷却 5 断言均通过


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| ring-429-switches-next-candidate | 候选环：双候选链首候选以 429 失败（429 文案仅在 result 事件 api_error_status/result_text，stderr 仅 [claude-code:unrecognized_model] 噪声行）→ 本 run 内换第二候选成功；run jsonl 两条 provider_marker 记录 chain_index=0/1、chain_len=2；首候选进入 300s 限流冷却；换候选决策留有日志痕迹（R1/R2/R5） | pass | 0/15 | - |
| ring-chain-all-cooled-cheap-fail | 候选环：链上全部候选处于 switch/限流冷却 → 不调用 _run_agent、不启动进程，直接以 [model-chain-unavailable] 归因廉价失败（R2/D6） | pass | 0/5 | - |
| ring-4xx-no-switch-reraise | 候选环：首候选以可解析 HTTP 404（配额/鉴权类 4xx）失败 → 不换候选（_run_agent 恰 1 次）、异常原样上抛且 api_error_status=404 保留（R4） | pass | 0/6 | - |
| ring-business-failure-noise-not-switch | 候选环：候选以普通业务异常失败（stderr 含 [claude-code:unrecognized_model] 噪声行但无结构化切换信号）→ 不换候选、原样上抛——噪声行不得作为切换依据（R3）、业务失败不得烧链（R4） | pass | 0/5 | - |
| ring-attempt-cap-terminal-429-attribution | 候选环：三候选链全部以 429 失败 → _run_agent 恰好调用 3 次（候选上限=链长不超出）、终局异常保留 api_error_status=429 且文本含 [model-chain-unavailable] 归因、三候选均进限流冷却（R2/R6/D5） | pass | 0/9 | - |
| ring-post-provider-env-per-candidate | 候选环：post_provider_env 在每候选 provider env 组装（ANTHROPIC_*/provider.env 合并）之后合并——换候选后第二候选的 env 仍含 post 键（如 CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0），provider.env 键亦注入（D7/R7） | pass | 0/8 | - |
| ring-fail-open-without-bookkeeping | 候选环：桩 runner 缺簿记接线（_record_daily_provider_attempt/_write_provider_marker 置 None）→ fail-open 不阻断，双候选 429 换候选仍成功（R7） | pass | 0/6 | - |
| ring-model-rejected-both-tail-attribution | 候选环：双候选均以拒模型正文失败（model not found 仅在 result 事件 result_text）→ 先换第二候选（恰 2 次调用）、每次拒模型记 WARNING 记账（Unrecognized model rejected）、链尾仍被拒时错误文本带 [model-chain-unavailable] 归因（R2/R3） | failed（已修正） | 2/7 | product-bug |
| lane-code-review-dual-chain-failover | code-review 车道：双候选链（agents.models.code-review）首候选 429（结构化 result 事件）→ 本 run 换第二候选成功（_run_agent 2 次、第二次 env 指向第二候选）、provider_marker 记录真实 chain_index=0/1 与 chain_len=2（R1/R5） | pass | 0/10 | - |
| lane-code-review-role-fallback-order | code-review 车道角色回退顺序保留：code-review 角色未配置 → 回退 self-review 链（marker chain_len 如实=1）；再未配置 → 回退 _get_admin_model 默认网关形态（无 ANTHROPIC_BASE_URL、无 marker）（R1） | pass | 0/10 | - |
| lane-administrator-dual-chain-failover | administrator 车道：双候选链首候选 429 → 换第二候选成功（2 次调用、env 指向第二候选）、marker 记录 chain_index=0/1 与 chain_len=2（R1） | pass | 0/9 | - |
| lane-arbiter-pinned-fallback | arbiter 车道：agents.models.arbiter 未配置 → 回退 ARBITER_PINNED_MODEL 常量单次执行、不写 provider_marker、env 无 ANTHROPIC_BASE_URL（R1 链空回退语义） | pass | 0/6 | - |
| lane-self-review-dual-chain-failover | self-review 车道：双候选链首候选 429 → 换第二候选成功、marker 记录真实 chain_index=0/1 与 chain_len=2（R1/R5） | pass | 0/9 | - |
| lane-evolution-unconfigured-status-quo | evolution 车道未配置 agents.models：沿用 _get_admin_model() 回退模型单次执行、env 不注入 ANTHROPIC_BASE_URL/provider env、不写 provider_marker、行为与现状逐字段一致（R1/R7） | pass | 0/7 | - |
| lane-evolution-post-env-per-candidate | evolution 车道双候选换候选后每候选 env 均保持 CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 在 provider env 组装之后注入（顺序不变量 item 4a65f8620c29，D7），且第二候选 ANTHROPIC_BASE_URL/provider.env 正确（链经 self-review 角色解析——SPEC R1，夹具配 agents.models.self-review） | pass | 0/10 | - |
| lane-code-fix-dual-chain-failover | code-fix 车道：双候选链（code-fix 角色）首候选 429 → 换第二候选成功、provider_marker 仍写 spec_name=code-review-fix、agent_type=code-fix 且记录真实 chain_index=0/1 与 chain_len=2（R1/tasks 3.5） | pass | 0/8 | - |
| lane-marker-failopen-stub | 车道 marker 写点 fail-open：runner 缺 _write_provider_marker（替身/精简 runner）→ 配置了链的车道仍正常执行完成、_run_agent 正常调用、不阻断 run 主流程（R7/既有 _write_lane_provider_marker 契约保持） | pass | 0/6 | - |
| judge-spec-review-429-switch-provider-used | spec-review 判官车道：双候选链首候选 429（结构化 result 事件）→ 本 run 换第二候选成功，AgentRunResult.provider_used/model_used 取最终候选（p2），run jsonl 两条 provider_marker 记录 chain_index=0/1、chain_len=2，首候选进 300s 限流冷却（R1/R5） | pass | 0/11 | - |
| judge-dispute-429-switch-provider-used | dispute-judge 判官车道：双候选链首候选 429 → 换第二候选成功、AgentRunResult.provider_used 为第二候选、marker 两条 chain_index=0/1 与 chain_len=2、首候选限流冷却——与 spec-review 镜像同步（R1/R5/D8） | pass | 0/10 | - |
| judge-unconfigured-default-gateway-no-marker | 判官范式车道未配置 agents.models：run_spec_review 与 run_dispute_judge 均走 DEFAULT_GATEWAY_MODEL 默认网关单次执行、不写 provider_marker、AgentRunResult.provider_used=None——两处镜像一致（R1/D8/tasks 2.4） | pass | 0/11 | - |
| judge-mirror-contract-same-ring | 镜像契约：run_spec_review 与 run_dispute_judge 的模型路由/换候选段均经同一候选环 helper（拦截 _run_agent_with_chain_failover 哨兵计数，两方法调用各触发恰 1 次，入参 agent_type 分别为 spec-review/dispute-judge）——MUST 两处同步（D8/tasks 3.9） | pass | 0/7 | - |
| redispatch-intent-carries-chain-info | 429 终局重派意图携带链信息：code-review 车道双候选全链 429 终局 → 重派意图（CodeReviewResult.ratelimit_redispatch）含 chain_len=2 与失败候选（p1/p2），run jsonl 追加 type=ratelimit_redispatch 标注（R6） | pass | 0/7 | - |
| redispatch-rerun-resolves-cooled-chain | 重派复跑按链解析：首候选处于限流冷却期时重新执行链选择 → 直接落第二候选（provider_marker chain_index=1），不固定复用链首；RATELIMIT_REDISPATCH_MAX 仍为 1（R6/重派预算不变） | pass | 0/8 | - |
| reg-new-suite-green | 新增回归套件全绿：tests/test_maintenance_lane_failover.py（tasks 2.3/2.4/3.6/3.9 交付的 helper 单测、六车道回归、判官镜像契约）整文件通过 | pass | 0/2 | - |
| reg-provider-failover-family | 既有 provider failover 家族回归零回退：test_provider_failover / test_provider_circuit / test_transient_backoff / test_run_agent_call_site_arity（_run_agent 5 元解包宽度 AST 守卫）全绿（tasks 5.1；基线 133 passed） | pass | 0/2 | - |
| reg-judge-lane-suites | 判官范式车道既有用例回归零回退：test_spec_review_agent / test_spec_review_gate / test_spec_review_infra_attribution / test_dual_lane_adjudication / test_deliverable_declaration_triage 全绿（tasks 5.1，收口语义不变；基线 144 passed） | pass | 0/2 | - |
| reg-lane-suites | 六条维护车道既有用例回归零回退：test_code_review / test_code_fix / test_admin / test_evolution_bg_wait_ceiling / test_api_stall_disposition / test_daily_self_review 全绿（tasks 5.1，返回值/降级/告警路径不变；基线 550 passed） | pass | 0/2 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

当前稳定场景集共 27 个（第 1 轮）。

- 首轮写入 27 个场景

