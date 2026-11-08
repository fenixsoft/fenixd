# init-self-bootstrap 规范

## ADDED Requirements

### Requirement: 白名单文件初始化自动入库

fenix-init 在 git 仓库内完成骨架写入后 SHALL 自动 `git add` 模板 gitignore 放行的白名单文件（`.fenix/todo.md`、`.fenix/verify.yaml`）——仅 staged、MUST NOT 自动 commit（提交时机留给用户）；仓库无提交史（ unborn 分支）时 git add 同样生效；非 git 仓库跳过并输出提示行。

#### Scenario: git 仓库内初始化后白名单文件已 staged

- **WHEN** 在已初始化（`git init` 完成、允许零提交）的仓库内执行 fenix-init
- **THEN** `.fenix/todo.md` 与 `.fenix/verify.yaml` 处于 git index（`git ls-files` 可见），无自动 commit 产生，控制台输出已入库提示

#### Scenario: 非 git 仓库跳过并提示

- **WHEN** 目标目录不是 git 仓库
- **THEN** 骨架照常生成，git add 步骤跳过，输出「检测到非 git 仓库，白名单文件待 `git init` 后手工入库」提示

#### Scenario: 幂等重跑不重复报错

- **WHEN** fenix-init 对已初始化项目重跑（各文件已存在走跳过分支）
- **THEN** 已入库文件不重复报错，整体行为幂等

### Requirement: 运行时产物目录预防性 ignore

gitignore 模板 SHALL 覆盖框架播种的全部运行时产物目录：在既有 `.claude/worktrees/` 规则外增加 `.claude/agents/`；`--ensure-gitignore` 幂等补齐时对缺失该规则的既有项目一并追加（判据取关键规则行，幂等不重复）。

#### Scenario: 新项目播种产物不再成散件

- **WHEN** fenix-init 以新模板初始化项目并播种 `.claude/agents/`
- **THEN** `git status` 不再视 `.claude/agents/` 下文件为 untracked（周期盘点不再产生该目录散件提示）

#### Scenario: 既有项目幂等补齐

- **WHEN** 对缺 `.claude/agents/` 规则的既有项目执行 `--ensure-gitignore`
- **THEN** 规则被追加且带成因注释；规则已在场时跳过不重复

### Requirement: 配置模板注释按 harness 分形态

`config.template.yaml` 的 llm 段与 `agents.models` 段注释 SHALL 按 `agent.harness` 选型分形态描述无分配时的默认行为：claude 形态=环境继承 CLI 默认档；dsh 形态=无分配回落 dsh profile 默认档（对称回落），并说明显式分配（provider+model）是获得确定模型与 failover 的建议路径；MUST NOT 出现「默认环境变量模型」这类对两形态都不准确的表述。

#### Scenario: 注释与回落语义一致

- **WHEN** 新手阅读模板 agents.models 段注释
- **THEN** 注释准确描述 claude/dsh 两形态的无分配默认行为与显式分配建议，无「环境变量模型」误导表述

### Requirement: fenix-setup 模型配置检查与首跑告警引导

fenix-setup SKILL SHALL 在初始化完成后增加两个引导动作：①「模型配置检查」——读取项目 config.yaml，探测 `llm.providers` 与 `agents.models` 配置形态，按检查结果给出指引（未配置→Dashboard 设置页/手工编辑模板示例路径；已配置→确认 provider 名与注册表一致的核对要点）；②「首跑常见告警解读」——说明白名单脱落/散件首现/契约模板态三类首跑高频告警的来源与处置方式。

#### Scenario: setup 引导覆盖模型配置与首跑告警

- **WHEN** 按 fenix-setup SKILL 对新项目执行初始化引导
- **THEN** 流程含模型配置检查步骤（含未配置/已配置两分支指引）与首跑三类告警的解读说明（来源 + 处置）
