# Tasks: add-declaration-premechanize

## Deliverables

```yaml
- path: core/deliverables.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: schemas/spec-driven/schema.yaml
  kind: modify
- path: skills/fenix-new/SKILL.md
  kind: modify
- path: tests/test_deliverable_declaration_premechanize.py
  kind: new
```

## 1. PR1 分类器与软化编排（core/deliverables.py）

- [x] 1.1 新增 `_path_is_outside_root(project_root, candidates)`：候选路径逐个 `expanduser` → `abspath` → 与 resolve 后的 project_root 做前缀判定（`relative_to`，`..` 已消解），任一不在根内返回 True；解析异常 fail-open 返回 False
- [x] 1.2 新增 `classify_unsatisfiable(entry, project_root)`：`kind ∈ {new, modify}` 且（`_path_is_gitignored` 或 `_path_is_outside_root` 命中）返回 True；`reference` 恒 False；entry 缺 path/kind 返回 False
- [x] 1.3 新增 `soften_unsatisfiable_declarations(spec_dir, project_root) -> list`：`extract_declared_entries` 逐条 `classify_unsatisfiable`，命中即 `soften_declared_kind(spec_dir, element)`；单条异常跳过记 warning 不中断；返回 `[{element, kind_before, kind_after}]`；无声明段早退返回 []
- [x] 1.4 回归测试：gitignored modify/new 软化、`~`/`../` 仓库外软化、reference 不动、占位符/目录/疑似笔误 new 不动、无声明段早退、单条改写异常跳过

## 2. PR2 晋升接线（core/pm_engine/engine.py）

- [x] 2.1 `_on_spec_drafted` 在 `_lint_deliverable_declarations` 之前调用 `soften_unsatisfiable_declarations`（spec_dir = `spec/changes/<name>`），软化非空时 logger.info 含 spec 名与软化清单
- [x] 2.2 软化非空时写 `DisputeAuditStore` 审计（spec、`trigger_run_id: ""`、`judge_run_id: ""`、verdicts 含 `{element, verdict: "reference", reasoning: "promotion-soften: <gitignored|outside-root>"}`、diff 前后声明段）；写失败 warning 非阻塞
- [x] 2.3 软化编排自身异常捕获降级 warning，晋升流程继续走既有 lint 判定（fail-safe，不产生新卡死形态）
- [x] 2.4 回归测试：gitignored modify 声明 spec 晋升后状态 ready 且 tasks.md 已软化；审计含 promotion-soften；占位符 spec 照旧 drafted+error

## 3. PR3 lint 规则 6 仓库外路径（core/deliverables.py）

- [x] 3.1 `lint_declared` 新增规则 6：`kind: new/modify` 候选路径经 `_path_is_outside_root` 判 True 时返回违规，消息含路径与「仓库外路径不可作为 new/modify 交付物，应声明 reference 或改为仓库内路径」；仓库外 reference 放行
- [x] 3.2 fail-open 保持：规则 6 仅增量判定，异常沿用既有「返回空清单放行」语义
- [x] 3.3 回归测试：`~/x` new 与 `../y` modify 违规且消息含处方文案、仓库外 reference 放行、规则 5 与规则 6 并列共存不互相遮蔽

## 4. PR4 守卫缺件确定性预分类（core/pm_engine/dispatch.py）

- [x] 4.1 `_adjudicate_deliverable_missing` 入口（组装 judge 输入之前）读取声明段 entries，partition 缺件：`classify_unsatisfiable` 命中的进 deterministic 清单；声明段无该条目（存量正则提取）不预分类
- [x] 4.2 deterministic 非空：逐条 `soften_declared_kind`（单条异常留在 missing 清单并 warning）→ `DisputeAuditStore.append`（reasoning 前缀 `guard-preclassify`，diff 前后声明段）→ 重跑 `self._pm._deliverable_gate_missing(spec_name, result)`
- [x] 4.3 重跑全清 → 走既有「裁决执行后守卫重跑通过」放行分支（恢复 in-flight、放行 merge），不派 `dispute-judge-` run；仍有剩余 → 剩余项作为 missing 进入既有 dispute-judge 流程（judge 输入只含剩余项）
- [x] 4.4 回归测试：全命中确定性模式不派 judge 且软化+放行；混合缺件 judge 输入仅含剩余项；预分类异常全量回退既有 judge 流程

## 5. PR5 产出期教学与部署副本同步（schemas/spec-driven/schema.yaml + skills/fenix-new/SKILL.md）

- [x] 5.1 schema.yaml tasks 工件 instruction 追加四类不可交付模式表：dist/构建产物 → 锚点文件 + `reference`；gitignored 路径 → 禁 `new/modify`；`~`/仓库外路径 → 禁 `new/modify`；`.fenix/` 运行时文件 → `reference`
- [x] 5.2 `skills/fenix-new/SKILL.md` §3.2 tasks 指引注入同表（措辞与 schema 一致），注明「daemon 晋升时对命中条目机械软化并审计留痕」
- [x] 5.3 部署副本同步（**merge-back 后于主树执行**，worktree 内 `.fenix` 为运行时目录断链、不在 worktree 内同步）：`cp core/deliverables.py .fenix/core/deliverables.py`、`cp schemas/spec-driven/schema.yaml .fenix/schemas/spec-driven/schema.yaml`（.fenix 为 gitignore 运行时目录，不入库）
- [x] 5.4 回归测试：`instructions tasks` 输出含四类模式关键词；SKILL.md 含四类模式表

## 6. PR6 收尾与全量回归

- [x] 6.1 全量回归：tests/test_deliverable_lint.py、tests/test_deliverable_gate.py、tests/test_deliverable_declaration_triage.py、tests/test_deliverable_declaration_premechanize.py 及相邻 pm_engine 套件全绿
- [x] 6.2 行为自检：构造「gitignored modify 声明 spec」干跑晋升链路（软化 → lint 通过 → ready）与「混合缺件」干跑守卫链路（软化子集 → judge 仅剩余项），确认无静默放行、审计可复核、防洗白重跑闸门在场
