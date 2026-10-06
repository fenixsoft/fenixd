# 验证报告：evo-improve-placeholder-scan-discrimination

> ⚠️ 本报告由框架于 2026-10-02T18:25:16Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-02T18:25:16.412698+00:00+run-result@mtime1790965516444760784

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.69M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| scan-injected-literal-downgraded-to-info | 注入值字面量降级（spec 场景2）：code-fix 台账条目引用源码 f-string「{e}」、URL 模板「${doc}」「{ts}」字面量经 values 注入，_fill_and_scan_placeholders 填充后残差须判「注入值字面量」——零 WARNING、INFO 计数在场、字面量与填充内容原样保留、派发不被阻断（出处 core/agent_runner/prompt_builder.py:103-134，design D1；R1 注入值字面量 MUST 降为 INFO 且 MUST NOT 再打 WARNING） | pass | 0/5 | - |
| scan-template-drift-warning-carries-template-name | 模板真漂移告警携带模板名（spec 场景1）：模板骨架含构建方未填充的 {job} → WARNING 恰 1 条且消息含模板名 evolution.md（AGENT_PROMPT_FILES[agent_type]，prompt_builder.py:41-55）、残留键 job、调用点上下文 run-abc；填充行为保持无条件 return out——未填充占位符原样保留、已填充值生效（出处 prompt_builder.py:103-134，design D1/D2，R1/R2） | pass | 0/6 | - |
| scan-backward-compat-default-kwarg-still-warns | 向后兼容（design D1）：不传 template_name keyword（缺省 None 退化形态）调用含未填充占位符的模板仍打 WARNING、返回值完整、不抛异常——签名扩展不破坏潜在调用方 | pass | 0/3 | - |
| scan-json-brace-literals-and-empty-input-clean | 空输入与 JSON 花括号边界（异常路径）：模板含 JSON 示例字面量（{"data": …}、{}、{1}）与空模板均不触发任何 WARNING——模板通道扫描不误伤合法花括号文本（_PLACEHOLDER_RE 字符类限定，prompt_builder.py:33），空模板返回空串 | pass | 0/5 | - |
| scan-large-injected-value-info-only | 超长注入值鲁棒性（异常路径）：2 万字符注入值内嵌 200 个占位符形 token （{tok_0}…{tok_199}）→ 仅 INFO 计数不 WARNING，填充结果完整保留（出处 R1 注入值字面量降级；self-review 车道形态，prompt_builder.py:1533 调用点） | pass | 0/4 | - |
| scan-call-sites-all-pass-template-name | R2 调用点全覆盖（MUST NOT 只改单车道）：AST 解析 core/agent_runner/prompt_builder.py，_fill_and_scan_placeholders 全部调用点（设计确认 5 处：主路径 spec :347 / self-review :1533 / evolution :1606 / code-review :1684 / code-fix :1736）均传 template_name（keyword 或第 6 位置实参）（出处 design D2） | pass | 0/3 | - |
| render-all-agent-types-zero-template-drift | R3 渲染断言·全车道回归（spec 场景4）：复用 tests/test_agent_prompt_files.py 的 make_runner 夹具惯例驱动真实构建器 _build_prompt，渲染 AGENT_PROMPT_FILES 全部 12 个 agent 类型，断言模板通道零漂移（零「提示词占位符未解析」WARNING）、零构建异常——独立于交付物自身测试的交叉验证（出处 design D3，tests/test_agent_prompt_files.py:44-69 惯例） | pass | 0/3 | - |
| deliverable-test-file-contract-and-suite-passes | 交付物测试文件契约（tasks 2.1/2.2）：tests/test_prompt_placeholder_scan.py 存在，且内容按项目惯例驱动真实构建器（含 make_runner/_build_prompt/AGENT_TYPES/被测函数 _fill_and_scan_placeholders 字样），pytest 全量通过（-v 冗长模式，不并列 -q，output_match 断言与真实输出形态一致） | pass | 0/7 | - |
| deliverable-render-test-parametrized-full-coverage | R3.1 参数化全集覆盖（tasks 2.1「按 AGENT_TYPES 参数化」）：pytest --collect-only 收集 tests/test_prompt_placeholder_scan.py 用例数 >= 12（AGENT_PROMPT_FILES 共 12 个 agent 类型，prompt_builder.py:41-55，参数化渲染每模板至少一例） | pass | 0/2 | - |
| mutation-evolution-recurrence-caught-and-rolled-back | 回潮拦截（spec 场景3）：向 agents/evolution.md 塞回未填充占位符 {epoch}（历史唯一真漂移案复刻，已由 commit 45675687 修复）→ 交付物渲染断言测试必须失败（pytest 退出码 1 = MUTATION_CAUGHT），随后从备份恢复文件并 diff 校验逐字节一致（mutation 自含回滚；依赖交付套件先全绿，防「套件本来就红」造成的退出码 1 误判为拦截成功） | pass | 0/2 | - |
