<!-- knowledge: capability=fenix-setup-skill rev=1 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

# 框架初始化与启动入口

`/fenix-setup` 是初始化或重启 Fenix 框架的用户入口，覆盖新项目首次接入与既有项目重启。

## 现行规则

- 三段流程：检查依赖 → 创建目录骨架 → 启动 fenixd daemon。
- 依赖检查覆盖 Python、git、tmux 与 Claude Code CLI，缺项先报告再继续。
- 目录骨架创建委托 `fenix-init`（`.fenix/`、`spec/` 骨架、软链接与 `.gitignore` 规则同初始化播种口径）。
- daemon 启动前先探测既有实例，避免双实例；重启场景沿用 daemon 单例保证。
- 幂等：对已完成初始化的项目重复执行不破坏既有状态。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
