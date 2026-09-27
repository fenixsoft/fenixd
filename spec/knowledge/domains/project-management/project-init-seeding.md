<!-- knowledge: capability=project-init-seeding rev=1 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

# 项目初始化骨架播种

`fenix-init` 在目标目录生成使用 fenixd 所需的工程骨架。

## 现行规则

- 用法：`fenix-init [DIR] [--name NAME] [--type web|cli|library|api]`。
- 生成 `.fenix/`：项目配置 `config.yaml`、状态文件 `STATE.md`、`PROJECT_LOG.md`、运行时目录，以及指向框架根的软链接。
- 生成 `spec/{changes,specs}/` 与 `spec/archive/` 目录骨架。
- 生成 `.claude/agents/`（软链接）与 `.claude/worktrees/`。
- 幂等确保 `.gitignore` 含 fenix 运行时目录规则（`.fenix/*` 等）；`--ensure-gitignore` 模式只补 `.gitignore`，不做其他初始化。
- 框架根目录定位：脚本路径经 `.resolve()` 跟随软链接解析到真实安装位置（`FENIXD_HOME`）。
- 状态与日志文件由 `templates/` 下的模板（`STATE.md`、`PROJECT_LOG.md`、`gitignore-fenix.txt`）播种。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
