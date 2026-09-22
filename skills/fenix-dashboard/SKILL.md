---
name: fenix-dashboard
description: Use when the user wants to view the Fenix Web Dashboard, monitor multiple Fenixd projects in a browser, or launch/register the cross-project dashboard service. Invoked via /fenix-dashboard.
---

# Fenix: Web Dashboard

启动（或复用）Fenix Web Dashboard 独立进程，把当前项目注册进跨项目监控列表，并输出可直接粘贴到浏览器的访问 URL。

## 步骤

### 1. 解析框架目录与配置端口

框架目录经项目内 `.fenix` 软链接解析；dashboard 脚本位于框架的 `bin/` 下。

```bash
# 框架根目录：.fenix -> <框架根>（bin/core 等为软链接）
FENIX_DIR="$(cd .fenix 2>/dev/null && pwd -P || echo '')"
if [ -z "$FENIX_DIR" ] || [ ! -f "$FENIX_DIR/bin/fenix_dashboard.py" ]; then
    echo "❌ 当前目录不是有效的 Fenixd 项目（缺少 .fenix 软链接），请在 Fenixd 项目根目录执行 /fenix-dashboard"
    exit 1
fi
DASH="$FENIX_DIR/bin/fenix_dashboard.py"

# 配置端口（默认 8787）
PORT=$(python3 - "$HOME" << 'PYEOF' 2>/dev/null || echo 8787
import os, sys, yaml
p = os.path.expanduser('~/.config/fenixd/dashboard.yaml')
try:
    d = yaml.safe_load(open(p, encoding='utf-8')) or {}
    print(d.get('port', 8787))
except Exception:
    print(8787)
PYEOF
)
```

### 2. 探测 Dashboard 是否已运行

检查 tmux session `fenix-dashboard` 与配置端口；两者任一存活即视为已运行。
**注意**：端口探测必须校验 JSON 响应内容（`"projects"` 字段），不能只看 HTTP 200
（其它 web 服务如 SPA fallback 会对任意路径返回 200，会误判）。

```bash
# 探测函数：/api/projects 是 Dashboard JSON 且首页返回 HTML 才算存活。
# 两个条件都满足才判定存活——陈旧实例（cwd 指向已删除的 worktree）API 正常
# 但静态资源 404，仅查 "projects" 会误判存活导致一直复用坏实例。
probe() {
  curl -s -m 2 "http://localhost:$1/api/projects" 2>/dev/null | grep -q '"projects"' \
    && [ "$(curl -s -m 2 -o /dev/null -w '%{http_code}' "http://localhost:$1/")" = "200" ]
}
TMUX_RUNNING=""
if tmux has-session -t fenix-dashboard 2>/dev/null; then
    TMUX_RUNNING="yes"
fi
PORT_ALIVE=""
if probe "$PORT"; then
    PORT_ALIVE="yes"
fi
```

### 3. 未运行则启动

```bash
# 找实际端口。启动竞态处理：服务从 `tmux new-session` 到监听需 ~1s，
# 若只做单次向上探测会错过刚就绪的配置端口；因此先在配置端口上重试，
# 再向上探测自动上探的场景。一律用 probe（校验 JSON）过滤其它 web 服务误判。
find_actual_port() {
  local p attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    probe "$PORT" && { echo "$PORT"; return; }
    sleep 0.5
  done
  for p in $(seq $((PORT + 1)) $((PORT + 50))); do
    probe "$p" && { echo "$p"; return; }
    sleep 0.3
  done
}
if [ -z "$TMUX_RUNNING" ] && [ -z "$PORT_ALIVE" ]; then
    echo "🟢 启动 Dashboard 服务（tmux session: fenix-dashboard）..."
    # env -u CLAUDE_PID：防 claude-watchdog 绑会话自杀（tmux server 会把启动 shell 的
    # CLAUDE_PID 继承进 pane；与 hook_engine restart-dashboard 固化命令对齐）
    tmux new-session -d -s fenix-dashboard "env -u CLAUDE_PID python3 $DASH --serve"
    ACTUAL_PORT="$(find_actual_port)"
    if [ -z "$ACTUAL_PORT" ]; then
        echo "⚠️ 服务启动失败或超时，请检查 tmux session 'fenix-dashboard'（tmux attach -t fenix-dashboard 查看日志）"
    fi
else
    echo "✅ Dashboard 已在运行（复用）"
    ACTUAL_PORT="$(find_actual_port)"
fi
```

### 4. 注册当前项目（已注册则跳过）

```bash
python3 "$DASH" --add-project .
```

### 5. 输出 URL 与项目列表

```bash
URL="http://localhost:${ACTUAL_PORT:-$PORT}"
echo ""
echo "=================================================="
echo "  Fenix Web Dashboard"
echo "  访问地址: ${URL}"
echo "=================================================="
echo "已监控项目:"
python3 "$DASH" --list-projects
```

## 输出要求

- **一行可粘贴的 URL**：`http://localhost:<port>`（放在最显眼位置）
- 已监控项目列表（`--list-projects` 输出）
- 若服务为本轮新启动，说明 tmux session 名 `fenix-dashboard` 与停止方式（`tmux kill-session -t fenix-dashboard`）
- 提示：Dashboard 每 2 秒自动刷新，仅本机可访问

## 功能概览

- **概览**：跨项目 SPEC 状态统计、任务进度、问题告警、活跃运行
- **项目详情**：SPEC 列表、任务进度、验证结果、bug 列表、运行记录、时间轴
- **配置页**：可视化编辑 LLM Provider、Agent 模型分配、审批模式（manual/auto）
  - 配置修改后写入 `.fenix/config.yaml`，**需重启 daemon 生效**
  - `approve_mode=auto` 时 SPEC 完成后会自动 `git push` 到远端，请谨慎使用
