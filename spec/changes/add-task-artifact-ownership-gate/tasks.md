## Deliverables

```yaml
- path: core/deliverables.py
  kind: modify
- path: core/artifact_ownership.py
  kind: new
- path: skills/fenix-new/SKILL.md
  kind: modify
- path: agents/evolution.md
  kind: modify
- path: tests/test_task_artifact_ownership.py
  kind: new
```

> 说明：`core/artifact_ownership.py` 为实现期选定的归属表载体（design D2 开放问题：可与 `core/deliverables.py` 常量块二选一）；若实现期并入 `core/deliverables.py`，则从本段删除该条并在 1.x 说明，其余条目不变。`.fenix/core` 为指向主树 `core/` 的符号链接，代码改动即时生效、无需重启 daemon。

## 1. 产物归属表（D2）

- [ ] 1.1 新建 `core/artifact_ownership.py`：声明式常量 `VERIFICATION_ARTIFACT_OWNERS`（产物路径标识 → 归属车道集合），至少覆盖六条——`test_scenarios.json` → `{"planner-plan","fast-track"}`；`scenarios.json` → `{"pm_engine","fast-track"}`；`report.json` → `{"verify_engine"}`；`verify-progress/<spec>/.fenix-run-result.json` → `{"planner-judge"}`；`.fenix/verify-progress/<spec>/`（目录级持久化引用）→ `{"planner-plan","pm_engine","verify_engine","planner-judge","fast-track"}`；worktree 根 `.fenix-run-result.json` → `{"implementer","fast-track"}`。**验证链产物归属集合 MUST NOT 含 `implementer`**。附：产物路径标识匹配常量、代码文件特征常量（代码扩展名 + 代码路径特征）、**产出动词常量**（写/落盘/持久化/保存/落位/序列化/追加）
- [ ] 1.2 同文件导出单一判定入口 `ownership_violations_for_task_line(line: str, lane: str) -> list[str]`（返回违规描述；无违规返回空列表），供 lint 与起草自检复用；纯函数、零 IO、异常不外抛。判据按 design D1 三重合取：①路径限定到 `.fenix/verify-progress/` 的**已登记核心产物**引用，或该目录自身的持久化引用；②把命中产物字面量遮蔽后行内无代码文件特征；③引用前有产出动词且 `lane ∉ 归属集合`。**裸 `test_scenarios.json`/`scenarios.json`/`report.json` 字面量与裸 `.fenix-run-result.json`（worktree 根收工票据）MUST NOT 触发违规；未登记侧车（`tokens.json`/`fail_history.json` 等）MUST NOT 触发违规**

## 2. lint 规则接入（D1/D3/D4）

- [ ] 2.1 `core/deliverables.py` `lint_tasks_text`：在既有分组/任务行计数判定通过（未提前返回可解析性违规）后追加产物归属校验——逐条扫描符合 `_TASKS_ITEM_RE` 的任务行，命中 design D1 三重合取判据时追加违规消息（含任务行 id/原文摘要与所命中产物路径）。三条件 MUST 为合取（仅命中其一放行）；裸产物字面量与未登记侧车 MUST NOT 触发；可解析性违规已提前返回时不必再跑本校验（短路语义与现状一致）
- [ ] 2.2 `core/deliverables.py` 新增执行车道判定 `_resolve_lane_for_spec_dir(spec_dir) -> str`：复用既有 `core/spec_mode.py:read_spec_mode`（MUST NOT 自实现第二套 `.spec.yaml`/YAML 解析），`fast-track` → `fast-track`，其余/缺失/读取异常 → `full`（保守侧，design D3）；在 `lint_tasks_text` 之外提供「读文件取车道」的薄封装（`lint_tasks_text` 保持纯文本签名不变，车道由调用侧经新增可选参数或独立入口传入——实现期取侵入最小者）
- [ ] 2.3 违规消息给出纠正处方：改写为「实现 X 让框架产出该文件」或移出任务书（reference / `.fenix/todo.md` 人工步骤），措辞与 `skills/fenix-new` §3.2.1 表格一致

## 3. 三个挂点一致生效验证（D4）

- [ ] 3.1 核对 `_lint_tasks_parseable`（`core/pm_engine/promotion.py`）、`_tasks_md_relint_from_branch` 与 `_tasks_md_relint_from_worktree`（`core/pm_engine/verification/branch_guard.py`）三个挂点均经 `lint_tasks_text` 进入新规则；若 `lint_tasks_text` 签名变更，三处调用点同步传入车道（或改用新入口），MUST NOT 各自实现判据

## 4. 起草指引同步（D5）

- [ ] 4.1 `skills/fenix-new/SKILL.md` §3.2.1：四类「Agent 做不到的事」表格新增第 5 类「需产出他车道产物」（典型写法：要求把 `test_scenarios.json`/`scenarios.json`/`report.json`/`.fenix/verify-progress/` 产物写出来；做不到的原因：该文件由验证链车道产出，实现者交付时尚不存在），并在「正确做法」补一条（改写为「实现 X 让框架产出该文件」或移出任务书）；§3.3 自检脚本注释同步说明新规则
- [ ] 4.2 `agents/evolution.md`：自进化草稿格式契约段同步第 5 类禁止项（与 §3.2.1 同语义），确保自进化起草入口同源

## 5. 测试

- [ ] 5.1 新建 `tests/test_task_artifact_ownership.py`：判据矩阵——要求实现者持久化他车道产物（路径限定 + 产出动词 + 无代码文件）判违规 / 写代码让框架产出该文件放行 / 裸 `report.json` 与裸 `.fenix-run-result.json` 放行 / 写入未登记侧车（如 `scenario_reroute_stoploss.json`）放行 / 与验证产物无关的任务放行
- [ ] 5.2 同文件：执行车道比对——full（含 mode 缺失）判违规 / `mode: fast-track` 下 `test_scenarios.json` 合法、`report.json` 仍判违规 / `.spec.yaml` 读取异常保守按 full
- [ ] 5.3 同文件：归属表断言——含六条核心产物条目（含目录级条目）且验证链产物归属集合不含 `implementer`
- [ ] 5.4 同文件：零误拦回归——对 `spec/changes/` 与 `spec/archive/` 下全部 tasks.md 运行 `lint_tasks_text`，既有合法 spec 均无产物归属违规（复用本次实测的 260 份基线；测试内动态扫描，MUST NOT 硬编码文件数）
- [ ] 5.5 同文件：fail-open——lint 自身故障返回空违规清单、不抛异常

## 6. 收尾

- [ ] 6.1 运行有界全量套件 `python3 bin/run_full_suite.py --timeout 3600`，修复回归；对照 HEAD 基线区分存量失败
- [ ] 6.2 写 `.fenix-run-result.json`（含 `completed_tasks`）；本 run 的**交付物不含任何验证链产物**——场景集与验证报告由验证链车道独立产出，实现者不得代造（该约束由本 SPEC 新增的晋升门规则机械保证）
- [ ] 6.3 事故真阳性回归钉：`spec/changes/fix-verify-serving-disk-reclaim/tasks.md` 6.2（历史事故任务行）在新判据下判违规，作为端到端锚点（只读断言，MUST NOT 改写该 SPEC 文件）
