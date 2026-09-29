# Dashboard 技能入口

<!-- knowledge: capability=fenix-dashboard-skill rev=1
     sources=spec/archive/2026-09-02-add-fenix-dashboard -->

`/fenix-dashboard` skill：一键启动（或复用）跨项目 dashboard 服务并把当前项目注册进监控。

## 规则

- 执行 `/fenix-dashboard` 时先探测服务是否已运行：检查 tmux session `fenix-dashboard` 或探测配置端口，任一存活即视为已运行；已运行则复用，不重复启动、不产生重复注册。
- 未运行时在 tmux 中启动 `env -u CLAUDE_PID python3 <框架目录>/bin/fenix_dashboard.py --serve`（框架目录经项目 `.fenix` 软链接解析）；`env -u CLAUDE_PID` 防 claude-watchdog 把常驻服务绑到启动它的 Claude 会话上误杀。
- 启动后将当前项目注册进监控配置（`bin/fenix_dashboard.py --add-project .`，按路径去重、已注册跳过）。
- 输出用户可直接粘贴到浏览器访问的 URL（`http://localhost:<port>`）与已监控项目列表摘要；验证以页面可达为准。
- 一键安装：`install.sh` 按 `skills/*/` 通配把 `skills/fenix-dashboard/` 软链到 `~/.claude/skills/fenix-dashboard`，安装后任意项目内可用；安装完成提示提及 dashboard 能力。

## 溯源

- 史前复原 — /fenix-dashboard skill 启动并注册跨项目 dashboard 服务，验证以页面可达为准
- [2026-09-02 2026-09-02-add-fenix-dashboard](spec/archive/2026-09-02-add-fenix-dashboard/) — 建立「探测→启动→注册→输出 URL」流程与 install.sh 软链接入
