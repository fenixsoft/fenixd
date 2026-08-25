---
name: fenix-setup
description: Use when the user wants to initialize or restart the Fenix Loop Engineering Framework. Checks dependencies, creates directories, and starts the fenixd daemon. Invoked via /fenix-setup.
---

# Fenix: 初始化与启动

设置并启动 Fenix Loop Engineering Framework。

## 步骤

### 1. 检查依赖

```bash
echo "Checking dependencies..."
python3 --version 2>/dev/null || echo "MISSING: Python 3.10+"
git --version 2>/dev/null || echo "MISSING: git"
tmux -V 2>/dev/null || echo "MISSING: tmux"
which claude 2>/dev/null || echo "MISSING: claude CLI"
python3 -c "import yaml" 2>/dev/null && echo "PyYAML: OK" || { echo "Installing PyYAML..."; pip3 install pyyaml -q; }
```

### 2. 创建目录结构

```bash
mkdir -p .fenix/core .fenix/logs .fenix/tests .claude/agents .claude/worktrees
```

### 3. 计算本项目唯一 session 名并检查是否已在运行

session 名由项目根路径派生（`fenixd-<目录名>-<哈希>`，见 `bin/fenix_session.py`），
同一台机器可同时运行多个项目的 daemon，互不干扰。

```bash
SESSION_NAME=$(python3 .fenix/bin/fenix_session.py name "$(pwd)" 2>/dev/null)
if [ -z "${SESSION_NAME}" ]; then
    echo "错误：无法确定 session 名。项目尚未初始化 .fenix，请先运行 fenix-init"
    exit 1
fi
if python3 .fenix/bin/fenix_session.py running "$(pwd)" 2>/dev/null | grep -q YES; then
    echo "fenixd is already running for this project (tmux session: ${SESSION_NAME})"
    echo "To restart: tmux kill-session -t ${SESSION_NAME} && /fenix-setup"
    exit 0
fi
```

### 4. 初始化状态文件

如果 STATE.md 和 PROJECT_LOG.md 不存在，创建它们。

### 5. 启动 fenixd

```bash
tmux new-session -d -s "${SESSION_NAME}" "cd $(pwd) && python3 .fenix/fenixd.py 2>&1 | tee .fenix/logs/stdout.log"
sleep 2
if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    echo "fenixd started (tmux session: ${SESSION_NAME})"
else
    echo "Failed to start"
fi
```

### 6. 展示启动信息

```
  Fenix is running!
  tmux session: ${SESSION_NAME}
  View logs:  tmux attach -t ${SESSION_NAME}
  Status:     /fenix-status
  New SPEC:   /fenix-new "your idea"
  Stop:       tmux kill-session -t ${SESSION_NAME}
```
