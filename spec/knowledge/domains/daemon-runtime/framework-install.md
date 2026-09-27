<!-- knowledge: capability=framework-install rev=1 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

# 框架安装

`install.sh` 把 fenixd 框架装配到本机，幂等可重复执行。

## 现行规则

- 依赖检查先行，缺一即失败退出：Python 3.10+、git、tmux、Claude Code CLI、PyYAML。
- 框架 skills 软链到 `~/.claude/skills/`，使 `/fenix-*` 命令全局可用。
- `fenix-init` 软链进 PATH（优先 `~/.local/bin`，其次 `/usr/local/bin`），使命令行可直接调用。
- 框架根目录以脚本所在目录为准（`FENIXD_HOME`），安装产物全部是软链接，不拷贝代码。
- 重复执行安全：已存在的软链与依赖检查结果幂等收敛，不产生重复产物。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
