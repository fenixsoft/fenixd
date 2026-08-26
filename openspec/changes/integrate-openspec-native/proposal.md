# Proposal: 将 openspec 原生集成到 fenix

## Why

fenix 目前依赖外部 openspec 工具链生成 SPEC：npm 全局包 `@fission-ai/openspec` CLI（`new change` / `status` / `instructions` 三个命令）+ `~/.claude/skills/openspec-propose` 等外部 skills。安装 fenix 并不安装 openspec，属于隐式外部依赖；且 openspec-propose 的输出提示「实现就绪后可运行 /opsx:apply」不符合 fenix 的实际运作流程——fenix 的 SPEC 由 fenixd 自动推动实现（注册 STATE.md 后 daemon 自动推进状态机并派发 implementer）。应将 openspec 原生集成进 fenix，用户只需安装 fenix（Python）即可完成 SPEC 生成，并让生成流程的输出对齐 fenix 的开发运作方式。

## What Changes

- **新增原生 spec 生成器** `core/spec_gen.py`：实现 `new change` 脚手架、`status`（artifact 依赖顺序与完成度）、`instructions`（每类 artifact 的模板与指令）三者的 Python 等价能力；spec-driven schema 数据（proposal / design / specs / tasks 的模板与指令）从 openspec 包 vendored 进 fenix。
- **新增 CLI 入口** `bin/fenix_spec.py`：子命令 `new` / `status` / `instructions`，JSON 输出，供 fenix-new skill 调用，替代外部 `openspec` CLI。
- **重写 `fenix-new` skill 为自包含**：不再调用 openspec-propose 外部 skill，改用原生生成器创建 SPEC；输出文案改为「SPEC \<name\> 已创建并注册，fenixd 会自动拾取并开始实现」，全程不出现 `/opsx:apply` / `openspec` CLI / `openspec-propose`。
- **废弃对 `openspec-apply-change` 的依赖**：fenix 由 fenixd 自动实现，无手动 apply 流程。
- **新增原生归档能力**：`bin/fenix_archive.py` + `fenix-archive` skill，将完成的 change 移动到 `openspec/changes/archive/YYYY-MM-DD-<name>`。
- **`fenix-init` 创建 `openspec/changes/archive/` 目录**。
- 布局保持：`openspec/changes/<name>/` 下 `proposal.md` / `design.md` / `specs/**/spec.md` / `tasks.md` / `.openspec.yaml` 的文件名与目录结构不变（fenix 核心 StateMachine/PMEngine/Dashboard 直接读写，属硬依赖）。

## Capabilities

### New Capabilities
- `native-spec-generation`: fenix 原生 SPEC 生成——`core/spec_gen.py` 提供 `new change` / `status` / `instructions` 等价能力（内嵌 spec-driven schema 模板与指令），`bin/fenix_spec.py` 提供 CLI 入口，替代外部 openspec CLI。
- `spec-archive`: 原生 change 归档——`bin/fenix_archive.py` 将完成的 change 移动到 `openspec/changes/archive/YYYY-MM-DD-<name>`，供 fenix-archive skill 调用。

### Modified Capabilities
<!-- 无既有 specs，全部为新增 -->

## Impact

- `core/spec_gen.py`（新增）：schema 数据加载、change 脚手架、artifact 状态计算、instructions 解析。
- `schemas/spec-driven/`（新增，vendored）：`schema.yaml` + `templates/{proposal,design,spec,tasks}.md`（自 openspec 包复制，MIT）。
- `bin/fenix_spec.py`（新增）：CLI 入口。
- `bin/fenix_archive.py`（新增）：归档命令。
- `skills/fenix-new/SKILL.md`（修改）：自包含生成流程 + fenix 流程文案。
- `skills/fenix-archive/SKILL.md`（新增）：归档 skill。
- `fenix-init`（修改）：创建 `openspec/changes/archive/`。
- 依赖：移除对 npm `@fission-ai/openspec` 与 openspec-propose/apply-change 等外部 skills 的依赖；无新增 Python 依赖。
- 测试：`tests/test_core.py` / `tests/test_spec_gen.py`（或并入 test_core）新增 spec_gen 与 archive 单测。
