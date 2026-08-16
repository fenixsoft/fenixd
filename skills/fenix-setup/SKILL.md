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

### 3. 检查是否已在运行

```bash
if tmux has-session -t fenixd 2>/dev/null; then
    echo "fenixd is already running (tmux session: fenixd)"
    echo "To restart: tmux kill-session -t fenixd && /fenix-setup"
    exit 0
fi
```

### 4. 初始化状态文件

如果 STATE.md 和 PROJECT_LOG.md 不存在，创建它们。

### 5. 启动 fenixd

```bash
tmux new-session -d -s fenixd "cd $(pwd) && python3 .fenix/fenixd.py 2>&1 | tee .fenix/logs/stdout.log"
sleep 2
tmux has-session -t fenixd 2>/dev/null && echo "fenixd started" || echo "Failed to start"
```

### 6. 展示启动信息

```
  Fenix is running!
  View logs:  tmux attach -t fenixd
  Status:     /fenix-status
  New SPEC:   /fenix-new "your idea"
  Stop:       tmux kill-session -t fenixd
```
