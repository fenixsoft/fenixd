# core-package-structure 规格

## ADDED Requirements

### Requirement: 外部 API 零变化

core 包重组后，所有现存 import 路径与符号 MUST 保持可用：`from core.pm_engine import PMEngine`、`from core.agent_runner import AgentRunner`、`from core.agent_runner import AgentRunResult, AdminDisposition, clean_old_runs`。`fenixd.py` 与 `core/dashboard/data.py` 的 import 语句 MUST NOT 修改。测试直接调用的私有方法（如 `engine._process_queue`、`engine._do_spec_bug_found`、`runner._build_prompt`、`runner._record_provider_4xx`）MUST 经门面委托保持调用路径可用。

#### Scenario: import 路径逐一验证

- **WHEN** 包成型阶段（阶段 3、6）完成后运行 `python -c "from core.pm_engine import PMEngine"`、`python -c "from core.agent_runner import AgentRunner, AgentRunResult, AdminDisposition, clean_old_runs"`
- **THEN** 全部 import 成功且符号身份与重组前一致

#### Scenario: 现有测试零修改通过

- **WHEN** 任一拆分阶段完成后运行全量 pytest
- **THEN** tests/ 目录下 27 个测试文件无任何修改，且结果不劣于基线（912 passed + 1 个已认定的环境性失败，不引入新失败）

### Requirement: 职责包结构

pm_engine.py MUST 重组为 `core/pm_engine/` 包，包含 engine（门面）、dispatch、family、budget、verification、recovery、reporting 七个模块；agent_runner.py MUST 重组为 `core/agent_runner/` 包，包含 runner（门面）、prompt_builder、provider_circuit、liveness、token_budget、v2_server、session（可并入 runner）、run_files 组件。拆分后单模块 SHOULD 在 300-800 行量级（门面与准纯函数模块可例外）。

#### Scenario: 组件按职责就位

- **WHEN** 阶段 3 与阶段 6 完成后检查包结构
- **THEN** 上述模块存在且旧的单文件 `core/pm_engine.py`、`core/agent_runner.py` 已删除，职责归位与设计文档 D2 一致

### Requirement: 状态归属与锁安全

组件提取时 MUST 遵守：领域状态随组件同迁；线程锁与其被保护状态（`_queue_lock` 与 `_run_queue`/`_active_runs`/`_active_priorities`）MUST 整体同迁至 Dispatcher，不得出现两把锁或锁与状态分离；无状态依赖经构造注入；跨域调用只允许"组件 → 门面"单向回引（`self._pm`），门面单向持有组件。

#### Scenario: Dispatcher 单锁验证

- **WHEN** 阶段 6 完成后检查 Dispatcher 实现
- **THEN** `_queue_lock` 与其保护的队列/活动计数状态位于同一对象，全仓库无第二把锁保护这些状态

#### Scenario: 并发相关测试通过

- **WHEN** 阶段 6 完成后运行 test_dispatch_aging、test_repair_redispatch、test_repair_lane_dedup、test_pm_engine_dispatch_fixes
- **THEN** 全部通过

### Requirement: 行为等价

拆分 MUST 保持行为等价：搬移方法时只改写调用点（`self.xxx` → `self._pm.xxx` 或组件内调用），不重排语句、不改条件、不顺手优化；准纯函数模块（PromptBuilder）MUST 保持文件读取时机等价（不缓存、不提前读取）；巨方法内部结构不动。

#### Scenario: characterization tests 锁定行为

- **WHEN** 阶段 0 对将被搬移且无测试覆盖的方法补充 characterization tests 后，后续每个拆分阶段运行全量测试
- **THEN** characterization tests 全部通过，证明搬移前后行为一致

### Requirement: bug 只记录不修

拆分过程中发现的 bug、死代码、可疑逻辑 MUST 记录到持续维护的疑点清单（自阶段 0 起，随各阶段追加），MUST NOT 在本次重构中修复；清单在阶段结束统一汇报。

#### Scenario: 疑点不混入重构 diff

- **WHEN** 审查任一拆分阶段的 commit
- **THEN** diff 中不含行为修改（仅调用点改写与代码搬移），发现的疑点全部出现在清单而非代码改动中

### Requirement: 分阶段提交与验证

重构 MUST 按 design D5 阶段表执行：每阶段独立 commit；每阶段完成后全量 pytest（允许基线环境性失败）+ import 兼容验证通过方可进入下一阶段；回滚粒度为阶段。

#### Scenario: 阶段门禁

- **WHEN** 任一阶段完成
- **THEN** 该阶段有独立 commit，且 commit 时全量测试通过（不引入新失败）、import 验证通过

### Requirement: daemon 运行安全

重构期间 MUST NOT 触发 daemon 重启（不 touch `.fenix/restart_request`）；运行中的 daemon 不受文件重组影响。重启冒烟验证仅在收尾阶段（阶段 8）且经用户确认时机后执行。

#### Scenario: 重构期间 daemon 持续运行

- **WHEN** 阶段 0-7 任意时刻检查 daemon 进程
- **THEN** daemon 未被本次重构重启或中断，`.fenix/restart_request` 不存在
