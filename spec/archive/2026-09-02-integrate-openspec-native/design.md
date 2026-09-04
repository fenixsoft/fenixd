# Design: 将 openspec 原生集成到 fenix

## Context

fenix 依赖外部 openspec 工具链生成 SPEC：
- `@fission-ai/openspec` npm 全局包（v1.3.1），提供 `openspec new change` / `openspec status --change --json` / `openspec instructions <artifact> --change --json` 三个命令。
- `~/.claude/skills/openspec-propose` 等外部 skills 驱动生成流程，末尾输出「Run `/opsx:apply` or ask me to implement」——与 fenix 自动实现流程不符。

已确认事实：
- fenix 仅在 SPEC 提案阶段调用 openspec CLI；核心（StateMachine / PMEngine / Dashboard / watcher）只把 `spec/changes/<name>/` 当目录路径直接读写 `proposal.md` / `tasks.md` / `specs/**/spec.md` / `verification-report.md`。
- spec-driven schema 自包含且很小：4 个 artifact，线性依赖 `proposal → specs / design → tasks`，`apply.requires = [tasks]`；模板与指令位于 openspec 包 `schemas/spec-driven/`（MIT）。
- 唯一引用外部 openspec 的位置：`skills/fenix-new/SKILL.md` 步骤 3「调用 openspec-propose skill」。
- fenix 自动实现流程：fenix-new 生成 SPEC + 注册 STATE.md（drafted）→ fenixd 拾取 → 状态机 `drafted→ready→implementing→implemented→testing→verified→done→pushed`（bug-found→implementing），implementer 读 tasks.md 执行。

已确认决策：
- D1 原生 Python 重实现：fenix 内置 spec 生成器，彻底移除 npm openspec 依赖。
- D2 全部融合适配：propose 融入 fenix-new；apply-change 废弃；explore 由 fenix-process 覆盖；新增原生归档命令 + skill。

## Goals / Non-Goals

**Goals:**
- fenix 自包含生成 SPEC：`core/spec_gen.py` + `bin/fenix_spec.py` 提供与 openspec 等价能力，仅需 Python。
- fenix-new skill 不依赖任何外部 openspec skill/CLI，输出对齐 fenix 自动实现流程（不再提 `/opsx:apply`）。
- 提供原生归档能力（`bin/fenix_archive.py` + fenix-archive skill）。
- 保持 `spec/changes/<name>/` 布局与 artifact 文件名完全不变（fenix 核心硬依赖）。
- 无新增 Python 依赖（沿用标准库 + pyyaml）。

**Non-Goals:**
- 不移植 openspec 的全部功能（仅 `new change` / `status` / `instructions` 三个被 fenix 用到的操作）。
- 不做 delta-spec 同步到主 specs（fenix 无 `spec/specs` 主 spec 机制）。
- 不维护 openspec 上游 schema 版本兼容（vendored 固定一份，升级属后续维护）。
- 不自动卸载用户机器上已有的 openspec CLI / openspec-* skills（它们归 openspec 自身管理；fenix 只是不再依赖）。

## Decisions

### D1: Schema 数据 vendoring

将 openspec 包 `schemas/spec-driven/`（`schema.yaml` + `templates/{proposal,design,spec,tasks}.md`，MIT）复制到 fenix 框架根 **`schemas/spec-driven/`**。

解析路径：`core/spec_gen.py` 通过 `Path(__file__).parent.parent / "schemas" / "spec-driven"` 定位框架根。理由：`.fenix/core` 是指向框架安装目录的软链，Python 导入时 `__file__` 解析为真实路径，`parent.parent` 即框架根，无需为 `.fenix` 新增软链或重跑 fenix-init。

替代方案：schema 数据硬编码进 Python 模块 —— 被否决（模板与指令作为数据文件更易维护、与上游 diff 清晰）。

### D2: `core/spec_gen.py` 模块设计

- `SCHEMA_DIR` / `load_schema()`：读取 vendored `schema.yaml`（artifacts 定义 + `apply` 段）。
- `new_change(project_root, name) -> Path`：校验名称 kebab-case；目标已存在则返回错误；创建 `spec/changes/<name>/` 并写 `.spec.yaml`（`schema: spec-driven` / `created: YYYY-MM-DD`）。幂等语义：已存在时报「已存在」，由调用方决定继续或改名的询问。
- `status(project_root, name) -> dict`：对每个 artifact 计算：
  - `done` = 其 `generates` glob 有匹配文件（`specs/**/*.md` 用 `specs/` 下任意 `.md` 存在判定）；
  - `ready` = `requires` 全部 done；
  - `blocked` = `requires` 有未完成，附 `missingDeps`；
  - 输出与 openspec `status --json` 同构：`{changeName, schemaName, isComplete, applyRequires: ["tasks"], artifacts: [{id, outputPath, status, missingDeps}]}`。
- `instructions(project_root, artifact_id, name) -> dict`：查 schema 返回 `{changeName, artifactId, schemaName, changeDir, outputPath, description, instruction, template(文件内容), dependencies(已完成 requires 的绝对路径)}`。
- 复用 `ConfigLoader` 无关；本模块不依赖 daemon，可独立调用。

### D3: `bin/fenix_spec.py` CLI

仿 `bin/fenix_process.py` 模式：脚本头部 `sys.path.insert(0, 框架根)` 后 `from core.spec_gen import ...`。

子命令（argparse）：
- `new <name>` → 打印 JSON `{ok, path, error}`。
- `status --change <name>` → 打印 `status()` JSON。
- `instructions <artifact-id> --change <name>` → 打印 `instructions()` JSON（template 内嵌字符串，供 agent 直接写文件）。

输出 JSON 统一 `--json` 风格（无需 flag，默认 JSON），供 fenix-new skill 以 `python3 .fenix/bin/fenix_spec.py ...` 调用。

### D4: fenix-new skill 重写（自包含 + fenix 流程）

`skills/fenix-new/SKILL.md` 步骤 3 改为「使用 fenix 原生 SPEC 生成器」，流程：

1. `python3 .fenix/bin/fenix_spec.py new <name>`
2. `python3 .fenix/bin/fenix_spec.py status --change <name>` → 依依赖顺序处理
3. 对每个 ready artifact：`python3 .fenix/bin/fenix_spec.py instructions <id> --change <name>` → 按返回的 template/instruction 写 `outputPath` → 重跑 status 直到 `applyRequires`（tasks）全 done
4. 注册 STATE.md（沿用现有 python 片段）
5. 输出文案：**「SPEC \<name\> 已创建并注册。fenixd 会自动拾取并开始实现。」**——全程不出现 `/opsx:apply`、`openspec` CLI、`openspec-propose`。

规则部分保留：先澄清、kebab-case 命名、requirement 至少一个 scenario、搜索归档目录避免能力误判。

### D5: 原生归档（`bin/fenix_archive.py` + fenix-archive skill）

- `bin/fenix_archive.py <name>`：校验 change 存在于 `spec/changes/<name>/`；计算目标 `spec/archive/YYYY-MM-DD-<name>`（日期取当天）；目标已存在 → 报错并提示改名或换日期；否则 `shutil.move`。打印 JSON `{ok, from, to, error}`。
- `skills/fenix-archive/SKILL.md`：列出可选 changes（非归档），由用户选择（`AskUserQuestion`），确认后调用 `bin/fenix_archive.py`；不校验 tasks 完成度（不阻塞归档，仅提示）。
- 不做 delta-spec 同步（fenix 无主 spec 机制）。STATE.md 中的历史记录保持不变（已完成 spec 的状态字段本就是终态）。

### D6: fenix-init 目录

`fenix-init` 步骤 3（当前创建 `openspec/{changes,specs}/`）增加 `archive`：创建 `spec/archive/`。

### D7: 兼容性与引用清理

- `spec/changes/<name>/` 布局与 artifact 文件名、`.spec.yaml` 均保持不变。
- 清理 fenix 仓库内对 `openspec-propose` / `openspec-apply-change` / `/opsx:apply` / `openspec` CLI 的引用（当前仅 `skills/fenix-new/SKILL.md`；实施时全局 grep 复核）。
- `install.sh` 无需改动（本就不安装 openspec）；README 可补充说明「不再需要独立安装 openspec」。

## Risks / Trade-offs

- [与上游 schema 漂移] vendored 的 spec-driven 数据与未来 openspec 版本不一致 → 模板/指令以 vendored 副本为准，fenix 生成结果稳定；升级即替换 `schemas/spec-driven/` 目录。
- [生成器行为差异] 原生 `status`/`instructions` 与 openspec CLI 存在细微行为差异（如 spec 文件判定方式）→ 以「生成的 artifacts 可被 fenix 核心消费」为正确性标准，行为对齐 openspec 输出 JSON 结构。
- [归档目录影响 dashboard/watcher] archive 移动会触发 `spec/changes` watcher 事件 → 已确认 watcher 对归档目录仅做读取，无副作用。
- [fenix-new 流程依赖 JSON 输出解析] agent 需解析 CLI JSON → CLI 输出保持稳定、字段命名与 openspec 一致，降低 agent 理解成本。

## Migration Plan

1. vendored `schemas/spec-driven/`（从 openspec 包复制）。
2. 实现 `core/spec_gen.py` + 单测（new/status/instructions）。
3. 实现 `bin/fenix_spec.py` CLI + CLI 冒烟（对照 openspec 输出结构）。
4. 重写 `skills/fenix-new/SKILL.md`（自包含流程 + 文案）。
5. 实现 `bin/fenix_archive.py` + `skills/fenix-archive/SKILL.md` + `fenix-init` 创建 archive 目录。
6. 全局 grep 复核无残留 openspec CLI/skill 引用；全量 pytest 回归。

回滚：保留 `core/spec_gen.py` 即可继续使用；若需退回 openspec CLI，仅恢复 fenix-new 步骤 3 的调用即可，无数据迁移残留。

## Open Questions

- 是否需要在 `fenix-archive` 中先提示/确认未完成任务数：设计为仅提示不阻塞（与 openspec-archive-change 一致），无需用户确认。
