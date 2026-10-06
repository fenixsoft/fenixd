# 验证报告：evo-add-knowledge-audit-escalation-consumption

> ⚠️ 本报告由框架于 2026-10-02T19:26:04Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-02T19:26:03.477380+00:00+run-result@mtime1790969163513194597

## 结论：✅ 通过（verified）

**状态：verified — 15/15 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 15/15 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.23M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| escalated-budget-exempt-new-candidate-dispatched | R1 语义车道解冻·实驱动：临时夹具项目 11 对矛盾候选（总量 11 > MAX_SEMANTIC_RUNS=10），其中 10 条 escalated 在册（复刻旧实现占满全部转写槽的饱和形态），跑 run_audit 后唯一新候选当日仍被转写派发（dispatched=1 且派发的正是新候选「主题00」而非 escalated 疑点）、新候选当日入账判 exempt（verdicts=1）、escalated 挂起态零触碰（status/verdicts/review_rounds 原样）、零改动+零龄期零提交（出处：core/knowledge_audit.py:1086-1110 切片前按台账 escalated 指纹剔除、:65 MAX_SEMANTIC_RUNS、tests/test_knowledge_audit_escalation_governance.py:165 同款装配） | pass | 0/9 | - |
| pytest-escalation-governance-suite-green | 交付测试套件守卫：tests/test_knowledge_audit_escalation_governance.py 全量 11 条用例 pytest -v --tb=short 通过（占槽豁免/报告聚合/todo 聚合行 upsert/注记写入摘除/150 行硬顶/marker 不劫持/配置覆盖回退/白名单缺省/仲裁当日消费闭环/脏输入防御/零写零提交），exit_code=0 且输出含「11 passed」、无 FAILED/ERROR（出处：tasks.md Deliverables 第 4 项新增测试文件；注意 -v 与 -q 不可并列，须保留 PASSED 输出形态） | pass | 0/4 | - |
| report-escalated-aggregate-single-summary | R2 体检报告聚合·实驱动：2 条 9 龄期 + 1 条 3 龄期 escalated 在册跑 run_audit，报告恰 1 个「## 升级待人工（escalated）汇总」节、含「共 3 条待人工仲裁」与「最长龄期 9 天」（自 first_seen 起算）并指向 knowledge_audit_arbitration.json 唯一人工入口；counts.pending_manual 折叠为 1 而非逐条 3；旧逐条展开形态（「：升级待人工（escalated），已停止自动复核」）不再出现（出处：core/knowledge_audit.py:1108-1112 循环外聚合、:1520-1526 _render_report 汇总节、tests/test_knowledge_audit_escalation_governance.py:199） | pass | 0/7 | - |
| todo-aggregate-row-upsert-replace-not-append | R2 todo 聚合行 upsert·实驱动：预置历史逐条登记行后跑 run_audit 清理为恰 1 条聚合行（前缀「- audit 疑点升级待人工（聚合）：1 条待人工仲裁（最长龄期 3 天）」且指向仲裁清单路径）；first_seen 推进到 9 天前再跑仍 1 行且龄期更新为 9 天（同前缀整行替换非追加，聚合行不变成每日重述）；台账 escalated 清零后再跑聚合行被摘除、报告不再出汇总节（空状态自愈）（出处：core/knowledge_backfill.py:190-233 upsert_todo_line、core/knowledge_audit.py:241-253 聚合行、:1361-1367 循环后单次登记，tests/test_knowledge_audit_escalation_governance.py:223） | pass | 0/8 | - |
| knowledge-audit-clean-state-zero-escalated | 空状态回归·实驱动：全新知识库（台账无任何 escalated）跑 run_audit——报告无「升级待人工（escalated）汇总」节、todo 无聚合行、知识页无 disputed 注记、仲裁清单文件不被创建、零提交；唯一新矛盾候选正常转写并以 exempt 入账（零改动判无矛盾），车道在无积压时零额外动作（出处：core/knowledge_audit.py:241-243 空 escalated 返回空串、:1521 汇总节仅在有积压时输出、:1371-1396 注记同步零期望态零写） | pass | 0/7 | - |
| disputed-annotation-write-selfcommit-clean-tree | R3 超龄注记写入·实驱动：escalated 挂 8 天（> 缺省阈值 7）跑 run_audit，涉事两页顶部（H1 与既有 knowledge marker 之后、独立成行）出现机器可读注记 <!-- disputed: since=... fps=<指纹前 8 位> -->，不含 knowledge: 前缀、不引用 spec/archive 路径（marker 三红线之二）；写入走既有 [fenix] knowledge 提交路径自提交（提交主题含 disputed），spec/knowledge 工作区零残留（不成为下一轮 carryover 告警源）（出处：core/knowledge_audit.py:255-281 注记行格式、:293-344 _sync_disputed_annotations、:1371-1396 写入+自提交、tests/test_knowledge_audit_escalation_governance.py:263） | pass | 0/4 | - |
| disputed-annotation-removed-when-entry-leaves-escalated | R3 注记摘除·回归点：先以 8 龄期 escalated 跑体检写入注记（写入期断言），条目转出 escalated（改判 exempt）后再跑体检——两页 <!-- disputed: 注记被摘除，摘除同走 [fenix] knowledge 提交路径自提交（log 中 disputed 主题提交 ≥2 次：写入+摘除），工作区仍零残留（出处：core/knowledge_audit.py:293-344 摘除分支（desired 空集 × 页并集）、:1393 提交路径，tests/test_knowledge_audit_escalation_governance.py:263 第二段） | pass | 0/5 | - |
| disputed-annotation-line-cap-skip-traced | R3 150 行硬顶红线·实驱动：手工构造恰 150 行（=LINE_CAP）知识页 gamma.md 并种超龄 escalated 指向该页，跑 run_audit——写注记需 +1 行越顶故跳过：页顶无注记、报告留痕「disputed 注记写入跳过」且含页名 gamma.md（出处：core/knowledge_audit.py:60 LINE_CAP=150、:1376-1386 写前查行数+留痕、tests/test_knowledge_audit_escalation_governance.py:297） | pass | 0/5 | - |
| disputed-annotation-not-hijack-knowledge-marker | R3 marker 三红线之一（不劫持解析）·实驱动：8 龄期 escalated 写入 disputed 注记后，ka._parse_marker 仍取首个 knowledge: marker 本体（capability=p00a / rev=1 / sources=arc-good 不受 disputed 行影响），_MARKER_RE 首匹配含 capability= 且不含 disputed——注记无 knowledge: 前缀天然不冲突（出处：core/knowledge_audit.py:83-85 _DISPUTED_RE 设计、:555 _parse_marker、core/knowledge.py:156-197 parse_marker 取首匹配，tests/test_knowledge_audit_escalation_governance.py:332） | pass | 0/7 | - |
| escalated-stale-days-config-override-fallback-whitelist | R3 阈值配置·实驱动：knowledge.escalated_stale_days=3 时 4 龄期 escalated 即注记（覆盖生效）；非法值（字符串 '3'）回退缺省 7 → 4 龄期不注记（摘除注记重跑验证回退口径）；ConfigLoader.get_knowledge_lane_config 白名单挑键：空配置缺省 7、正整数 3 覆盖生效、非法值 '3'/True/False/0/-1/1.5/None 全部回退 7（bool 虽是 int 子类仍判非法）（出处：core/config.py:1997-2053 白名单加键+校验、core/knowledge_audit.py:67-71 ESCALATED_STALE_DAYS、tests/test_knowledge_audit_escalation_governance.py:354/:384） | pass | 0/6 | - |
| arbitration-consume-same-day-despite-done-gate | R4 仲裁闭环·实驱动（当日体检已跑仍当日消费）：8 龄期 escalated 先跑体检（注记在盘、todo 聚合行在场），置 last_audit_date=今日（自然日防重短路态）后向 .fenix/knowledge_audit_arbitration.json 写入 decision=no-conflict，调 knowledge_daily_check——audit 车道被防重短路未跑（lane 零调用）但独立仲裁消费段当日消费：台账删条目、清单回写为空（防 300s 周期重复消费）、两页注记同轮摘除并自提交、日志留痕「仲裁清单消费」、工作区干净；第二步同实例再跑 run_audit——该页对恢复自动复核（新候选重派发、条目以 exempt 重建 review_rounds=0，todo 聚合行随之摘除）（出处：core/knowledge_audit.py:369-462 consume_arbitration、:489-501 消费段挂防重短路之前、:75 ARBITRATION_RELPATH、tests/test_knowledge_audit_escalation_governance.py:418） | pass | 0/15 | - |
| arbitration-dirty-inputs-skip-with-trace | R4 脏输入防御·实驱动：清单混合 4 条——未知指纹（no-conflict）、suspected 态条目（fixed）、合法指纹配非法 decision（approve）、同指纹合法 false-positive——调 consume_arbitration：consumed=1/skipped=3，合法条目删除、suspected 条目原态保留、3 条跳过条目留清单不吞、日志恰 3 条「跳过留痕」；随后 run_audit ok=True 审计循环不受影响（出处：core/knowledge_audit.py:387-428 逐条校验+跳过留痕、:78 ARBITRATION_DECISIONS 合法枚举，tests/test_knowledge_audit_escalation_governance.py:470） | pass | 0/8 | - |
| arbitration-empty-list-zero-write | R4 空状态零写零提交·实驱动：无清单文件时 knowledge_daily_check 正常跑车道但 results 无 arbitration 键、清单文件不被创建、零提交；人工清空为 [] 后 consume_arbitration 台账逐字节不变、零提交——未命中保持 300s 周期执行的轻量（出处：core/knowledge_audit.py:384-386 fail-open 空清单、:493-501 消费段未命中零写、tests/test_knowledge_audit_escalation_governance.py:510） | pass | 0/6 | - |
| arbitration-all-decisions-consumed | R4 decision 合法枚举全覆盖·实驱动：3 条 escalated 指纹分别登记 fixed / no-conflict / false-positive 三种合法决定，调 consume_arbitration：triggered=True、consumed=3、三指纹全部自台账删除、清单回写为空——三种合法决定同走 _record_verdict+删条目通路（出处：core/knowledge_audit.py:78 ARBITRATION_DECISIONS=('fixed','no-conflict','false-positive')、:387-428 消费循环） | pass | 0/5 | - |
| disputed-annotation-shared-page-convergence-on-partial-consume | R3/R4 同页多疑点注记收敛·实驱动：页 p00a 挂两条超龄 escalated（真实指纹 8 龄期 + 合成指纹 10 龄期）、p00b 仅真实指纹——写入阶段 p00a 收敛为单条注记含两指纹前 8 位（since 取最早 first_seen）、p00b 仅真实指纹注记；仲裁消费真实指纹（false-positive）后 p00a 注记原位改写收敛为仅剩合成指纹（fps 收敛而非误摘）、p00b 注记摘除，同步自提交、工作区干净（出处：core/knowledge_audit.py:262-281 _disputed_targets 同页收敛、:428-443 消费后按台账现状重算期望态+restrict_pages、tests 语义出处 design.md D4） | pass | 0/8 | - |

## 本轮场景集变更

当前稳定场景集共 15 个（第 1 轮）。

- 首轮写入 15 个场景

