<!-- knowledge: capability=fenix-setup-skill rev=2 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

# 框架初始化与启动入口

`/fenix-setup` 是初始化或重启 Fenix 框架的用户入口，覆盖新项目首次接入与既有项目重启。

## 现行规则

- 三段流程：检查依赖 → 创建目录骨架 → 启动 fenixd daemon。
- 依赖检查覆盖 Python、git、systemd（systemctl 可用性，daemon/dashboard 承载必需）与 Claude Code CLI，缺项先报告再继续。
- 目录骨架创建委托 `fenix-init`（`.fenix/`、`spec/` 骨架、软链接与 `.gitignore` 规则同初始化播种口径）。
- daemon 启动前先探测既有实例，避免双实例；启动经 systemd unit 承载（`fenixd-<项目名>.service` 生成安装并 `enable --now`），重启场景沿用 daemon 单例保证；启动失败看现场用 `journalctl -u <unit>` 加 `.fenix/logs/` 既有日志文件。
- 含「人工切换步骤」小节：tmux 承载存量部署一次性迁移 systemd（env 候选稿人工审核 → `bin/migrate_to_systemd.py` 先 dry-run 后真切换 → 验收 → 回滚配方），实际切换由人工执行。
- 幂等：对已完成初始化的项目重复执行不破坏既有状态。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
- 2026-11-04 add-systemd-hosting（spec/changes/add-systemd-hosting） — 配方 systemctl 化：依赖检查 tmux → systemd（systemctl）、daemon 启动改 unit 承载、看现场 journalctl + 既有日志文件；新增「人工切换步骤」小节（存量 tmux 部署迁移与回滚配方）
