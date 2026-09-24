## ADDED Requirements

### Requirement: 从选中问题生成修复 SPEC

系统 SHALL 支持把选中的 code-review 问题条目机械合成为一个修复 SPEC，复用框架既有的草稿材料化 / 同源 lint / 注册链路，MUST NOT 自实现第二套 SPEC 生成器。

- 生成器 MUST 复用 `core/deliverables.lint_declared` / `lint_tasks_parseable` 做同源 lint 预检。
- SPEC 目录 MUST 落在 `spec/changes/<name>/`，含 `proposal.md` / `design.md` / `tasks.md` / `specs/<capability>/spec.md` / `.spec.yaml`。
- 所有被选条目的 `file` MUST 作为 `## Deliverables` 声明段的 `modify`（若文件已存在于主树）；tasks.md MUST 内联各条目的 `title` 与 `file:line`。
- 注册 MUST 经 `StateMachine.add_spec(name, {"status": "drafted", "priority": 5})`，MUST 立即进入调度（不写 `start_after`）。
- 生成后 MUST 把对应条目置为 `in_spec` 并写入 `spec_name`。
- 生成失败（lint 不通过 / 名称冲突无法消解 / 落盘失败）时 MUST NOT 半写，MUST 返回明确错误且 MUST NOT 改变条目状态。

#### Scenario: 成功生成修复 SPEC

- **WHEN** 用户选中 3 条 `file` 为 `core/a.py`、`core/b.py`、`core/c.py` 的 open 问题并触发生成
- **THEN** MUST 在 `spec/changes/` 下生成一个含 Deliverables（三个 modify）的草稿 SPEC，lint 预检 OK，注册为 `drafted`，三条问题置 `in_spec` 且记录该 SPEC 名

#### Scenario: lint 不通过不半写

- **WHEN** 生成的 tasks.md 声明段存在 lint 违规
- **THEN** MUST NOT 落盘部分文件，MUST 返回错误，条目状态 MUST 保持 `open`

### Requirement: 修复 SPEC 命名消解

生成的修复 SPEC 名 SHALL 采用 `fix-cr-<slug>` 基名，并做冲突消解，MUST NOT 与既有 change / 归档 change / STATE 条目重名。

- `<slug>` MUST 由选中问题推导（如首个问题的分类或短标题），且 MUST 满足 kebab-case（`^[a-z0-9][a-z0-9-]*$`）。
- 基名冲突时 MUST 追加短指纹后缀（如 `-<fingerprint[:6]>`）后重试全部三处判重；仍冲突 MUST 返回错误（不覆盖）。
- 判重范围 MUST 覆盖 `spec/changes/<candidate>`、STATE.md 既有条目名、`spec/archive/*-<candidate>` 三处（与 evolution `resolve_spec_name` 同源口径）。

#### Scenario: 首次生成用基名

- **WHEN** 无同名 change，选中问题推导 slug 为 `unused-import`
- **THEN** 生成的 SPEC 名 MUST 为 `fix-cr-unused-import`

#### Scenario: 重名追加后缀

- **WHEN** `spec/changes/fix-cr-unused-import` 已存在
- **THEN** 生成器 MUST 追加短指纹后缀（如 `fix-cr-unused-import-abc123`）并重新判重，MUST NOT 覆盖既有目录

### Requirement: 生成入口的并发与幂等

生成接口 SHALL 对并发与重复请求保持安全。

- 同一批 `item_ids` 重复提交且首次已成功时，MUST 幂等返回既有结果（不重复生成第二个 SPEC）。
- 已被置为 `in_spec` / `resolved` / `ignored` 的条目 MUST NOT 再次参与生成。
- 生成过程 MUST NOT 因单个条目缺字段而整批失败——缺关键字段（如 `file`）的条目 MUST 被跳过并计入返回的 `skipped`。

#### Scenario: 重复提交幂等

- **WHEN** 用户对同一批已成功生成 SPEC 的条目再次提交生成
- **THEN** MUST NOT 生成第二个 SPEC，MUST 返回既有 SPEC 名

#### Scenario: 跳过非 open 条目

- **WHEN** 提交的 `item_ids` 中含一条已 `in_spec` 的条目
- **THEN** 该条目 MUST 被计入 `skipped`，其余 open 条目正常生成
