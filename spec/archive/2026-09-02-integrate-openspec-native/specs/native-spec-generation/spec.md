## ADDED Requirements

### Requirement: 原生 change 脚手架

系统 SHALL 通过 `core/spec_gen.new_change` 创建 change：在 `spec/changes/<name>/` 下建立目录并写入 `.spec.yaml`（含 `schema: spec-driven` 与创建日期）。名称 SHALL 为 kebab-case；同名 change 已存在时 SHALL 返回错误而不覆盖。

#### Scenario: 创建新 change

- **WHEN** 调用 `new_change(project_root, "add-user-login")`
- **THEN** 生成 `spec/changes/add-user-login/.spec.yaml`，内容含 `schema: spec-driven`，返回路径

#### Scenario: 同名 change 已存在

- **WHEN** `spec/changes/add-user-login/` 已存在时再次调用 `new_change(project_root, "add-user-login")`
- **THEN** 返回错误，且不覆盖已有目录内容

#### Scenario: 非 kebab-case 名称被拒绝

- **WHEN** 调用 `new_change(project_root, "Add User Login")`
- **THEN** 返回错误并提示需使用 kebab-case 名称

### Requirement: Artifact 状态计算

系统 SHALL 通过 `core/spec_gen.status` 计算 change 的 artifact 完成状态：`done` = 对应 `generates` 文件已存在（`specs/**/*.md` 以 `specs/` 下存在任意 `.md` 判定）；`ready` = 全部依赖已完成；`blocked` = 存在未完成依赖并列出 `missingDeps`。输出 SHALL 与 openspec `status --json` 同构，包含 `changeName`、`schemaName`、`isComplete`、`applyRequires`（`["tasks"]`）与 `artifacts` 列表。

#### Scenario: 空 change 的初始状态

- **WHEN** 对仅含 `.spec.yaml` 的新 change 调用 `status`
- **THEN** `proposal` 为 `ready`，`specs`/`design` 为 `blocked`（missingDeps=[proposal]），`tasks` 为 `blocked`（missingDeps=[specs, design]），`isComplete` 为 false

#### Scenario: 全部 artifact 完成后 apply 就绪

- **WHEN** `proposal.md`、`design.md`、`specs/` 下 spec.md、`tasks.md` 均已写入
- **THEN** 所有 artifact 为 `done`，`isComplete` 为 true，`applyRequires` 为 `["tasks"]`

### Requirement: Instructions 解析

系统 SHALL 通过 `core/spec_gen.instructions` 返回指定 artifact 的生成指引：`outputPath`、`description`、`instruction`、`template`（vendored 模板文件内容）与 `dependencies`（已完成依赖文件的绝对路径）。

#### Scenario: 返回 proposal 指引

- **WHEN** 对 change 调用 `instructions(project_root, "proposal", name)`
- **THEN** 返回包含 `proposal.md` 的 `outputPath`、非空 `instruction` 与 `template`（含「## Why」骨架）

#### Scenario: 返回 tasks 指引并含依赖

- **WHEN** `proposal.md`/`design.md`/`specs/**/spec.md` 均已存在时调用 `instructions(project_root, "tasks", name)`
- **THEN** `dependencies` 列出已完成的 proposal/design/specs 文件路径，`template` 为 tasks 模板

### Requirement: CLI 入口 bin/fenix_spec.py

系统 SHALL 提供 `bin/fenix_spec.py` CLI，子命令 `new <name>`、`status --change <name>`、`instructions <artifact-id> --change <name>`，输出 JSON，可在项目 `.fenix/` 环境下独立调用（无需外部 openspec CLI）。

#### Scenario: new 子命令

- **WHEN** 运行 `python3 .fenix/bin/fenix_spec.py new add-user-login`
- **THEN** 创建 change 并输出 JSON 含 `ok` 与 `path`

#### Scenario: instructions 子命令输出模板

- **WHEN** 运行 `python3 .fenix/bin/fenix_spec.py instructions proposal --change add-user-login`
- **THEN** 输出 JSON 含 `template` 字符串，可直接据此写 `proposal.md`

### Requirement: fenix-new 自包含且对齐 fenix 流程

`fenix-new` skill SHALL 使用原生生成器（`bin/fenix_spec.py`）创建 SPEC，不再调用外部 openspec-propose skill 或 openspec CLI。生成并注册 STATE.md 后，输出 SHALL 告知用户「SPEC 已创建并注册，fenixd 会自动拾取并开始实现」，全程不得出现 `/opsx:apply`、`openspec` CLI 或 `openspec-propose` 字样。

#### Scenario: fenix-new 不依赖外部 openspec

- **WHEN** 用户通过 fenix-new 创建 SPEC，环境中未安装 openspec CLI 与 openspec-propose skill
- **THEN** 流程仍通过 `bin/fenix_spec.py` 完整生成 proposal/design/specs/tasks 并注册 STATE.md

#### Scenario: 输出文案符合 fenix 流程

- **WHEN** fenix-new 完成 SPEC 注册
- **THEN** 输出告知 fenixd 将自动拾取实现，且不含 `/opsx:apply` 等 openspec 手动 apply 提示
