# Dashboard 技能入口

<!-- knowledge: capability=fenix-dashboard-skill rev=2
     sources=spec/archive/2026-09-02-add-fenix-dashboard,spec/changes/add-systemd-hosting -->

`/fenix-dashboard` skill：一键启动（或复用）跨项目 dashboard 服务并把当前项目注册进监控。

## 规则

- 执行 `/fenix-dashboard` 时先探测服务是否已运行：检查 systemd unit `fenix-dashboard.service` 是否活跃（`systemctl is-active`）或探测配置端口（校验 JSON 响应内容过滤其它 web 服务误判），任一存活即视为已运行；已运行则复用，不重复启动、不产生重复注册。
- 未运行时经 `install_dashboard_unit` 生成安装 unit（含 `FENIX_DASHBOARD_DETACH=1`）并以 systemd 承载拉起（`systemctl enable --now` 语义）；unit 环境经 EnvironmentFile 会话身份 denylist 剥离 `CLAUDE_PID`，claude-watchdog 不把常驻服务绑到启动它的 Claude 会话上误杀。启动竞态处理：unit 拉起到监听约 1s，探测先在配置端口重试再向上探测。
- 服务为本轮新启动时输出承载 unit 名与启停协议（重启 `systemctl restart fenix-dashboard`、停止 `systemctl stop`、看现场 `journalctl -u fenix-dashboard` 加主树 `.fenix/logs/` 既有日志文件）；勿以手工 `python3 fenix_dashboard.py --serve` 接管 unit 承载常驻实例（接管豁免拒绝）。
- 启动后将当前项目注册进监控配置（`bin/fenix_dashboard.py --add-project .`，按路径去重、已注册跳过）。
- 输出用户可直接粘贴到浏览器访问的 URL（`http://localhost:<port>`）与已监控项目列表摘要；验证以页面可达为准。
- 一键安装：`install.sh` 按 `skills/*/` 通配把 `skills/fenix-dashboard/` 软链到 `~/.claude/skills/fenix-dashboard`，安装后任意项目内可用；安装完成提示提及 dashboard 能力。

## 溯源

- 史前复原 — /fenix-dashboard skill 启动并注册跨项目 dashboard 服务，验证以页面可达为准
- 2026-09-02 2026-09-02-add-fenix-dashboard（spec/archive/2026-09-02-add-fenix-dashboard） — 建立「探测→启动→注册→输出 URL」流程与 install.sh 软链接入
- 2026-11-04 add-systemd-hosting（spec/changes/add-systemd-hosting） — 启动/探测/重启配方 systemctl 化：探测 unit 活跃 + 端口 JSON 校验、启动经 `install_dashboard_unit`（含 DETACH 门）、输出 unit 启停协议与接管豁免警示（tmux 会话探测与 `env -u CLAUDE_PID` tmux 启动退役）
