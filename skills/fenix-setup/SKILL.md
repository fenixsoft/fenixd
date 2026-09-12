---
name: fenix-setup
description: Use when the user wants to initialize or restart the Fenix Loop Engineering Framework, including on a brand-new project that has not been initialized yet. Invoked via /fenix-setup.
---

# Fenix: 初始化与启动

设置并启动 Fenix Loop Engineering Framework。未初始化的项目会自动运行 fenix-init 生成工程骨架，无需单独执行。

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

### 2. 确保项目骨架（幂等运行 fenix-init，每次都执行）

`fenix-init` 完全幂等：已存在的 config.yaml / 框架软链 / 状态文件 / verify.yaml /
spec 目录 / agent 软链一律跳过，只补齐缺失项（含 `.gitignore` 的 `.fenix/*` 规则）。
因此本步骤**每次都运行**，一次覆盖「新项目初始化」与「已初始化项目补齐缺失项」
两种情形——消除了旧逻辑「已初始化即跳过 fenix-init」导致缺失项永远补不上的缺口。

`.fenix/config.yaml` 含 API Key、`.fenix/` 下有运行时产物（run 转录、日志、agent
会话配置）与指向框架的软链，缺失 `.gitignore` 规则会导致误提交与密钥泄露，
fenix-init 会幂等确保该规则存在。无需用户单独执行 fenix-init：

```bash
if command -v fenix-init >/dev/null 2>&1; then
    # 先清理旧版 setup 可能预创建的真实空目录（rmdir 只删空目录，软链与非空目录天然安全），
    # 否则 fenix-init 的软链会因「已存在」被跳过，留下空目录顶替框架软链
    rmdir .fenix/core .fenix/bin .fenix/tests 2>/dev/null
    fenix-init
else
    echo "错误：找不到 fenix-init 命令。请先在 Fenixd 框架仓库运行 bash install.sh"
    exit 1
fi
```

### 3. 创建目录结构（兜底）

```bash
mkdir -p .fenix/core .fenix/logs .fenix/tests .fenix/verify-progress .fenix/screenshots .claude/agents .claude/worktrees
```

### 4. 计算本项目唯一 session 名并检查是否已在运行

session 名由项目根路径派生（`fenixd-<目录名>-<哈希>`，见 `bin/fenix_session.py`），
同一台机器可同时运行多个项目的 daemon，互不干扰。

```bash
SESSION_NAME=$(python3 .fenix/bin/fenix_session.py name "$(pwd)" 2>/dev/null)
if [ -z "${SESSION_NAME}" ]; then
    echo "错误：无法确定 session 名。项目尚未初始化 .fenix，请先运行 fenix-init"
    exit 1
fi
if python3 .fenix/bin/fenix_session.py running "$(pwd)" 2>/dev/null | grep -q YES; then
    echo "fenixd is already running for this project (supervisor-hosted, tmux session: ${SESSION_NAME})"
    echo "To restart: 经 Dashboard 项目页「停止」→「启动」（或 touch .fenix/restart_request 走 supervisor 优雅重启）"
    exit 0
fi
```

### 5. 生成项目简介

读取项目根目录的 `README.md`（缺失或信息不足时查看 `package.json`、`pyproject.toml` 等清单文件与目录结构），生成一句约 100 字的中文项目简介，写入 `.fenix/config.yaml` 的 `project.description` 字段。

> **兜底规则**：信息不足（空仓库、无可推断文件、无法判断项目性质）或写入出错时，写入默认文案「由 Fenix 框架管理的项目，暂无自动生成的简介。」；此步骤的任何失败 MUST NOT 阻塞后续步骤。

```bash
# 读取 README.md（优先），缺失时读 package.json/pyproject.toml，再缺失则读目录结构
README_CONTENT=""
if [ -f "README.md" ]; then
    README_CONTENT=$(head -c 8192 README.md 2>/dev/null)
elif [ -f "package.json" ]; then
    README_CONTENT=$(head -c 4096 package.json 2>/dev/null)
elif [ -f "pyproject.toml" ]; then
    README_CONTENT=$(head -c 4096 pyproject.toml 2>/dev/null)
else
    README_CONTENT=$(ls -1 | head -20)
fi

# 使用 Claude CLI 生成简介（失败时写默认文案）
PROMPT="你是一个项目简介生成器。请根据以下项目信息生成一句约100字的中文项目简介。

项目信息：
${README_CONTENT}

要求：
1. 生成的简介应该是纯文本，不要包含任何标记语言
2. 简介应该概括项目的主要用途和特点
3. 简介长度控制在100字左右
4. 只输出简介文本，不要有其他内容"

DESCRIPTION=$(claude -p "${PROMPT}" 2>/dev/null | head -c 500)
if [ -z "${DESCRIPTION}" ]; then
    DESCRIPTION="由 Fenix 框架管理的项目，暂无自动生成的简介。"
fi

# 写入配置文件（存在则合并，不存在则跳过——config 由步骤 2 的 fenix-init 渲染）
if [ -f ".fenix/config.yaml" ]; then
    python3 -c "
import yaml, sys
try:
    with open('.fenix/config.yaml', 'r') as f:
        config = yaml.safe_load(f) or {}
    if not isinstance(config, dict):
        config = {}
    if 'project' not in config or not isinstance(config.get('project'), dict):
        config.setdefault('project', {})
    config['project']['description'] = '''${DESCRIPTION}'''
    with open('.fenix/config.yaml', 'w') as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
except Exception:
    # 写入失败不阻塞
    pass
" 2>/dev/null
fi
echo "项目简介已生成"
```

### 6. 兜底：确保验证契约模板

`.fenix/STATE.md`、`.fenix/PROJECT_LOG.md`、`.fenix/verify.yaml` 均由步骤 2 的
fenix-init 创建（已存在则跳过）。本步骤仅作兜底：若 `.fenix/verify.yaml` 异常缺失，
从框架模板补建（模板全部配置行注释 = 无契约，框架安全回退旧行为；用户后续可在
Dashboard 设置页或直接编辑取消注释启用）。已存在则绝不覆盖：

```bash
if [ ! -f ".fenix/verify.yaml" ]; then
    if [ -f ".fenix/core/verify_contract_template.yaml" ]; then
        cp ".fenix/core/verify_contract_template.yaml" ".fenix/verify.yaml"
        echo "已生成 .fenix/verify.yaml（契约模板，按项目实际取消注释启用）"
    else
        echo "跳过：找不到契约模板 .fenix/core/verify_contract_template.yaml"
    fi
else
    echo ".fenix/verify.yaml 已存在，跳过"
fi
```

### 7. 启动 fenixd

> **托管语义**（fix-supervisor-hosting-chain）：daemon 由 `fenixd_supervisor.py`
> 看门狗托管启动（而非 tmux 直启 `fenixd.py`）——supervisor 承担唯一的重启职责，
> 检测 `.fenix/restart_request` 后 SIGTERM daemon 并自动拉起。tmux 仅作为
> 「脱离终端的承载手段」，daemon 是 supervisor 的子进程。

```bash
tmux new-session -d -s "${SESSION_NAME}" "cd $(pwd) && python3 .fenix/bin/fenixd_supervisor.py --project-root $(pwd) >> .fenix/logs/supervisor.log 2>&1"
sleep 2
if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    echo "fenixd started (supervisor-hosted, tmux session: ${SESSION_NAME})"
else
    echo "Failed to start"
fi
```

### 8. 展示启动信息

```
  Fenix is running! (supervisor-hosted)
  tmux session: ${SESSION_NAME}
  View logs:  tmux attach -t ${SESSION_NAME}  # supervisor 日志见 .fenix/logs/supervisor.log
  Status:     /fenix-status
  New SPEC:   /fenix-new "your idea"
  Stop:       请经 Dashboard 项目页「停止」按钮（supervisor 收口退出）

