# core 包职责分层结构

<!-- knowledge: capability=core-package-structure rev=1 sources=spec/archive/2026-09-07-refactor-core-packages -->

core/ 后端引擎按「组合提取 + 门面」模式分层组织：巨型实现按职责域拆为子包组件，门面类对外保持既有调用契约不变。

## 规则

- 包结构：`core/pm_engine/` 由 engine 门面与 dispatch、family、budget、verification、recovery、reporting 等职责模块组成；`core/agent_runner/` 由 runner 门面与 prompt_builder、provider_circuit、liveness、token_budget、v2_server、run_files 等组件组成；单模块保持在 300–800 行量级（门面与准纯函数模块可例外）。
- 外部 API 零变化：`from core.pm_engine import PMEngine`、`from core.agent_runner import AgentRunner, AgentRunResult, AdminDisposition, clean_old_runs` 等既有 import 路径与符号保持可用；`fenixd.py` 与 `core/dashboard/data.py` 的 import 语句不做适配性修改；测试直调的私有方法（如 `engine._process_queue`、`engine._do_spec_bug_found`、`runner._build_prompt`、`runner._record_provider_4xx`）经门面委托保持调用路径可用。
- 状态归属与锁安全：领域状态随组件同迁；线程锁与其被保护状态整体归属同一对象（`_queue_lock` 与 `_run_queue`/`_active_runs`/`_active_priorities` 同在 Dispatcher，全仓无第二把锁保护这些状态）；无状态依赖经构造注入；跨域调用只走「组件 → 门面」单向回引（`self._pm`），门面单向持有组件。
- 行为等价搬移：搬移方法只改写调用点，不重排语句、不改条件、不顺手优化；准纯函数模块（PromptBuilder）保持文件读取时机等价（不缓存、不提前读取）；巨方法内部结构在拆包中不动。
- 拆分纪律：拆分前对将被搬移且无测试覆盖的方法补 characterization tests，每个拆分阶段跑全量测试佐证行为一致；发现的 bug、死代码、可疑逻辑只记入疑点清单，不混入结构重构的 diff；分阶段提交——每阶段独立 commit，全量 pytest（允许既有环境性失败）+ import 兼容验证通过方可进入下一阶段，回滚粒度为阶段。
- daemon 运行安全：结构性重构期间不触发 daemon 重启（不 touch `.fenix/restart_request`）；运行中的 daemon 不受文件重组影响，重启冒烟验证只在收尾阶段且确认时机后执行。

## 溯源

- 2026-09-02 史前复原 — 迁移期已存在的基线：core/ 按组合提取+门面分层组织（agent_runner/pm_engine/verify_engine/worktree_manager/admin_monitor 等子包），门面转发保持既有调用契约，巨文件拆分不改变外部行为
- 2026-09-07 2026-09-07-refactor-core-packages（spec/archive/2026-09-07-refactor-core-packages） — 固化 pm_engine/agent_runner 两巨文件拆包的包结构、状态归属与锁安全（Dispatcher 单锁）、外部 API 兼容不变式、行为等价搬移与分阶段验证纪律
