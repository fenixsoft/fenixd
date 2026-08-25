## ADDED Requirements

### Requirement: /fenix-dashboard skill 启动当前项目监控并输出 URL
框架 MUST 新增 `skills/fenix-dashboard/SKILL.md`，用户在任意 Fenixd 项目目录内执行 `/fenix-dashboard` 时，该 skill MUST：
1. 探测 Dashboard 服务是否已运行（检查 tmux session `fenix-dashboard` 或探测配置端口）；
2. 若未运行，在 tmux 中启动 `python3 <框架目录>/bin/fenix_dashboard.py --serve`（框架目录经 `.fenix` 软链接解析）；
3. 将当前项目目录注册到监控配置（`bin/fenix_dashboard.py --add-project .`），已注册则跳过；
4. 输出一个用户可直接粘贴到浏览器访问的 URL（`http://localhost:<port>`）及「已监控的项目列表」摘要。

#### Scenario: 首次执行启动并注册
- **WHEN** Dashboard 未运行且当前目录是 Fenixd 项目
- **THEN** 服务被启动、当前项目被注册，skill 输出可访问的 URL 与项目列表

#### Scenario: 已运行时复用服务
- **WHEN** Dashboard 已运行且当前项目已注册
- **THEN** 不重复启动服务、不产生重复注册，仍输出 URL 与项目列表

### Requirement: 一键安装自动接入新 skill
`install.sh` MUST 在安装时将 `skills/fenix-dashboard/` 软链到 `~/.claude/skills/fenix-dashboard`（与其它 skill 一致，沿用现有 `skills/*/` 通配逻辑）。安装后用户即可在任意项目内使用 `/fenix-dashboard`，无需手动配置。安装完成的提示信息 SHOULD 提及新 dashboard 能力。

#### Scenario: 安装后 skill 可用
- **WHEN** 执行 `install.sh` 完成后检查 `~/.claude/skills/fenix-dashboard`
- **THEN** 该目录存在且为指向框架 `skills/fenix-dashboard/` 的软链接
