## Why

fenix-init / 骨架播种在新项目落地自己的产物后，框架的周期盘点随即把这些产物标成告警——框架先污染后告警自己（cloud-phone 首跑 3 条 major 白名单告警 + 3 条 info 散件提示全部源于初始化产物）：

1. `.fenix/verify.yaml` 被模板 gitignore 的 `!` 规则放行（白名单），但初始化从不 `git add` → 首轮盘点即报「白名单文件脱落」major（入库意图已声明、文件却未入库）。
2. `.claude/agents/`（框架播种的运行时产物目录）不在 gitignore 模板覆盖范围（只盖了 `.claude/worktrees/`）→ 播种的 `implementer.md`/`verifier.md` 成为 untracked 散件，触发首现提示。
3. `config.template.yaml` 的 llm/agents.models 注释按 claude 语境写（「未配置时所有 Agent 使用默认环境变量模型」），对 dsh+fenix 组合是误导——该组合无分配时回落 dsh 默认档（对称回落），并非「环境变量模型」；新手按注释理解配置必然困惑。

## What Changes

- **初始化产物自举**：fenix-init 在 git 仓库内完成骨架写入后，自动 `git add` 白名单文件（`.fenix/todo.md`、`.fenix/verify.yaml`）——staged 不 commit（提交时机留给用户）；非 git 仓库跳过并提示。
- **gitignore 模板补运行时产物**：`templates/gitignore-fenix.txt` 增加 `.claude/agents/` 规则（框架播种产物，预防性 ignore）；`--ensure-gitignore` 幂等补齐既有项目缺失规则。
- **模板注释按 harness 分形态改写**：`config.template.yaml` 的 llm 段与 agents.models 段注释改写为按 `agent.harness` 分形态描述默认行为（claude=环境继承默认档；dsh=回落 dsh profile 默认档，显式分配建议），消除「环境变量模型」误导。
- **fenix-setup skill 引导补强**：SKILL.md 增加初始化完成后的「模型配置检查」步骤（探测 providers/models 配置可用性，给出 Dashboard 设置页或手工编辑指引）与首跑常见告警解读（白名单/散件/契约模板态三类，说明来源与一键处置方式）。

## Capabilities

### New Capabilities

- `init-self-bootstrap`：初始化产物自举（白名单文件自动入库、运行时产物预防性 ignore、模板注释分形态、setup 引导）

## Impact

- **代码**：`fenix-init`（git add + 提示）、`templates/gitignore-fenix.txt`、`.fenix/config.template.yaml`、`skills/fenix-setup/SKILL.md`
- **兼容性**：既有项目经 `--ensure-gitignore` 幂等补齐；已初始化项目不重复 git add（幂等）
- **关联**：与 SPEC ② 的 `init-stray` 根因标签衔接——本变更消除了散件告警的产生源
