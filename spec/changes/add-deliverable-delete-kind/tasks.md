## Deliverables

```yaml
- path: core/deliverables.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: schemas/spec-driven/schema.yaml
  kind: modify
- path: skills/fenix-new/SKILL.md
  kind: modify
- path: tests/test_deliverable_delete_kind.py
  kind: new
- path: tests/test_deliverable_gate.py
  kind: modify
```

## 1. 声明 schema 扩展

- [x] 1.1 `core/deliverables.py`：`_DECLARED_KINDS` 由 `("new", "modify", "reference")` 扩为 `("new", "modify", "delete", "reference")`，更新紧邻的语义注释（`delete`=让该路径在合并后不存在，仅限入库文件，守卫反判存在性）。
- [x] 1.2 `core/deliverables.py::extract_declared`：归类键由 `kind in ("new", "modify")` 改为 `kind in ("new", "modify", "delete")` → `deliverables`；`reference` → `references`。同步更新函数 docstring 与模块头部的 two-bucket 说明。
- [x] 1.3 `core/deliverables.py::extract_declared_entries`：docstring 中 `kind ∈ new/modify/reference` 的枚举声明同步为四值。

## 2. 晋升 lint 新规则与软化排除

- [x] 2.1 `core/deliverables.py::lint_declared`：新增 `kind: delete` 的四类拒绝——路径被 gitignore 排除（复用既有 `_path_is_gitignored`）／主树不存在／是目录（复用既有目录判定形态）／仓库外（复用 `_path_is_outside_root`）。违规消息 MUST 含路径、命中规则与处方；gitignored 一条的处方须明示「运行时文件的删除不进 Deliverables 段，由人工在主树执行」。
- [x] 2.2 `core/deliverables.py::lint_declared`：更新函数 docstring 的规则清单，把新增的四类 delete 约束写入规则说明（与既有规则 1–6 同格式）。
- [x] 2.3 `core/deliverables.py::classify_unsatisfiable`：`kind: delete` 条目 MUST 恒返回 False（不参与软化），并在 docstring 中写明理由（软化的语义是降级为仅审计，对 delete 即等于删除要求静默消失）。
- [x] 2.4 `core/deliverables.py::soften_unsatisfiable_declarations` 与 `soften_declared_kind`：在软化入口再加一道 `kind == "delete"` 的显式跳过（防御性，即使上游 classify 已拦；审计留痕说明跳过原因）。

## 3. 守卫反判与返回结构

- [x] 3.1 `core/pm_engine/verification.py::_deliverable_gate_missing`：返回类型由 `list[str]` 改为 `list[dict]`，每项 `{"path": str, "kind": str, "violation": "missing"|"undeleted"}`。`new`/`modify` 维持「分支 HEAD 无该 blob 即 missing」；`delete` 反判「分支 HEAD 仍有该 blob 即 undeleted」。
- [x] 3.2 `core/pm_engine/verification.py::_deliverable_gate_missing`：更新 docstring（判定基准、两类 violation 的语义、返回结构变更及下游消费点），并保留 `references` 软校验的既有审计分支不变。
- [x] 3.3 `core/pm_engine/verification.py`：检索本文件内 `_deliverable_gate_missing` 的其他调用点（若有），同步适配新返回结构。

## 4. 处置链按 kind 分化

- [x] 4.1 `core/pm_engine/dispatch.py`：4 个 `_deliverable_gate_missing` 消费点（收工守卫判定、dispute 匹配、LLM 终审入口、重派路径）全部适配 `list[dict]`，从条目中取 `path` 用于既有匹配逻辑（dispute 仍按路径匹配，不因 kind 失效）。
- [x] 4.2 `core/pm_engine/dispatch.py::_deliverable_redispatch`（缺件打回/重派）：error 文案按 `violation` 分化——`undeleted` 用「未删除」语义、`missing` 保持「缺件」语义；两类均含路径，blocked 阈值与重试计数逻辑不变。
- [x] 4.3 `core/pm_engine/dispatch.py::_adjudicate_deliverable_missing`：judge 裁决机械执行时，对 `kind: delete` 条目拒绝 `reference` 归宿——命中即改写为 `unclear`、不软化声明段、审计记录保留 judge 原始 verdict 与改写事实；`typo`/`missing` 出口行为不变。
- [x] 4.4 `core/pm_engine/dispatch.py`：守卫缺件确定性预分类（`guard-preclassify`）MUST NOT 软化 `kind: delete` 条目，该条目保留在待处置清单进入后继流程。
- [x] 4.5 `core/pm_engine/dispatch.py`：LLM 终审 judge 输入中的违规清单改为携带 kind 的结构化条目，使 judge 能看到「该路径应被删除」而非仅看到缺件路径。

## 5. 派发前处方覆盖 delete

- [x] 5.1 `core/agent_runner/prompt_builder.py::_declared_reality_snapshot`：`delete` 条目保留 `kind` 字段；主树不存在时执行既有 basename 候选匹配（把 `kind in ("new", "modify")` 的候选条件扩为含 `delete`）。
- [x] 5.2 `core/agent_runner/prompt_builder.py::_declared_reality_section`：`delete` 条目按其特有语义出词——主树存在 → 「删除目标确认」；主树不存在 → 「无可删，疑似声明笔误」+ 候选；MUST NOT 复用 `modify` 的「修改目标确认」表述。

## 6. 产出期教学双源同改

- [x] 6.1 `schemas/spec-driven/schema.yaml`：tasks 工件的 instruction 文本中，kind 语义段由三值扩为四值（补 `delete` 语义）；不可交付模式表的行内约定由「禁 `new/modify`」改为「禁 `new/modify/delete`」；新增一句明示「`.fenix/` 等 gitignored 运行时文件的删除不能由 SPEC 交付（worktree 内不可达 + 主树只读），须人工在主树执行」。
- [x] 6.2 `skills/fenix-new/SKILL.md`：kind 语义段与不可交付路径模式表同步为四值 + 上述明示；删除或改写任何把「删除目标」引导到 `reference` 的表述。
- [x] 6.3 `schemas/spec-driven/templates/tasks.md`：若其 Deliverables 示例段含 kind 枚举说明，同步为四值（无则跳过并在 tasks 勾选处注明）。

## 7. 测试与回归

- [x] 7.1 新增 `tests/test_deliverable_delete_kind.py`：覆盖 `lint_declared` 对 delete 的四类拒绝与合法 delete 放行；`extract_declared` 的归类（delete 进 deliverables、非法 kind 忽略、同路径保留首见）。
- [x] 7.2 `tests/test_deliverable_delete_kind.py`：覆盖守卫反判——delete 条目在分支 HEAD 仍存在 → 返回 `undeleted`；已不存在 → 无违规；与 `missing` 混合时逐条返回且 kind/violation 一一对应。
- [x] 7.3 `tests/test_deliverable_delete_kind.py`：覆盖防洗白三处——`classify_unsatisfiable`/`soften_*` 不改写 delete；守卫预分类不软化 delete；judge 对 delete 给出 `reference` 时被机械改写为 `unclear` 且声明段未被改写。
- [x] 7.4 `tests/test_deliverable_delete_kind.py`：覆盖派发前处方对 delete 的两种形态（主树存在 → 删除目标确认；主树不存在 → 无可删 + 候选）。
- [x] 7.5 `tests/test_deliverable_gate.py`：既有用例适配 `list[dict]` 返回结构（断言改为从条目取 path/kind/violation），行为预期不变。
- [x] 7.6 运行全量测试 `python3 -m pytest tests/ -q`，修复因返回结构变更或 kind 词表扩展引入的回归，至零失败。

## 验证修复（原地打回第 1 轮）

- [ ] 先复核失败有效性：逐条核对 `spec/changes/add-deliverable-delete-kind/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
