# 验证报告：evo-scenario-product-toplevel-contract

> ⚠️ 本报告由框架于 2026-10-06T19:46:19Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-06T19:46:19.070150+00:00+run-result@mtime1791315979117878543

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 9.40M |
| 本链增量 Token（输出） | 0.12M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| planner-plan-md-toplevel-contract | 「规划任务书顶层契约」静态模板侧（tasks 1.1）：agents/planner-plan.md 分批落盘工作流处显式声明 test_scenarios.json 顶层必须是纯 JSON 数组、MUST NOT 用 {"scenarios": […]} 之类 dict 包裹（附读端拒收文案「场景文件格式错误」）、正例 [{"id": "login-ok"…}] 与反例各一行、显式区分同目录 scenarios.json（持久化集）dict 形态相反不得互抄。 | pass | 0/8 | - |
| prompt-builder-planner-plan-toplevel-injection | 「Scenario: 运行时提示词含顶层契约」（tasks 1.2）：构造 planner-plan 会话提示词（最小 AgentRunner 装配 + _build_prompt），注入内容含「顶层交付契约」段、纯 JSON 数组契约句、dict 包裹反例与纯数组正例、scenarios.json dict 形态区分说明，且既有场景 schema 必填字段段保留（双保险之运行时侧）。 | pass | 0/8 | - |
| prompt-builder-other-lanes-unchanged | 「Scenario: 其他 agent 不受影响」（tasks 1.2）：构造 planner-judge 与 fast-track 会话提示词，均不注入「顶层交付契约」条目（含纯 JSON 数组契约句也不出现）但既有场景 schema 段保留；administrator 仍不注入 schema 段（schema-alignment 2.4 边界不回归）。 | pass | 0/7 | - |
| load-scenarios-toplevel-gate-unchanged | 读端硬门既有语义不变（tasks 2.1 前置，design D1）：load_scenarios 对顶层 dict 包裹照抛「场景文件格式错误: 期望JSON数组，实际为 dict」、对字符串顶层照抛同格式错误（不拯救），纯数组顶层照常加载（id 序保持），文件缺失 FileNotFoundError——拯救由验收路径显式调用，load_scenarios 本体不接助手。 | pass | 0/7 | - |
| unwrap-scenarios-dict-form-scoping | 拯救助手形态收窄（design D1，tasks 2.1）：unwrap_scenarios_dict 仅对「顶层 dict 且含非空 scenarios 数组」解包返回该数组；dict 缺 scenarios 键（报错含顶层键清单）、scenarios 非数组、scenarios 空数组均报「不可解包」；非 dict 顶层（数组/字符串/数字）报「非 dict 包裹形态」无解包面——字符串/列表套列表等不拯救。 | pass | 0/7 | - |
| salvage-rewrites-pure-array-with-audit-info | 「Scenario: dict 包裹产物被解包采纳」（tasks 2.1/2.2，design D1/D4）：salvage_scenarios_file 对 {"spec":…,"scenarios":[…]} 解包重过既有全部场景校验后返回 TestScenario 列表与留痕 info（top_keys/entry_count/rewritten=true），并以解包后的纯数组原子重写原文件——盘上变纯数组、原始条目字段零丢失（raw 落地而非 to_dict 回环）、其余 load_scenarios 读端按既有语义恢复可读、无临时文件残留（原子写 os.replace）。 | pass | 0/9 | - |
| salvage-rejects-invalid-or-unsalvageable-without-rewrite | 「Scenario: 解包后仍非法照常拒收」（tasks 2.1，design D1）：解包得到的条目未通过既有场景校验 → ValueError 且盘上文件保持 dict 原文不落地；缺 scenarios 键 / scenarios 为 dict / 标量 / 列表套标量等不可拯救形态同样 ValueError 不落地；文件缺失 FileNotFoundError（同 load_scenarios 既有语义）。 | pass | 0/7 | - |
| pipeline-stage2-salvage-wiring | 「验收归因点单点接线」（tasks 2.2，design D1/D4）：VerificationPipeline._execute_stage2 对 dict 包裹产物先拯救——解包落地后不产生 env_error（不按「场景文件验收失败」退回 replan）、盘上纯数组、WARNING 留痕含解包前顶层键与条目数、格式类侧车保持 False；不可拯救形态（dict 缺 scenarios 键）照常 env_error「场景文件验收失败」+ _replan_error_format_class 置位 + 拯救不适用 info 留痕 + 渲染反馈走最小修复文案不含全量重建——拯救单点接入验收归因点，其余读端不接助手。 | pass | 0/9 | - |
| replan-feedback-classified-minimal-repair | 「拒收反馈按类别给最小修复指引」（tasks 2.2，design D3）：_replan_feedback_text 在格式类侧车置位时给「最小修复」指引（含失败类别「格式类」、修复动作指明顶层纯数组契约与 dict 反例、保留 navigate 绝对 URL 规则），MUST NOT 含「重新输出全部场景」，并模拟 REPLAN_FEEDBACK.md 写盘点验证落盘文件即分类文案；内容类缺失保留「重新输出全部场景」全量重建指示；侧车缺省 False（未经历 stage2 的路径）照旧全量重建文案，既有行为不回归。 | pass | 0/7 | - |
| pytest-toplevel-gate-salvage-suite | 测试回归（tasks 3.1）：pytest 跑 tests/test_verify_scenarios.py::TestTopLevelGateAndSalvage 全部 12 用例——非数组顶层被 load_scenarios 拒绝、拯救助手对 {"scenarios":[…]} 解包成功、缺 scenarios 键/非数组值/空数组/非 dict 原样报错、解包后非法不落地、纯数组输入不受影响、文件缺失 FileNotFoundError。命令只带 -v（不带 -q，保 PASSED 行输出），断言逐用例照抄真实输出行。 | pass | 0/16 | - |
| pytest-injection-feedback-wiring-suite | 测试回归（tasks 3.2 + 2.2）：pytest 跑 tests/test_planner_scenario_schema_alignment.py 三个测试类共 9 用例——TestTopLevelContractInjection（planner-plan 注入顶层契约与 scenarios.json dict 形态区分、judge/fast-track 不注入）、TestReplanFeedbackClassifiedText（格式类最小修复不含全量重建、内容类保留、侧车缺省）、TestStage2TopLevelSalvageWiring（拯救成功跳过 replan 落地纯数组留痕、不可拯救置格式类侧车）。命令只带 -v（不带 -q，保 PASSED 行输出），断言逐用例照抄真实输出行。 | pass | 0/13 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

