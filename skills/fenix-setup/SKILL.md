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
systemctl --version 2>/dev/null | head -1 || echo "MISSING: systemd（daemon/dashboard 承载必需，add-systemd-hosting 起 tmux 承载已退役）"
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

### 4. 计算本项目唯一 unit 名并检查是否已在运行

unit 名由项目根路径派生（`fenixd-<目录名>-<哈希>.service`，见
`python3 .fenix/bin/fenix_session.py unit`），同一台机器可同时运行多个项目的
daemon（各一条 unit），互不干扰。

```bash
UNIT_NAME=$(python3 .fenix/bin/fenix_session.py unit "$(pwd)" 2>/dev/null)
if [ -z "${UNIT_NAME}" ]; then
    echo "错误：无法确定 unit 名。项目尚未初始化 .fenix，请先运行 fenix-init"
    exit 1
fi
if python3 .fenix/bin/fenix_session.py running "$(pwd)" 2>/dev/null | grep -q YES; then
    echo "fenixd is already running for this project (systemd unit: ${UNIT_NAME})"
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

### 5b. 探测并填写构建产物路径

调用 `bin/fenix_detect_artifacts.py --write`（纯本地探测：`package.json` scripts、
`pyproject.toml`、目录结构、Fenix 框架约定）写入 `.fenix/config.yaml` 的
`worktree.has_build_artifacts` 与 `worktree.build_artifact_paths`。

> **幂等规则**：`worktree.has_build_artifacts` 已显式存在（人工或前次 setup 写入）
> 时 MUST 跳过，MUST NOT 覆盖人工设置。
> **兜底规则**：探测失败 / 信息不足（如纯文档仓库）时两键留空（未裁决），交由
> 运行期 `build_artifact_paths_missing` 信号兜底起草——本步骤任何失败 MUST NOT
> 阻塞后续步骤。

```bash
# .fenix/bin 为框架 bin 的软链（fenix-init 步骤 2 已建立）
if [ -x ".fenix/bin/fenix_detect_artifacts.py" ] || [ -f ".fenix/bin/fenix_detect_artifacts.py" ]; then
    python3 .fenix/bin/fenix_detect_artifacts.py --write "$(pwd)" 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin); w=d.get('write',{}); print(('已填写产物配置' if w.get('wrote') else '跳过：'+w.get('reason','探测失败')) + ('（'+str(len(d.get('build_artifact_paths',[])))+' 条候选路径）' if d.get('has_build_artifacts') else '（未探测到产物）'))" \
        || echo "产物路径探测跳过（失败不阻塞）"
else
    echo "跳过：找不到探测脚本 .fenix/bin/fenix_detect_artifacts.py（不阻塞后续步骤）"
fi
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

### 7. 启动 fenixd（systemd unit 承载）

> **托管语义**（fix-supervisor-hosting-chain + add-systemd-hosting）：daemon 由
> `fenixd_supervisor.py` 看门狗托管启动，supervisor 承担唯一的重启职责，检测
> `.fenix/restart_request` 后 SIGTERM daemon 并自动拉起。承载手段为 systemd
> unit（`fenixd-<项目名>-<哈希>.service`，`Restart=on-failure` + 崩溃拉回，开机
> 自启）；daemon 是 supervisor 的子进程，systemd 监督对象是 supervisor 不是
> daemon。tmux 承载已退役（BREAKING），`systemctl` 不可用时启动拒绝并给可读
> 错误，不回退 tmux。

```bash
# ① env 承载：从当前会话环境机械捕获（过滤 CLAUDE_PID/CLAUDECODE/CLAUDE_CODE_*
#    等会话身份键）→ 0600 正式 EnvironmentFile——systemd 不继承 shell 会话环境，
#    缺失则 daemon 无法访问 LLM 网关。新装场景源即当前受信会话，直接写正式文件；
#    密钥不入库（.fenix/ 已被 gitignore 覆盖）
python3 - <<'PYEOF'
import os, sys
from pathlib import Path
sys.path.insert(0, '.fenix')
from core.systemd_hosting import (read_process_env, filter_session_identity,
                                  render_env_file, write_env_file, project_env_file)
target = project_env_file(Path.cwd().resolve())
filtered = filter_session_identity(read_process_env(os.getpid()))
write_env_file(render_env_file(filtered), target)
print(f"EnvironmentFile 已写入 {target}（{len(filtered)} 键，0600）")
PYEOF

# ② 启动：unit 缺失即生成安装并 enable --now（幂等；已活跃不重建不重启）
python3 - <<'PYEOF'
import json, sys
from pathlib import Path
sys.path.insert(0, '.fenix')
from core.fenix_session import start_daemon
r = start_daemon(str(Path.cwd().resolve()))
print(json.dumps(r, ensure_ascii=False))
sys.exit(0 if r.get("ok") else 1)
PYEOF
if [ $? -eq 0 ]; then
    echo "fenixd started (systemd unit: ${UNIT_NAME})"
else
    echo "Failed to start（看现场：journalctl -u ${UNIT_NAME} + .fenix/logs/supervisor.log）"
fi
```

### 8. 展示启动信息

```
  Fenix is running! (systemd unit hosted)
  unit:       ${UNIT_NAME}   # systemctl status ${UNIT_NAME}
  View logs:  journalctl -u ${UNIT_NAME} -f  # supervisor 日志另见 .fenix/logs/supervisor.log
  Status:     /fenix-status
  New SPEC:   /fenix-new "your idea"
  Stop:       请经 Dashboard 项目页「停止」按钮（systemctl stop + supervisor 收口退出）
```

## 人工切换步骤（tmux 承载存量部署迁移 systemd）

> 适用于 add-systemd-hosting 之前以 tmux 承载启动的在跑部署。daemon 本尊就在
> 旧链上，真切换是**人工步骤**（Agent 只交付脚本与预演，不代拆）。

1. **审核 env 候选稿**：`bin/migrate_to_systemd.py` 的 ① 阶段会从在跑进程
   `/proc/<pid>/environ` 捕获候选稿（`<项目>/.fenix/systemd.env.candidate` 与
   主树 `.fenix/dashboard-systemd.env.candidate`，0600）。逐键核对，补齐
   load-bearing 键、删除不该带的键（会话身份键已被 denylist 自动剥离）。
2. **dry-run 预演**：`python3 bin/migrate_to_systemd.py --dry-run`（缺省即预演）。
   输出完整编排清单（unit 全文、env 键名摘要、旧链定位、验收项），零副作用。
3. **真切换**：`python3 bin/migrate_to_systemd.py --execute`。编排顺序固定：
   写 unit 不 enable → 拆旧 tmux 链（快照 SIGTERM→轮询→补杀，旧 dashboard
   kill pid 等端口释放）→ `enable --now` 两条 unit → 验收四件套。全程无
   「unit 已启用而旧链仍在」的双托管窗口。
4. **验收**：脚本输出进程/端口/退出码语义/env 冒烟四项结果；人工补一项最小
   agent spawn 冒烟（design：切换冒烟=最小 agent spawn + 网关健康探测）。
5. **回滚配方**（验收失败时）：`systemctl disable --now <项目 unit>
   fenix-dashboard.service` → 旧配方（tmux）重启托管链：
   `tmux new-session -d -s <旧 session 名> "cd <项目根> && python3 .fenix/bin/fenixd_supervisor.py --project-root <项目根>"`。

