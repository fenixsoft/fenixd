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

### 2. 自动初始化项目骨架（未初始化时自动运行 fenix-init）

以 `.fenix/bin/fenix_session.py` 与 `.fenix/core/config.py` 是否存在为判定标志，
任一缺失即视为未完成初始化（含旧版 setup 预创建空目录导致的半破损状态）。
未初始化则自动运行 `fenix-init`
（生成 .fenix/config.yaml、框架软链、状态文件、verify.yaml 模板、spec/、agent 软链、.gitignore），
不需要用户单独执行 fenix-init：

```bash
if [ ! -e ".fenix/bin/fenix_session.py" ] || [ ! -e ".fenix/core/config.py" ]; then
    echo "项目尚未初始化，自动执行 fenix-init ..."
    # 先清理旧版 setup 可能预创建的真实空目录（rmdir 只删空目录，软链与非空目录天然安全），
    # 否则 fenix-init 的软链会因「已存在」被跳过，留下空目录顶替框架软链
    rmdir .fenix/core .fenix/bin .fenix/tests 2>/dev/null
    if command -v fenix-init >/dev/null 2>&1; then
        fenix-init
    else
        echo "错误：找不到 fenix-init 命令。请先在 Fenixd 框架仓库运行 bash install.sh"
        exit 1
    fi
else
    echo "项目已初始化，跳过 fenix-init"
fi
```

### 2.5 确保 .fenix 已在 .gitignore（幂等，每次都执行）

步骤 2 只对**未初始化**项目运行 fenix-init，已初始化项目的 `.gitignore` 若缺
`.fenix/*` 规则不会被修复——而 `.fenix/config.yaml` 含 API Key、`.fenix/` 下有
运行时产物（run 转录、日志、agent 会话配置）与指向框架的软链，缺失该规则会导致
误提交与密钥泄露。本步骤对**所有**项目每次都执行，幂等补齐（已含规则则跳过）：

```bash
if command -v fenix-init >/dev/null 2>&1; then
    fenix-init --ensure-gitignore "$(pwd)"
else
    echo "提示：未找到 fenix-init，跳过 .gitignore 检查（请在框架仓库运行 bash install.sh）"
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
    echo "fenixd is already running for this project (tmux session: ${SESSION_NAME})"
    echo "To restart: tmux kill-session -t ${SESSION_NAME} && /fenix-setup"
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

### 6. 初始化状态文件与验证契约模板

如果 .fenix/STATE.md 和 .fenix/PROJECT_LOG.md 不存在，创建它们。

如果 .fenix/verify.yaml 不存在，从框架模板生成（模板全部配置行注释 =
无契约，框架安全回退旧行为；用户后续在 Dashboard 设置页或直接编辑取消
注释启用）。已存在则绝不覆盖：

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

```bash
tmux new-session -d -s "${SESSION_NAME}" "cd $(pwd) && python3 .fenix/fenixd.py 2>&1 | tee .fenix/logs/stdout.log"
sleep 2
if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    echo "fenixd started (tmux session: ${SESSION_NAME})"
else
    echo "Failed to start"
fi
```

### 8. 展示启动信息

```
  Fenix is running!
  tmux session: ${SESSION_NAME}
  View logs:  tmux attach -t ${SESSION_NAME}
  Status:     /fenix-status
  New SPEC:   /fenix-new "your idea"
  Stop:       tmux kill-session -t ${SESSION_NAME}
```
