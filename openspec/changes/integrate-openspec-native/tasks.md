# Tasks: integrate-openspec-native

## 1. Vendoring schema 数据

- [x] 1.1 在 fenix 框架根新建 `schemas/spec-driven/`，从 `/usr/lib/node_modules/@fission-ai/openspec/schemas/spec-driven/` 复制 `schema.yaml` 与 `templates/{proposal,design,spec,tasks}.md`
- [x] 1.2 在 `schemas/spec-driven/` 下新增 `README.md` 注明来源与版本（@fission-ai/openspec v1.3.1，MIT），便于后续升级

## 2. core/spec_gen.py 实现

- [x] 2.1 新增 `core/spec_gen.py`：`SCHEMA_DIR`（`Path(__file__).parent.parent / "schemas" / "spec-driven"`）+ `load_schema()` 读取 `schema.yaml`
- [x] 2.2 实现 `new_change(project_root, name)`：kebab-case 校验、同名已存在返回错误、创建 `openspec/changes/<name>/` 并写 `.openspec.yaml`（`schema: spec-driven` / `created: YYYY-MM-DD`）
- [x] 2.3 实现 `status(project_root, name) -> dict`：按 `generates` glob 存在性计算每个 artifact 的 `done`/`ready`/`blocked`（含 `missingDeps`），输出与 openspec `status --json` 同构（`changeName`/`schemaName`/`isComplete`/`applyRequires=["tasks"]`/`artifacts`），`specs/**/*.md` 以 `specs/` 下存在任意 `.md` 判定
- [x] 2.4 实现 `instructions(project_root, artifact_id, name) -> dict`：返回 `outputPath`/`description`/`instruction`/`template`（读 vendored 模板）/`dependencies`（已完成 requires 的绝对路径）
- [x] 2.5 `tests/` 新增 `test_spec_gen.py`：new_change（创建/重名错误/kebab-case 拒绝）、status（空 change 初始态、全完成 isComplete）、instructions（proposal/tasks 内容与依赖）；运行 `pytest tests/test_spec_gen.py -q` 通过

## 3. bin/fenix_spec.py CLI

- [x] 3.1 新增 `bin/fenix_spec.py`（仿 `bin/fenix_process.py`：脚本头 `sys.path.insert(0, 框架根)`）：argparse 子命令 `new <name>`、`status --change <name>`、`instructions <artifact-id> --change <name>`，均输出 JSON
- [x] 3.2 在 fenixd 项目内冒烟验证三个子命令输出结构（对照 openspec `status/instructions --json` 字段一致）
- [x] 3.3 确认在**未安装 openspec CLI** 的环境中 `python3 .fenix/bin/fenix_spec.py status --change <name>` 可正常运行（不引用 `openspec` 命令）

## 4. fenix-new skill 重写为自包含

- [x] 4.1 重写 `skills/fenix-new/SKILL.md` 步骤 3：改为「使用 fenix 原生 SPEC 生成器」——`python3 .fenix/bin/fenix_spec.py new <name>` → `status` → 依依赖顺序对每个 ready artifact 调 `instructions <id> --change <name>` 写 `outputPath` → 重跑 status 直到 applyRequires 全 done
- [x] 4.2 修改输出文案：注册 STATE.md 后告知「SPEC <name> 已创建并注册。fenixd 会自动拾取并开始实现。」；全文移除 `/opsx:apply`、`openspec-propose`、openspec CLI 字样
- [x] 4.3 保留步骤 1/2/4、SPEC 修改（--modify）与规则部分；`grep -rn "openspec-propose\|/opsx:apply\|openspec new\|openspec status\|openspec instructions" skills/` 确认无残留

## 5. 原生归档（命令 + skill + init）

- [x] 5.1 新增 `bin/fenix_archive.py <name>`：校验 change 存在；目标 `openspec/changes/archive/YYYY-MM-DD-<name>` 已存在则报错提示改名/换日期；否则 `shutil.move`；输出 JSON `{ok, from, to, error}`
- [x] 5.2 新增 `skills/fenix-archive/SKILL.md`：列出 `openspec/changes/` 下未归档 changes（AskUserQuestion 选择）→ 确认 → 调 `bin/fenix_archive.py`；未完成任务仅提示不阻塞
- [x] 5.3 `fenix-init` 步骤 3 增加创建 `openspec/changes/archive/` 目录
- [x] 5.4 `tests/` 新增归档单测：移动成功、日期冲突报错不覆盖、不存在 change 报错；运行通过

## 6. 收尾与回归

- [x] 6.1 全仓 `grep -rn "openspec-propose\|/opsx:apply\|openspec-apply-change"`（排除 `openspec/changes/`）确认 fenix 代码与 skills 无残留引用
- [x] 6.2 确认 `install.sh` 无需改动（不涉及 openspec）；README 补充「不再需要独立安装 openspec」说明（可选）
- [x] 6.3 运行 `pytest tests/ -q` 全量通过
