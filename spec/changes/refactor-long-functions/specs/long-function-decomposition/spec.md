# long-function-decomposition

## ADDED Requirements

### Requirement: 两个超长函数拆为私有方法

`core/pm_engine/verification/pipeline.py` 的 `VerificationPipeline._run_three_stage_verification`（约 1249 行）与 `core/agent_runner/runner.py` 的 `AgentRunner._execute_agent_inner`（约 907 行）MUST 按内部段落拆为若干私有方法 / 协作方法，主函数 MUST 收敛为编排骨架。

- `_run_three_stage_verification` MUST 按阶段（阶段 1 / 阶段 2 / 阶段 3 及各自子步骤）提取私有方法。
- `_execute_agent_inner` MUST 按执行阶段（准备 / 子进程驱动 / 事件处理 / 终态判定 / 产物门）提取私有方法。

拆分完成后，任一提取出的私有方法 SHOULD 不超过 200 行；两个主函数 MUST 各自收敛为编排骨架，且长度较重构前**下降至少三分之一**（`_run_three_stage_verification` 约 1249 行 → ≤ 830 行；`_execute_agent_inner` 约 907 行 → ≤ 600 行）。

> 阈值口径：design D2 明确保留在函数体内的循环体（pipeline 侧 472 行 `while True`；runner 侧 419 行内层 `while True` 及其 except 收口）**计入**主函数长度，故收敛口径为「下降至少三分之一」而非「降至三分之一以下」——后者与 D2 互斥，仅保留的循环体即已超过原长度的三分之一。同时，主函数 MUST NOT 以内联业务逻辑充数：除 D2 保留的循环体外，主函数体内 MUST 只含方法调用、控制流骨架与必需的局部变量传递。

#### Scenario: 主函数收敛为编排骨架

- **WHEN** 审阅拆分后的 `_run_three_stage_verification`
- **THEN** 其函数体为对提取出的阶段方法的顺序编排，不含大段内联逻辑

#### Scenario: 提取方法粒度达标

- **WHEN** 统计拆分后新提取的私有方法长度
- **THEN** 无单个方法超过 300 行

### Requirement: 等价搬移，无控制流重组

提取 MUST 只做等价搬移：局部变量通过参数 / 返回值显式传递，MUST NOT 借机重写逻辑、MUST NOT 改变求值顺序、MUST NOT 改变短路求值、MUST NOT 改变异常传播路径。

#### Scenario: 控制流逐条等价

- **WHEN** 对比拆分前后同一输入下的 return / raise 路径
- **THEN** 分支判定条件与求值顺序逐条一致

#### Scenario: 共享局部变量显式传递

- **WHEN** 某局部变量被多个提取方法使用
- **THEN** 通过参数或返回值显式传递，MUST NOT 改为隐式实例状态

> 边界约定：以一个**显式传入**、生命周期限于本函数（runner 侧为单次 attempt）的可变状态对象（design D3 的 `_AttemptState`）承载跨方法共享的局部标量，属「参数显式传递」，不属「隐式实例状态」。MUST NOT 改用 `self` 实例属性承载——原变量是每次 attempt 重初始化的局部量，提升为实例属性会跨 attempt 泄漏。

### Requirement: 可观测行为不变

两个函数的状态推进、写出的产物、返回结构、异常类型 MUST NOT 变化。

#### Scenario: 状态推进不变

- **WHEN** 用同一组输入驱动两个函数
- **THEN** STATE 推进序列与产物内容与重构前一致

#### Scenario: 异常类型不变

- **WHEN** 触发原有异常路径
- **THEN** 抛出的异常类型与消息与重构前一致

### Requirement: characterization 测试先行

拆分 MUST 先补 characterization tests 锁定两个函数的可观测行为（在拆分前运行并记录结果），作为拆分前后等价性的证据。既有以 monkeypatch / 直调方式触达函数内部符号的测试 MUST 在拆分后仍可通过（MUST NOT 依赖被消除的内部符号名）。

#### Scenario: 拆分前基线可运行

- **WHEN** 在拆分前的代码上运行 characterization 测试
- **THEN** 全部通过并记录基线结果

#### Scenario: 内部符号依赖不破

- **WHEN** 运行既有针对这两个函数的测试
- **THEN** 无一因内部符号改名 / 搬移而失败

### Requirement: 不使用绝对行号锚定

任务与交付物 MUST 以方法名 / 段落名锚定，MUST NOT 使用绝对行号。

#### Scenario: 任务锚点为符号名

- **WHEN** 审阅 tasks.md
- **THEN** 所有任务以方法名 / 段落名描述位置，无绝对行号
