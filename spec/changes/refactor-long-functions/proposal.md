# Proposal: refactor-long-functions

## Why

core 中仍有 32 个函数体超过 150 行，其中最大的两个是前两条重构 spec **明确写入 Non-Goal 而原样保留**的：

- `VerificationPipeline._run_three_stage_verification` —— **约 1249 行**（`core/pm_engine/verification/pipeline.py`），单函数即占该文件的三分之二，内部虽已用 `# ── 阶段1/2/3 ──` 段落注释自拟目录，但仍是单个不可整段理解的函数。
- `AgentRunner._execute_agent_inner` —— **约 907 行**（`core/agent_runner/runner.py`）。

这两个函数是核心链路（验证主流程、agent 执行主流程），局部变量数十个、嵌套深（`_execute_agent_inner` AST 嵌套深度达 8）、return/except 路径众多。前两条 spec 出于风险考量推迟了它们，但它们正是「无法整文件理解」问题的最后一块——文件已拆小，函数仍是巨石。

## What Changes

- **纯内部重构，零行为变化**：把两个超长函数按其内部段落拆为若干私有方法 / 协作方法，保持可观测行为、控制流语义、异常传播、返回值完全不变。
  - `_run_three_stage_verification`（约 1249 行）：按阶段性段落（阶段 1 / 阶段 2 / 阶段 3 及各自的子步骤）提取私有方法，主函数收敛为编排骨架。
  - `_execute_agent_inner`（约 907 行）：按执行阶段（准备 / 子进程驱动 / 事件处理 / 终态判定 / 产物门）提取私有方法。
- 提取的私有方法 MUST 只做**等价搬移**：局部变量通过参数 / 返回值显式传递，MUST NOT 借机重写逻辑或改变求值顺序。
- 用 **characterization tests** 锁定两个函数的可观测行为（状态推进、写出的产物、返回结构、异常类型），作为拆分前后的等价性证据。
- **不顺手修 bug**：发现的缺陷只记入疑点清单。
- 不使用绝对行号锚定任务与交付物（沿用 `fix-writepoint-anchor-drift` 修订后的口径，以符号名锚定）。

## Capabilities

### New Capabilities

- `long-function-decomposition`: 超长函数体的拆分契约——两个函数的目标结构（段落 → 私有方法映射）、等价搬移约束、可观测行为不变式、characterization 测试要求。

### Modified Capabilities

（无——本变更不修改任何既有 spec 级行为要求）

## Impact

- **代码**：`core/pm_engine/verification/pipeline.py`（1825 行）与 `core/agent_runner/runner.py`（3803 行）内的两个函数体被拆分为多个私有方法；两文件总行数基本不变，单函数长度大幅下降。
- **API**：零变化。两个函数均为类私有方法（`_` 前缀），无外部 import 路径暴露；类的外部方法签名不变。
- **测试**：以 monkeypatch / 直调方式触达这两个函数内部符号的测试须核对（拆分后内部符号名变化可能使某些 `patch` 目标失效）；新增 characterization tests 独立提交。
- **与其它在飞 spec 的关系**：本变更与 `refactor-giant-classes` **源文件不相交**（后者覆盖 `worktree_manager` / `dispatch` / `dashboard-server`），可并行。与 `refactor-facade-delegation` **同文件**（`pipeline.py` / `runner.py`）——故门面收敛 spec MUST 在本变更与 `refactor-giant-classes` 收口后才启动（依赖关系已登记）。
- **运行时**：重构期间运行中的 daemon 内存持旧代码，不受影响。
