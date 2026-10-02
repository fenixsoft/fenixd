<!-- knowledge: capability=task-artifact-ownership-gate rev=1 sources=spec/archive/2026-09-23-add-task-artifact-ownership-gate -->

# 任务产物归属门

tasks.md 任务行的产物归属校验：验证链产物只能由其归属车道产出，实现者不得被任务书要求代写他车道的验证产物。

## 现行规则

- 验证产物归属表：框架维护声明式的「验证链产物 → 归属车道」归属表作为单一真相源，lint 侧与起草自检侧共用。登记内容——`.fenix/verify-progress/<spec>/test_scenarios.json` → `planner-plan`（`fast-track` 亦为合法产出车道）；`scenarios.json` → pm_engine 持久化写侧（`fast-track` 亦合法）；`report.json` → `verify_engine`；`<vp_dir>/.fenix-run-result.json` → `planner-judge`；`.fenix/verify-progress/<spec>/` 目录级持久化引用 → `planner-plan`/`pm_engine`/`verify_engine`/`planner-judge`/`fast-track`；`<worktree>/.fenix-run-result.json` → `implementer`/`fast-track`（实现者自己的收工票据，合法交付）。`implementer` 不被登记为任何验证链产物的归属车道；未登记的侧车文件（`tokens.json`/`fail_history.json`/`warning_streaks.json` 等）不参与违规判定。
- 任务行校验判据（`lint_tasks_text` 内，三条件同时满足才判违规，零误拦取向）：①任务行命中已登记验证链产物的产出式引用（路径限定到 `.fenix/verify-progress/…` 且为归属表登记的核心产物之一，或 verify-progress 目录自身的持久化引用）；②该引用处未指向任何代码文件（遮蔽产物字面量后行内不出现代码扩展名 `.py`/`.ts`/`.tsx`/`.js`/`.jsx`/`.sh`/`.yaml`/`.yml` 或已知代码路径特征 `core/`/`agents/`/`tests/`/`bin/`/`skills/`/`docs/`）；③引用前出现产出动词（写/落盘/持久化/保存/落位/序列化/追加）且执行车道不在该产物归属车道集合内。
- 合法形态放行：「写代码让框架产出该文件」的任务（行内含代码文件）；裸 `test_scenarios.json`/`scenarios.json`/`report.json` 字面量引用（如 spec 目录下场景定义件、兼容解析语义，与 verify-progress 内同名文件是不同文件）；裸 `.fenix-run-result.json`（实现者/fast-track 自己的收工票据）；未登记侧车产物。
- 执行车道判定：按 `.spec.yaml` 的 `mode` 判定，复用既有 `core/spec_mode.py:read_spec_mode`（不另实现第二套 YAML 解析）；`mode` 缺失或不可解析时保守按 `full`（执行车道 = `implementer`）。full 车道下「要求实现者产出验证产物」恒判违规；fast-track 车道下自行出题落盘 `test_scenarios.json`/`scenarios.json` 合法，对 `report.json`/planner-judge 结果文件仍判违规。
- 三个 lint 挂点一致生效：晋升门（drafted → ready）、full 车道收口复检（`_tasks_md_relint_from_branch`）、fast-track 车道收口复检（`_tasks_md_relint_from_worktree`）复用 `lint_tasks_text` 单一实现，不各自实现判据。
- fail-open 与零误拦：校验自身故障时记 warning 返回空违规清单，不阻塞晋升/收口；`mode` 读取异常保守按 `full` 处理而非跳过校验。规则以存量回归验证零误拦（对 `spec/changes/` 与 `spec/archive/` 全部 tasks.md，既有合法 spec 均不产生违规）。
- 违规消息给出纠正处方：改写为「实现 X 让框架产出该文件」或移出任务书（reference / `.fenix/todo.md` 人工步骤）。

## 溯源

- 2026-09-23 2026-09-23-add-task-artifact-ownership-gate（spec/archive/2026-09-23-add-task-artifact-ownership-gate） — 确立归属表单一真相源、任务行三条件判据、mode 车道比对、三挂点同源与 fail-open 语义
