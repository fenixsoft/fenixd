# 原生 SPEC 生成（native-spec-generation）

<!-- knowledge: capability=native-spec-generation rev=1
     sources=spec/archive/2026-09-02-integrate-openspec-native -->

不依赖外部 openspec 工具链的 SPEC 生成器，提供 change 脚手架、artifact 状态计算与生成指引三件套。

## 规则

- SPEC 生成单源为 `core/spec_gen.py`，经 `bin/fenix_spec.py` CLI 驱动；fenix-new skill 自包含调用该链路，不依赖外部 openspec CLI、openspec-propose 与 openspec-apply-change。
- change 脚手架（`spec_gen.new_change`）：在 `spec/changes/<name>/` 下建立目录并写入 `.spec.yaml`（含 `schema: spec-driven` 与创建日期）；名称须为 kebab-case；同名 change 已存在时返回错误且不覆盖已有目录内容。
- artifact 状态计算（`spec_gen.status`）：`done` = 对应 generates 文件已存在（`specs/**/*.md` 以 `specs/` 下存在任意 `.md` 判定）；`ready` = 全部依赖已完成；`blocked` = 存在未完成依赖并列出 `missingDeps`。输出与 openspec `status --json` 同构，含 `changeName`、`schemaName`、`isComplete`、`applyRequires`（`["tasks"]`）与 `artifacts` 列表。
- 生成指引解析（`spec_gen.instructions`）：返回指定 artifact 的 `outputPath`、`description`、`instruction`、`template`（vendored 模板文件内容）与 `dependencies`（已完成依赖文件的绝对路径）。
- CLI 子命令为 `new <name>`、`status --change <name>`、`instructions <artifact-id> --change <name>`，输出 JSON，可在项目 `.fenix/` 环境下独立调用，无需任何外部 CLI。
- fenix-new 生成并注册 STATE.md 后，输出告知用户「SPEC 已创建并注册，fenixd 会自动拾取并开始实现」；文案全程不出现 `/opsx:apply`、`openspec` CLI 或 `openspec-propose` 字样。
- SPEC 文件布局固定为 `spec/changes/<name>/` 下的 `proposal.md`、`design.md`、`specs/**/spec.md`、`tasks.md`、`.spec.yaml`；fenix 核心 StateMachine/PMEngine/Dashboard 直接读写该布局，属硬依赖。

## 溯源

- 史前基线（归档前已生效）：spec 骨架与 tasks.md 由 core/spec_gen.py 原生生成，经 bin/fenix_spec.py CLI 驱动；fenix-new skill 自包含调用该链路。
- 2026-09-02 2026-09-02-integrate-openspec-native（spec/archive/2026-09-02-integrate-openspec-native） — 确立原生 change 脚手架、artifact 状态计算、instructions 解析、CLI 契约与 fenix-new 自包含文案约束，移除外部 openspec CLI 与 openspec-propose 依赖。
