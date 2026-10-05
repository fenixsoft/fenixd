# 验证报告：evo-add-acceptance-deviation-reporting

> ⚠️ 本报告由框架于 2026-10-05T23:16:41Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-05T23:16:40.478377+00:00+run-result@mtime1791242200516515671

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.11M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| impl-md-checkin-discipline-wording | agents/implementer.md 落盘任务勾选纪律段（任务 1.1）：字面验收未满足 MUST NOT 勾选完成、行内注明「以 X 替代验收」示例、findings 验收偏差条目三要素+evidence 形状、当轮经 unfinished 走 partial、闭环语义（替代场景链为后续验收基准）与 unattainable 诚实出口、结果模板 findings 字段与 success 硬门提示均在模板中。出处 agents/implementer.md:14-21 与 agents/implementer.md:47 | pass | 0/12 | - |
| planner-plan-substitute-rule-wording | agents/planner-plan.md 落盘「验收偏差注解任务出题规范」（任务 2.2）：带「以 X 替代验收」注解的任务 MUST 按注解的替代方式出题、MUST NOT 按字面验收出场景链、替代场景链即后续实现轮验收基准、注解缺失或语义不明时仍按字面出题。出处 agents/planner-plan.md:26-30 | pass | 0/8 | - |
| prompt-discipline-single-source-probe | 提示词单源探针（任务 1.2）：prompt_builder.acceptance_deviation_discipline_section() 渲染段含勾选纪律关键措辞，且 result_gate 经 import 引用同一常量对象（ACCEPTANCE_DEVIATION_TYPE / IMPL_FINDINGS_TYPE_WHITELIST / ACCEPTANCE_DEVIATION_ANNOTATION 身份相等）——改措辞只改单源即两侧生效，防提示词与硬门漂移。出处 core/agent_runner/prompt_builder.py:221-258、core/agent_runner/result_gate.py:1711-1714 | pass | 0/2 | - |
| agent-templates-framework-path-probe | 提示词文件经框架路径解析探针（任务 1.1/2.2）：AGENT_PROMPT_DIR / AGENT_PROMPT_FILES（FRAMEWORK_ROOT 单源，随加载模块解析到验证树）读出的 implementer 与 planner-plan 模板均含各自纪律措辞——框架运行时真实读到的就是含规范版本，而非仅仓库文件静态存在。出处 core/agent_runner/prompt_builder.py:23、core/agent_runner/prompt_builder.py:42 | pass | 0/2 | - |
| impl-findings-structure-validation-probe | findings 结构校验探针（任务 2.1 白名单部分）：findings 缺省/空数组零拦截（无偏差 run 零开销）；非数组、条目非对象、type 不在白名单、acceptance-deviation 条目缺 task/literal/substitute/evidence 任一要素均结构类拒绝（防口头替代）；偏差任务提取器 impl_findings_deviation_tasks 正确取 task。出处 core/agent_runner/result_gate.py:1682-1750 | pass | 0/2 | - |
| success-deviation-gate-rejection-probe | success∧偏差组合硬门判据探针（任务 2.1 组合校验）：success 且偏差任务∈completed_tasks → 拒绝，文案含「验收偏差」+任务 id 且指引 partial（unfinished 申报）/替代场景链/unattainable 三条出路、无 task-gate 前缀（结构类不降级）；偏差任务不在 completed_tasks 或 findings 缺省时判据不命中。出处 core/agent_runner/result_gate.py:1753-1783 | pass | 0/2 | - |
| deviation-gate-pytest-hard-gate-suite | 产物硬门全用例套件（任务 3.1）：pytest 跑 tests/test_honest_exit_convergence.py::TestAcceptanceDeviationGate 十个用例全绿——success∧偏差∈completed_tasks 被拒、结构类路径、拒绝文案出路指引、partial 携带偏差放行、无偏差零影响、越界 id 不命中、闭环后续 success 轮放行、未知 type 白名单拒绝、缺三要素/evidence 拒绝、fast-track 车道同义生效。出处 tests/test_honest_exit_convergence.py:382-517 | pass | 0/8 | - |
| discipline-prompt-contract-pytest-suite | 提示词契约套件（任务 3.2）：pytest 跑 tests/test_agent_prompt_files.py::TestAcceptanceDeviationDisciplinePrompt 六个用例全绿——implementer 模板含纪律段与条目形状、构建后 implementer/fast-track/planner-plan prompt 均注入对应措辞、result_gate 与 prompt_builder 措辞单源（常量对象同一+纪律段原样入 prompt+拒绝文案引用同一注解短语）。出处 tests/test_agent_prompt_files.py:912-991 | pass | 0/8 | - |
| impl-result-contract-regression-green | 回归点（任务 3.1/3.2 周边）：两个测试文件全量 141 用例全绿——本 SPEC 新增 findings 字段与组合硬门未破坏既有诚实退出收敛判据（unattainable/partial/success 完成度对账）与既有提示词契约断言。出处 tests/test_honest_exit_convergence.py、tests/test_agent_prompt_files.py（全文件，2026-10-06 本机实测 141 passed） | pass | 0/2 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

