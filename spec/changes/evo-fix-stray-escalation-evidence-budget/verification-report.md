# 验证报告：evo-fix-stray-escalation-evidence-budget

> ⚠️ 本报告由框架于 2026-10-30T13:14:09Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T13:14:07.855307+00:00+run-result@mtime1793366047909049597

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.11M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| size-segment-accident-shape-truncated | R1 体积明细段预算（51054 项事故形态）：「条目体积(字节)」段头部 50 项截断＋「等51054项」注记＋体积合计聚合，段长有界（<5000 字符，事故全量 join 形态约 1.3MB）；合计为注册表全量聚合（200×100=20000）而非前 50 项部分和（回归点：阈值内 ≤50 项输出与既有形态逐字节一致）；空 sizes 字典落「无」占位（空状态）。出处 core/worktree_manager/stray_wip.py:347-368（_evidence_size_manifest 单源）、tests/test_stray_untracked_evidence_budget.py:45-81 | pass | 0/5 | - |
| size-segment-independent-probe | R1 独立探针（不经交付测试文件，直接调实现单源复核）：_evidence_size_manifest 对 51054 项形态输出段长有界（BOUNDED_OK，SEG_LEN 实测 1718 < 5000）、「等51054项」注记（EQN_OK）、体积合计全量聚合（TOTAL_OK）、注册表 sizes_bytes 单源指引在场（REGISTRY_OK）、头部 50 项逐项内联（HEAD_OK）且第 51 项不再内联（TAIL_OK）。出处 core/worktree_manager/stray_wip.py:347-368 | pass | 0/7 | - |
| escalated-evidence-write-side-bounded | R1 写侧集成（升级信号构造）：51054 项 entry 构造 maintree_untracked_stray_escalated 升级信号，evidence 总量有界（<200K 字符；2026-10-24 事故同形态实测 6,667,709 字符），含「等51054项」与 sizes_bytes 单源指引；文件清单段保持头部 50 项截断原样（parse_stray_wip_manifest 写读成对不受影响）。出处 core/worktree_manager/stray_wip.py:2077-2085（_write_untracked_escalated_alert 读 sizes_bytes 注册表 :2093）、tests/test_stray_untracked_evidence_budget.py:88-118 | pass | 0/2 | - |
| manifest-parse-pairing-unchanged | R1 写读成对回归：体积段截断不破坏 manifest 解析——parse_stray_wip_manifest 仍按「文件清单(N):」段解析出头部 50 条（120 项声明→前 50 条），体积段「等120项」注记自成一段不被当作路径拼进清单。出处 core/dashboard/data/admin_stray_wip.py（parse_stray_wip_manifest 消费方）、tests/test_stray_untracked_evidence_budget.py:121-139 | pass | 0/2 | - |
| injection-cap-unit-boundary | R2 注入侧防御性体量上限边界：ADMIN_SIGNAL_EVIDENCE_MAX_CHARS=200000——上限内文本逐字节原样返回（fail-open 不动短信号）；超限截断为恰好上限字符＋「[evidence 已截断：原 N 字符]」注记，且注记段不含占位符字面量（残留扫描告警语义不变）。出处 core/agent_runner/prompt_builder.py:128-150（_bounded_evidence 单源）、tests/test_stray_untracked_evidence_budget.py:145-164 | pass | 0/3 | - |
| injection-cap-accident-shape-prompt-bounded | R2 事故形态注入不撑爆处置提示词：171 万字符级 evidence（51054 项条目体积内联形态）装配 administrator 提示词时超限 fail-open 截断，注入后提示词长度有界（模板＋截断预算＋注记余量）且含截断注记与原字符数；独立探针直接复核 _bounded_evidence（FAT_LEN 实测 1713624 → OUT_LEN 200028 有界、NOTE_OK 注记含原字符数、SMALL_OK 小额文本原样）。截断发生在 _fill_and_scan_placeholders 单趟填充之前（core/agent_runner/prompt_builder.py:556 值装配处、:246 附近单趟语义）、tests/test_stray_untracked_evidence_budget.py:166-188 | pass | 0/6 | - |
| ptl-final-failed-group-reschedules | R3 正向：prompt_too_long/api 400 终态（final failed 处置组，result="failed"）触发限次重派——孤儿巡检把该死亡形态纳入与 interrupted 同型的重派通道：原 run 追加 superseded 审计（reschedule_count=1）、重派产生新 run pending、重派 evidence 瘦身（≤上限＋「已截断」注记）、spec 归属与首次摄取同源（项目名）、限次未用尽无升级。出处 core/admin_monitor.py:6493-6668（_reschedule_prompt_too_long_final_group）、tests/test_stray_untracked_evidence_budget.py:354-396 | pass | 0/2 | - |
| ptl-exhaustion-critical-escalation-no-autoretry | R3 限次用尽出口：reschedule_max=0（额度即尽）→ 不重派，落 severity=critical 的 ESCALATION（signal_type=散件升级类型、spec 归一后 None、evidence 含 prompt_too_long、不带 next_retry_at/retry_count——不进 _retry_due_dispatch_failures 派发失败自动重试扫描）＋escalate=True 终结记录（本组此后豁免，与收敛升级共用 unhandled_for 去重不双升）；再次巡检不重复升级不再重派。出处 core/admin_monitor.py:6594-6668、tests/test_stray_untracked_evidence_budget.py:398-443 | pass | 0/2 | - |
| ptl-daemon-spec-mismatch-reachable | R3 daemon 级 spec 记法失配形态可达（46h 悬空根因修复）：SIGNAL 记录 spec=None＋处置组记录 spec=<项目名>（unhandled_signal_for 严格相等恒不命中的失配形态）下，重派/升级判定经归一口径仍可达并落 critical 升级。出处 core/admin_monitor.py:948-1046（_orphan_signal_query_spec 归一单源）、tests/test_stray_untracked_evidence_budget.py:445-466 | pass | 0/2 | - |
| ptl-non400-death-not-rescheduled | R3 异常路径/边界（防重派烧钱）：非 400 终态（terminal_reason=api_error＋api_error_status=429 瞬态归因形态）不入 prompt_too_long 重派通道——不重派、无 superseded、无升级，回落既有收敛路径。出处 core/admin_monitor.py:1049-1082（_PTL_TERMINAL_REASONS/_result_event_is_prompt_too_long_api400 判定）、tests/test_stray_untracked_evidence_budget.py:468-487 | pass | 0/2 | - |
| ptl-reschedule-cap-counts-across-runs | R3 额度跨 run 累计（多轮交互序列）：reschedule_max=1 时首轮重派 1 次（calls=1）；重派后的新 run 再次死于同签名 → 计数 1+1>1 超限，不再重派、落 critical 升级（无 next_retry_at），计数按 (spec, signal_type) 聚合自洽（防对同一坏信号重派风暴）。出处 core/admin_monitor.py:1724-1726（reschedule_max）、:6064（_reschedule_count_for）、tests/test_stray_untracked_evidence_budget.py:489-514 | pass | 0/2 | - |
| full-contract-suite-green | 整体回归门：交付契约测试文件全量（tests/test_stray_untracked_evidence_budget.py，R1/R2/R3 共 14 条用例）一次全绿，pytest 汇总含「14 passed」——三条需求合同整体通过、无相互回归。出处 tests/test_stray_untracked_evidence_budget.py:1-15（覆盖清单）、实测输出「14 passed, 6 warnings in 0.92s」 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

