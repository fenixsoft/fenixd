# 验证报告：evo-add-verify-fixture-flag-guard

> ⚠️ 本报告由框架于 2026-10-06T18:44:04Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-06T18:44:03.703100+00:00+run-result@mtime1791312243738473744

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.96M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| fixture-guard-scan-explicit-false-flagged | 静态扫描守卫（verify-fixture-guard）：cli 场景命令 stdin 内 reg.add_project(..., fixture=False) 注册探针夹具（add-alert-self-heal-marking 事故同型）命中 unmarked_fixture_add_project 情报——location 指 steps[0].stdin，message 含 fixture=True 补标建议（ADR-163）并引用原调用片段。出处 core/verify_engine/scenario_static_check.py:407-447 | pass | 0/5 | - |
| fixture-guard-scan-omitted-and-unclosed-flagged | 静态扫描守卫异常路径：缺省不传 fixture（Registry.add_project 缺省 False）的 str command 形态命中情报且 location 指 steps[0].command；命令截断未闭合形态（括号配平失败取剩余文本判）同样命中。出处 core/verify_engine/scenario_static_check.py:376-404 | pass | 0/4 | - |
| fixture-guard-scan-marked-forms-clean | 静态扫描守卫零误报回归：显式 fixture=True、等号带空白 fixture = True、mark_fixture 补标调用（非 add_project 注册面）、嵌套实参含 fixture=True 四种已打标/合法形态均不产情报。出处 core/verify_engine/scenario_static_check.py:372-374 | pass | 0/5 | - |
| fixture-guard-scan-argv-list-and-nested-args | 静态扫描守卫形态覆盖：cli command 的 argv 列表双形态（逐项拼接后扫，argv 项内嵌未打标调用不漏报）与括号配平的嵌套实参提取（dict 实参不含 fixture=True 仍命中）。出处 core/verify_engine/scenario_static_check.py:376-404 | pass | 0/4 | - |
| fixture-guard-scan-kind-scope-and-port-independence | 静态扫描守卫作用域：模式表 kinds 只覆盖 cli——同文本 web 场景不扫（web 无场景命令注册面）；need_port=False——serving 端口未知（None）时本规则仍执行（与端口无关）。出处 core/verify_engine/scenario_static_check.py:470-476 | pass | 0/3 | - |
| fixture-guard-pattern-table-contract | 静态扫描守卫表驱动契约与 fail-open：PATTERN_TABLE 存在 rule_id=unmarked_fixture_add_project 表项、kinds 含 cli、need_port=False；steps 含非 dict 项的畸形场景扫描不抛出（只情报不拦截）。出处 core/verify_engine/scenario_static_check.py:468-516 | pass | 0/5 | - |
| fixture-guard-registry-semantics-unchanged | Out-of-Scope 回归：守卫走静态扫描而非缺省翻转（ADR-163 Decision 禁按路径/名字推导）——Registry.add_project 的 fixture 缺省值仍为 False（inspect 签名断言，未被翻转）；行为面 fixture=True 打标注册、同路径重注册跳过且不静默改标记（True/False 双向）、mark_fixture 显式补标、非 Fenixd 项目目录拒注册均不回归。探针用独立临时配置路径，不触碰全局 registry。出处 core/dashboard/registry.py:445,531 | pass | 0/8 | - |
| fixture-guard-governance-doc-must-entry | 规范固化（知识层）：fixture-project-governance.md「现行规则」节新增 MUST 条目在场——验证场景注册探针夹具（/tmp 扫描根外临时路径）MUST 以 fixture=True 调用 Registry.add_project，载明依据 ADR-163、夹具告警直写 admin_alerts.json 不经摄取抑制、缺省聚合分支 fixture 过滤是唯一降噪面，并引用 selfheal-scratch-verify / arch-scratch-verify 两起反例事故。出处 spec/knowledge/domains/test-engineering/fixture-project-governance.md:13 | pass | 0/8 | - |
| fixture-guard-planner-prompt-rule | 规范固化（出题端触达）：agents/planner-plan.md 载明「场景夹具注册规范（fixture=True 硬约束）」——MUST 规则、正例 reg.add_project(SROOT, name="scratch-verify", fixture=True)、反例 fixture=False 与缺省不传形态、依据 ADR-163。出处 agents/planner-plan.md:118-121 | pass | 0/7 | - |
| fixture-guard-test-suite-pass | 测试回归：tests/test_fixture_project_governance.py 全绿——新扫描模式用例（显式 False/缺省命中、True 与空白等号与 mark_fixture 不误报、argv 双形态、web 不扫、端口无关、表项契约）与领域文档/出题提示词存在性断言随既有夹具治理用例一同通过。出处 tests/test_fixture_project_governance.py:610-762 | pass | 0/2 | - |
