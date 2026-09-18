# Spec Delta: baseline-blocked-gate

## ADDED Requirements

### Requirement: 全量套件执行必须有界且可诊断挂起
框架 MUST 提供有界的全量套件执行入口：单次执行带硬超时，超时或检测到测试挂起时 MUST 中止并报出**挂起的测试标识**（而非无限期占用 run 预算）。implementer/repair 契约 MUST 引导使用该入口执行全量回归，MUST NOT 仅依赖裸 `pytest` 调用而无超时。

注释：本案实证——裸 `pytest tests/ -q` 在存量死循环处挂起，实现 run 单次等待超过 1 小时，I/O 涨至 44–60GB；框架能否给出「挂在哪个测试」直接决定该 run 是数分钟收口还是数小时空转。

#### Scenario: 套件挂起时中止并报出测试标识
- **WHEN** 全量套件在某测试处挂起，执行时间超过有界入口的超时阈值
- **THEN** 系统 MUST 中止该次执行，并在输出中给出挂起测试的标识（文件/用例名），MUST NOT 无限期等待其自然结束

#### Scenario: 正常套件不受影响
- **WHEN** 全量套件在阈值内正常跑完
- **THEN** 有界入口 MUST 返回完整结果，行为与直接运行套件一致

### Requirement: 存量失败与本次引入失败的显式归类
当全量回归存在失败或挂起时，系统 MUST 提供将其归类为「存量」或「本次引入」的判定路径，判定 MUST 以变更前基线（本 change 首个提交的父提交）的等价执行为依据，MUST NOT 仅凭文件名/模块名经验推断。归类结论 MUST 落于两类之一，且 MUST NOT 允许把「仅本次引入」的失败归为存量。

#### Scenario: 失败在基线复现 → 归为存量
- **WHEN** 某失败或挂起在变更前基线的等价执行中同样出现
- **THEN** 系统 MUST 归类为存量，并在结论中指明基线复现依据

#### Scenario: 失败仅本次出现 → 归为本次引入
- **WHEN** 某测试在变更前基线通过，但在本 change 的代码状态失败或挂起
- **THEN** 系统 MUST 归类为本次引入，MUST NOT 归为存量

#### Scenario: 混合情形不得整体放行
- **WHEN** 全量回归中既有基线复现的存量失败，又有仅本次引入的失败
- **THEN** 系统 MUST 判为存在本次引入的回归，MUST NOT 以存量为由整体放行

### Requirement: 存量归类后 run 快速收口且证据可审计
一旦全量回归的失败/挂起被归类为存量（与本 change 无关且无法在本 change 范围内消除），implementer run MUST 据此收口为可判定终态并保留证据（阻塞测试标识 + 基线复现结论），MUST NOT 在同一 run 内反复完整重跑全量套件直至撞满超时预算。

#### Scenario: 归类后不再反复重跑
- **WHEN** 某 run 已把全量回归的失败/挂起归类为存量
- **THEN** 该 run MUST 据此收口，MUST NOT 再次完整重跑全量套件（除非为收集一次基线对照证据）

#### Scenario: 收口证据可审计
- **WHEN** 一次 run 以存量归类收口
- **THEN** run 文件与提交信息 MUST 含阻塞测试标识与基线复现结论，使该收口可被独立复核

### Requirement: 工作树缺失自举部署物时相关测试跳过而非失败
仅存在于主树的自举部署物（如 `.fenix/hooks/*`、`dist/`）在 worktree 中不存在时，依赖这些文件的测试 MUST 以 skip 处置（或经等价环境容错），MUST NOT 硬失败。测试 MUST NOT 因「worktree 未部署自举物」这一环境事实而被判为本 change 引入的回归。

注释：本案实证——`tests/test_block_main_tree_write_hook.py` 与 `tests/test_planner_scenarios_batching_hook.py` 硬编码 `.fenix/hooks/*` 路径，worktree 内文件不存在时前者失败、后者主动 `raise AssertionError`，构成每次 worktree 验证的固定噪声并干扰存量/引入归类。

#### Scenario: hooks 缺失时跳过
- **WHEN** 在 worktree 中运行依赖 `.fenix/hooks/*` 的测试，而该文件不存在
- **THEN** 测试 MUST 以 skip 结果结束（skip 原因指明自举物未部署），MUST NOT 计为失败

#### Scenario: 主树存在时正常执行
- **WHEN** 在主树（自举物已部署）运行同一批测试
- **THEN** 测试 MUST 正常执行其断言，行为与现状一致
