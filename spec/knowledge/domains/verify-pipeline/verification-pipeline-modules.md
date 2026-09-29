# 验证管线模块化结构
<!-- knowledge: capability=verification-pipeline-modules rev=1 sources=spec/archive/2026-09-21-refactor-verification-module -->

验证管线的模块组织契约：按职责分模块、模块边界即能力边界，依赖显式注入、改动不跨层直插。

## 现行规则

- 分层模块组织：验证管线按职责分模块组织——场景引擎侧为 engine/browser/assertions/scenarios/visual_diff 等模块，模块边界即能力边界，改动不跨层直插。
- pm_engine 验证流水线子包化：`core/pm_engine/verification/` 为按职责拆分的子包，子模块含 `pipeline`、`serving`、`scenario_gate`、`verdict_evidence`、`judge_gate`、`escalation`、`infra_classify`、`legacy`、`branch_guard`、`report_gate`，各自只承载单一职责域（如 serving 只管被测应用服务供给，不含裁决证据或 judge 门禁逻辑）；巨型单文件不存在，任一子模块不超过 1500 行。
- PipelineContext 显式依赖注入：`VerificationPipeline` 及其子组件通过显式 `PipelineContext` 访问外部依赖（logger、project_root、state_machine、配置读取、升级通知、派发入队），不直接回引门面私有方法（`self._pm._<private>` 零命中）。
- 门面与调用方兼容：`from core.pm_engine.verification import VerificationPipeline` 及既有公开符号（`reclassify_infra_rounds`、`resolve_env_blocked_reset_path`、`VerdictReadResult`、`_branch_merged_into_tree`、`_SCENARIO_REPAIR_MAX_ROUNDS`、`_MAX_JUDGE_RERUNS` 等）保持可用；engine.py 门面委托与既有测试引用路径零改动；`VerificationPipeline(pm)` 构造签名向后兼容。
- 模块级名字 patch 语义保持：既有测试以 `patch("core.pm_engine.verification.<name>")` 替换的模块级名字（`subprocess`、`ensure_main_tree_deps`、`run_prepare_steps`、`load_verify_contract`、`rewrite_scenarios_origin`）拆分后仍可被同一路径命中（子模块调用点经包命名空间或共享模块延迟解析）；确实无法保持者须显式列入例外清单上报裁决，不静默改测试。
- 结构重构纪律：纯结构性搬移零行为变化（发现的缺陷只记疑点清单，不顺手修）；依赖注入先于模块搬移，两阶段各自独立 commit（可独立回滚）；任务与交付物以方法名/模块名锚定，不用绝对行号；分组表覆盖全部方法无未归属项。
- 格式化收口独立：全部结构性拆分完成后，以独立 commit 对 `core/`、`bin/`、根 `fenixd.py` 的 `*.py` 统一格式化，不触及 `agents/`、`docs/`、`spec/` 与任何 `*.md`，格式化提交不混入逻辑改动。

## 溯源

- 史前复原（存量基线） — 验证管线按 engine/browser/assertions/scenarios/visual_diff 分模块组织，模块边界即能力边界，改动不跨层直插
- [2026-09-21 refactor-verification-module](spec/archive/2026-09-21-refactor-verification-module/) — 将 6304 行单文件 verification.py 拆为职责子包并引入 PipelineContext 显式注入，固化门面兼容、patch 语义保持与两阶段重构纪律
