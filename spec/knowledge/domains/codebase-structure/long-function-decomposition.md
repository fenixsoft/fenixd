# 超长函数拆分纪律

<!-- knowledge: capability=long-function-decomposition rev=1 sources=spec/archive/2026-09-22-refactor-long-functions -->

把验证管线与 agent 执行两处超长函数拆为私有协作方法、主函数收敛为编排骨架的拆分规则与等价性边界。

## 规则

- 拆分格局：`VerificationPipeline._run_three_stage_verification` 按三阶段（阶段 1 / 阶段 2 / 阶段 3 及各自子步骤）提取私有方法；`AgentRunner._execute_agent_inner` 按执行阶段（准备 / 子进程驱动 / 事件处理 / 终态判定 / 产物门）提取私有方法。
- 主函数收敛为编排骨架：主函数体只含方法调用、控制流骨架与必需的局部变量传递，不得以内联业务逻辑充数；保留在函数体内的循环体（pipeline 侧阶段循环、runner 侧单 attempt 事件循环及其 except 收口）计入主函数长度，故收敛口径为主函数长度较拆分前基线下降至少三分之一——`_run_three_stage_verification` ≤ 830 行、`_execute_agent_inner` ≤ 600 行。
- 提取粒度：新提取的私有方法无单个超过 300 行（目标 ≤ 200 行）。
- 等价搬移：局部变量经参数 / 返回值显式传递，不借机重写逻辑、不改求值顺序、不改短路求值、不改异常传播路径；被多个提取方法使用的局部变量显式传递，不得改为隐式实例状态——以显式传入、生命周期限于单次 attempt 的可变状态对象（如 `_AttemptState`）承载跨方法共享的局部标量属「参数显式传递」；提升为 `self` 实例属性会跨 attempt 泄漏，禁止。
- 可观测行为不变：STATE 推进序列、写出产物、返回结构、异常类型与消息均不变。
- characterization 测试先行：拆分前运行并记录基线结果，作为拆分前后等价性的证据；既有以 monkeypatch / 直调方式触达函数内部符号的测试不依赖被消除的内部符号名。
- 锚定纪律：任务与交付物以方法名 / 段落名锚定，不使用绝对行号。

## 溯源

- 2026-09-22 2026-09-22-refactor-long-functions（spec/archive/2026-09-22-refactor-long-functions） — 确立两超长函数拆分纪律：编排骨架收敛口径（保留循环体计入长度）、等价搬移边界、attempt 级显式状态对象约定、characterization 先行与符号名锚定
