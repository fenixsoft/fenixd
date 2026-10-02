# 审查发现转修复 SPEC 生成

<!-- knowledge: capability=code-review-spec-generation rev=1
     sources=spec/archive/2026-09-24-add-code-review-agent-and-quality-tab -->

把选中的审查问题条目机械合成为一个修复 SPEC：复用框架既有的草稿材料化 / 同源 lint / 注册链路，不自实现第二套 SPEC 生成器。

## 规则

- 生成器复用 `core/deliverables.lint_declared` / `lint_tasks_parseable` 做同源 lint 预检；SPEC 目录落在 `spec/changes/<name>/`，含 `proposal.md` / `design.md` / `tasks.md` / `specs/<capability>/spec.md` / `.spec.yaml`。
- 所有被选条目的 `file` 作为 `## Deliverables` 声明段的 `modify`（文件已存在于主树时）；tasks.md 内联各条目的 `title` 与 `file:line`。
- 注册经 `StateMachine.add_spec(name, {"status": "drafted", "priority": 5})`，立即进入调度（不写 `start_after`）。
- 生成成功后对应条目置 `in_spec` 并写入 `spec_name`。
- 生成失败（lint 不通过 / 名称冲突无法消解 / 落盘失败）不半写：返回明确错误，条目状态保持 `open`。
- SPEC 名基名为 `fix-cr-<slug>`：`<slug>` 由选中问题推导（如首个问题的分类或短标题），满足 kebab-case（`^[a-z0-9][a-z0-9-]*$`）。
- 判重范围覆盖 `spec/changes/<candidate>`、STATE.md 既有条目名、`spec/archive/*-<candidate>` 三处（与 evolution `resolve_spec_name` 同源口径）。
- 基名冲突时追加短指纹后缀（`-<fingerprint[:6]>`）后重试全部三处判重；仍冲突返回错误，不覆盖既有目录。
- 幂等：同一批 `item_ids` 重复提交且首次已成功时，返回既有 SPEC 名，不生成第二个 SPEC。
- 已 `in_spec` / `resolved` / `ignored` 的条目不再参与生成，计入返回的 `skipped`。
- 生成过程不因单个条目缺关键字段（如 `file`）整批失败：缺字段条目被跳过并计入 `skipped`，其余 open 条目正常生成。

## 溯源

- 2026-09-24 add-code-review-agent-and-quality-tab（spec/archive/2026-09-24-add-code-review-agent-and-quality-tab） — 新建生成能力：复用既有链路机械合成与失败不半写、fix-cr 命名三处判重与短指纹后缀消解、幂等返回与 skipped 语义。
