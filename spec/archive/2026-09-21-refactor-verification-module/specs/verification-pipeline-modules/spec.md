# verification-pipeline-modules

## ADDED Requirements

### Requirement: 验证流水线按职责分模块

`core/pm_engine/verification.py` MUST 拆分为 `core/pm_engine/verification/` 子包，按职责拆分为独立子模块：`pipeline`、`serving`、`scenario_gate`、`verdict_evidence`、`judge_gate`、`escalation`、`infra_classify`、`legacy`、`branch_guard`、`report_gate`。每个子模块 MUST 只承载单一职责域。

#### Scenario: 子模块职责单一

- **WHEN** 检查 `core/pm_engine/verification/serving.py`
- **THEN** 其内容为被测应用的服务供给（端口/可达性/worktree），不含裁决证据或 judge 门禁逻辑

#### Scenario: 巨型单文件不再存在

- **WHEN** 重构完成
- **THEN** `core/pm_engine/verification.py` 不存在，且不存在任一超过 1500 行的子模块

### Requirement: `PipelineContext` 显式依赖注入

`VerificationPipeline` 及其子组件 MUST 通过显式 `PipelineContext` 访问外部依赖（logger、project_root、state_machine、配置读取、升级通知、派发入队），MUST NOT 直接回引门面私有方法（`self._pm._<private>`）。

#### Scenario: 私有回引被消除

- **WHEN** 对重构后的 `core/pm_engine/verification/` 子包执行 `grep "self\._pm\._"` 
- **THEN** 无任何命中（对门面私有方法的直接调用为 0）

#### Scenario: 公共依赖经 context

- **WHEN** 某子组件需要 logger
- **THEN** 经 `context.logger` 获取，而非 `self._pm.logger`

### Requirement: 调用路径与测试引用零改动

`from core.pm_engine.verification import VerificationPipeline`（及既有公开符号如 `reclassify_infra_rounds`、`resolve_env_blocked_reset_path`、`VerdictReadResult`、`_branch_merged_into_tree`、`_SCENARIO_REPAIR_MAX_ROUNDS`、`_MAX_JUDGE_RERUNS`）MUST 保持可用；`core/pm_engine/engine.py` 的既有门面**委托方法体** MUST NOT 需要修改（允许对 import 行与 `_verification` property 的组合方式做最小适配）；既有测试文件的引用路径 MUST NOT 需要修改。

#### Scenario: 既有 import 可用

- **WHEN** 执行 `from core.pm_engine.verification import VerificationPipeline, reclassify_infra_rounds`
- **THEN** 两者均可导入

#### Scenario: 同名包过渡不破坏 import

- **WHEN** 按 tasks 4.1 把 `verification.py` 改名为 `verification/_legacy.py` 并建立包
- **THEN** 该 commit 上全部既有 import 仍可用（MUST NOT 出现「旧 `verification.py` 与新 `verification/` 包同时存在的中间态」）

#### Scenario: 全量测试不引入新失败

- **WHEN** 重构完成后运行 `bin/run_full_suite.py`
- **THEN** 失败集合相对基线不新增失败

### Requirement: 拆分零行为变化

重构 MUST 为纯结构性搬移与依赖注入，MUST NOT 改变验证语义、裁决规则或门禁阈值。`_run_three_stage_verification` 的内部逻辑 MUST NOT 在本变更中被重构。发现的缺陷只记入疑点清单。

#### Scenario: 验证语义不变

- **WHEN** 用同一组输入调用 `_run_three_stage_verification` 的可观测路径
- **THEN** 状态推进与裁决采纳结果与重构前一致

#### Scenario: 大函数仅搬移不改写

- **WHEN** 审阅 `_run_three_stage_verification` 的迁移
- **THEN** 函数体逻辑逐条等价（仅位置与依赖访问方式变化），无控制流重组

### Requirement: 依赖注入先于模块搬移

重构 MUST 先在原文件内完成 `PipelineContext` 注入与私有回引替换，再进行模块搬移；两阶段 MUST 各自独立 commit。

#### Scenario: 阶段可独立回滚

- **WHEN** 注入阶段发现回归
- **THEN** 可仅回退注入阶段 commit，文件结构仍为原单文件形态

### Requirement: 不使用绝对行号锚定

任务与交付物 MUST 以方法名/模块名锚定，MUST NOT 使用绝对行号。

#### Scenario: 任务锚点为符号名

- **WHEN** 审阅 tasks.md
- **THEN** 每个任务以方法名/模块名描述，不出现「第 N 行」式锚点

### Requirement: 分组表覆盖全部方法

design D2 的分组表 MUST 覆盖 `VerificationPipeline` 的全部方法（含 `VerdictReadResult` 的方法与全部模块级私有辅助），MUST NOT 留有未归属项；未归属项 MUST 显式归入某一子模块或在门面保留。

#### Scenario: 无未归属方法

- **WHEN** 用阶段 0 的 `contract-inventory.md` 与 D2 分组表逐名比对
- **THEN** 不存在既未归组、也未标注「保留在门面」的方法

### Requirement: 模块级名字与既有 patch 语义保持

既有测试以 `patch("core.pm_engine.verification.<name>")` 替换的模块级名字（`subprocess`、`ensure_main_tree_deps`、`run_prepare_steps`、`load_verify_contract`、`rewrite_scenarios_origin`）在拆分后 MUST 仍可被同一路径 patch 命中；子模块中的调用点 MUST 经包命名空间或保留的共享模块延迟解析。

#### Scenario: patch 仍然生效

- **WHEN** 以 `mock.patch("core.pm_engine.verification.subprocess.run")` 运行 `tests/test_blocked_reverify_gate.py`
- **THEN** 被测代码实际使用的是替换后的对象（patch 非空转），用例结果与重构前一致

#### Scenario: 无法保持者显式上报

- **WHEN** 某处 patch 语义确实无法保持
- **THEN** 该处 MUST 在阶段 0 列入例外清单并上报用户裁决，MUST NOT 静默修改测试

### Requirement: 构造签名向后兼容

`VerificationPipeline` 的构造 MUST 保持 `VerificationPipeline(pm)` 位置参数调用可用（context 为可选参数或由 `pm` 内部推导）；既有测试与 fixture 中的构造调用点 MUST NOT 需要修改。

#### Scenario: 既有构造调用不变

- **WHEN** 执行 `VerificationPipeline(pm)`（现有测试与 `tests/fixtures/schema-alignment-showcase/check.py` 的写法）
- **THEN** 构造成功且行为与重构前一致

### Requirement: 代码格式化收口（独立性约束）

在全部结构性拆分完成后，MUST 以**独立 commit** 对 `core/`、`bin/`、根 `fenixd.py` 下的 `*.py` 执行统一格式化，MUST NOT 触及 `agents/`、`docs/`、`spec/` 与任何 `*.md`；格式化提交 MUST NOT 混入任何逻辑改动。

#### Scenario: 格式化与逻辑改动分离

- **WHEN** 审阅格式化 commit 的 diff
- **THEN** 该 commit 不含逻辑性改动，且其上一 commit 的全量回归已全绿

#### Scenario: 格式化不引入失败

- **WHEN** 格式化提交后运行 `bin/run_full_suite.py`
- **THEN** 失败集合与格式化前基线一致
