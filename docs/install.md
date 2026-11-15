# fenixd 全新环境部署手册（Linux / Windows × Claude Code / dsh web）

> 目标读者：负责部署的 agent / 运维。目标：在**完全干净**的 Linux 或 Windows 机器上，
> 从零装好 fenixd 框架（含全部依赖），并按需装配 agent 执行 harness——
> **Claude Code**（CLI 通道，缺省）与 **dsh web**（DeepSeek Harness web GUI + 插件全家桶）二选一或双装。
>
> 本手册每阶段末尾带**验证门**；上一阶段验证不过不要进入下一阶段。
> 维护约定：版本基线随「版本兼容表」走（dsh 用最新稳定版，其余见表），升级任一组件前先读它。

## 0. 组件总览与支持矩阵

**支持矩阵**（两 OS × 两 harness 全组合支持）：

| | Claude Code harness（§5） | dsh web harness（§6–§7） |
| --- | --- | --- |
| **Linux** | ✅ §1 → §3 → §4a → §5 → §8 | ✅ 全流程 §1 → §2 → §3 → §4a → §5–§7 → §8 |
| **Windows** | ✅ §1 → §3 → §4b → §5 → §8 | ✅ 全流程 §1 → §2 → §3 → §4b → §5–§7 → §8 |

读法：Claude Code 通道只需 §1 前置 + §3 源码 + §4 框架 + §5 harness 配置 + §8 项目初始化；
dsh web 通道额外需要 §2 dsh 运行时、§6 web profile 与插件全家桶、§7 headless bundle。
两通道可共存于同一机器（fenixd 项目内 `agent.harness` 一键切换，见 §5.3）。

> **生效目标（设计承诺）**：安装作用于你**现有的** dsh（桌面版 / `dsh web`）与 Claude Code
> 环境——dsh 插件与配置注册进**现有实例实际加载的 profile**（§6a 先确定 profile，注册完
> 重启现有实例即生效；桌面版与 CLI 共享 `~/.dsh`），Claude Code 技能装进全局
> `~/.claude/skills`（现有 REPL 直接出现 `/fenix-*`）。**全程不新建并行 GUI 环境。**

**组件清单**：

| 组件 | 作用 | 来源 | 适用面 |
| --- | --- | --- | --- |
| fenixd 框架 | Fenix 研发闭环本体（CLI/daemon/dashboard/skills） | `github.com:fenixsoft/fenixd.git` | **两 harness 必装** |
| Claude Code CLI | agent 执行通道 A（每子代理一个 claude 子进程）；同时是 §4 安装器硬门 | npm `@anthropic-ai/claude-code` | **两 harness 必装**（dsh 通道装它只为过安装门，运行时不依赖） |
| dsh（DeepSeek Harness） | agent 执行通道 B 运行时 + web GUI（`dsh web`） | npm `@deepseek-ai/dsh` | 仅 dsh 通道 |
| dsh-bundle | fenixd → dsh 的 headless 派发通道（无人值守执行） | fenixd 仓库内 `dsh-bundle/` | 仅 dsh 通道（`agent.harness: dsh` 时） |
| dsh-plugins | dsh web 的 fenix 插件全家桶（skill 桥接/dashboard 面板/品牌/搜索等） | `github.com:fenixsoft/dsh-plugins.git` | 仅 dsh 通道 |
| NSSM（仅 Windows） | fenixd daemon 服务承载 | 2.24 线，推荐 2.24-101+ | 两 harness（daemon 承载与 harness 无关） |
| systemd user unit（仅 Linux） | fenixd daemon 服务承载 | fenixd 内建（`core/systemd_hosting.py`） | 两 harness |

**版本兼容表（基线；dsh 用最新稳定版）**

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| dsh CLI | **最新稳定版**（npm latest，不钉版） | dsh-bundle 的 peerDependencies 与 fenixd 侧 `dsh_adapter` 版本门按 fenixd 发布线同步维护；dsh 升级后若 bundle 被版本门拦下，按 §6c `allow-version --accept-risk` 显式放行，并重跑 §9 验收。Claude Code 通道无此约束 |
| `@deepseek-ai/cordis` | 随 dsh 宿主运行时解析 | bundle/插件 peer；bundle 目录内独立 `npm install` 仅调试用（§7） |
| Claude Code CLI | 跟随官方最新稳定版 | 无钉扎；fenixd 以原生 CLI 子进程方式调用（claude_adapter），只要求 `claude --version` 可执行 |
| Node.js | ≥ 24 | dsh（`node:sqlite`）、插件构建、dashboard 构建统一基线 |
| pnpm | ≥ 10 | 插件构建与 profile workspace |
| Python | ≥ 3.10 | fenixd 框架 |

## 1. 通用前置（两平台、两 harness 都做）

1. **Node.js ≥ 24** 与 **pnpm ≥ 10**：
   ```bash
   # Linux（nvm）或 Windows（官网安装包）装 Node 24 LTS 后：
   export COREPACK_ENABLE_DOWNLOAD_PROMPT=0   # Windows 用 set；非交互/自动化环境必设（否则 corepack 首次拉取会挂起等输入）
   corepack enable && corepack prepare pnpm@latest --activate
   node --version && pnpm --version        # 期望 v24.x / 10.x
   # corepack 因权限/沙箱失败（EPERM 写 Program Files 等）时的等价替代：
   #   npm install -g pnpm   （自动用 §1 的 registry 镜像）
   # 验证一律以 pnpm --version 输出为准，不依赖安装路径。
   ```
   国内网络建议先切 npm 镜像（registry.npmjs.org 直连可能长时间无输出）：
   `npm config set registry https://registry.npmmirror.com && pnpm config set registry https://registry.npmmirror.com`。
   **pip 同理**：症状为「index 页可达但包文件 403/超时」（第三方镜像劣化）——逐命令覆盖：
   `py -3 -m pip install <pkg> -i https://mirrors.aliyun.com/pypi/simple/`（或
   `-i https://pypi.org/simple`）；自动化环境也可 `setx FENIX_PIP_INDEX_URL <镜像地址>`
   让 install.ps1 自动透传 `--index-url`。
2. **git**（干净机器安装：Windows `winget install Git.Git`；Debian/Ubuntu `apt-get install -y git`；RHEL/Fedora `dnf install -y git`）。
3. **Python 3.10+**（Windows 用 python.org 安装包，勾选「Add to PATH」与 py launcher）。
4. **Claude Code CLI**：`npm install -g @anthropic-ai/claude-code && claude --version`。
   双重身份：①它本身就是 **Claude Code harness 的运行时**（§5）；
   ②fenixd 两个安装器（§4）都把 `claude --version` 作**硬门**（缺失直接 exit 1、不装 skills/PATH）
   ——即使本机最终只用 dsh 通道也必须装。
5. **LLM API Key**：一个 OpenAI 兼容（或 Anthropic 兼容）端点 + key，**提供商任选**
   （bigmodel.cn / DeepSeek / OpenAI / 自建网关均可，手册示例一律提供商无关）。
   **key 的存放优先级**（环境变量不是 key 的家）：
   ① GUI 凭据库——dsh Models 页登录/「从 Claude Code 导入」（§6e），存
   `~/.dsh/.credentials.yaml`；
   ② 项目配置文件——fenixd `.fenix/config.yaml` 的 `llm.providers[i].apikey`
   字段（gitignored，§7）；
   ③ 环境变量**仅作兜底**（手工调试 headless / 无人值守注入），命名一律用中性的
   **`LLM_API_KEY`**（不绑定任何提供商名）。Claude Code 的
   `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` 属 Claude Code 协议自有名，不受此约束。

## 2. 阶段 A：安装 dsh 运行时（仅 dsh web harness；纯 Claude Code 部署可跳过）

> 桌面版用户注意：`dsh` CLI 与桌面版**共享同一份 `DSH_HOME`（`~/.dsh`）**——§6 用 CLI 把
> 插件注册进你现有实例的 profile 后，桌面版重启即加载，不需要再单独装一套 dsh。

```bash
npm install -g @deepseek-ai/dsh          # 安装最新稳定版（不钉版本）
dsh --version                            # 打印版本号即可（长时间无输出先怀疑 registry 连通性，可加 --no-audit --no-fund）
```

> npm `latest` tag 可能落在 rc 线（实测曾为 0.2.2-rc.1），属正常；实际兼容锚以
> dsh-bundle 的 `peerDependencies`（§7）为准，不符时按 §6c `allow-version` 放行。

> 版本说明：手册基线是 dsh **最新稳定版**。fenixd 的 headless bundle（§7）以 peerDependencies
> 声明兼容的 dsh 版本线，版本不符时 dsh 经 `evaluatePluginCompatibility` **跳过 bundle**
> （stderr 报版本错误、不静默降级），fenixd headless 车道随即以 `MISSING_CREDENTIAL` 退出
> ——此时按 §6c 的 `allow-version --accept-risk` 显式放行，或与 fenixd 仓库同步升级 bundle。

## 3. 阶段 B：获取 fenixd 制品（推荐）或源码（开发者）

**两条路径二选一**：默认走 **制品路径**（GitHub Release 预构建包，含 dashboard dist、
dsh-bundle dist、双平台安装脚本——免 Node 工具链）；克隆源码仅供开发者改代码用。

### 3A. 制品路径（默认推荐）

> **解压目标目录：动手前必须向用户确认准确路径**（AI 代部署时以提问卡或直接提问落实，
> 不得自作主张默认）。建议默认值：Linux/macOS `~/fenixd`、Windows `%USERPROFILE%\fenixd`
> （用户目录下，**不要**落在盘根如 `C:\fenixd` 或系统目录）；用户指定后按指定值执行。
> 路径硬性要求见 §4b（仅限 ASCII、无中文/空格）。

Linux/macOS：

```bash
V=$(curl -s https://api.github.com/repos/fenixsoft/fenixd/releases/latest | grep -m1 '"tag_name"' | cut -d'"' -f4)
curl -L -o "fenixd-${V}.tar.gz" "https://github.com/fenixsoft/fenixd/releases/download/${V}/fenixd-${V}.tar.gz"
sha256sum -c <(curl -sL "https://github.com/fenixsoft/fenixd/releases/download/${V}/fenixd-${V}.sha256")   # 两个文件都应 OK
mkdir -p <用户确认的目录> && tar -xzf "fenixd-${V}.tar.gz" -C <用户确认的目录>
# 下文以 <repo> 指代框架根目录（= <用户确认的目录>/fenixd-<版本号>）
```

Windows（PowerShell）：

```powershell
$V = (Invoke-RestMethod "https://api.github.com/repos/fenixsoft/fenixd/releases/latest").tag_name
Invoke-WebRequest "https://github.com/fenixsoft/fenixd/releases/download/$V/fenixd-$V.zip" -OutFile "fenixd-$V.zip"
Expand-Archive "fenixd-$V.zip" -DestinationPath <用户确认的目录>
# <repo> = <用户确认的目录>\fenixd-<版本号>
```

> 制品内容（`VERSION` 文件记录版本）：全量 `bin/`（含 daemon supervisor 与验收器）、
> skills、`fenix-init`、`install.sh` + `install.ps1`、docs、**预构建**的
> `core/dashboard/static/dist` 与 `dsh-bundle/dist`。§4 的 dashboard 构建步与 §7 的
> bundle 构建步对制品安装**全部免做**（改跑各自的 dist 存在性验证）。

### 3B. 源码路径（开发者）

```bash
# <用户确认的目录> 下执行：
git clone https://github.com/fenixsoft/fenixd.git      # HTTPS 为主（免配 SSH key；私有仓库走 credential store）
# 备选：SSH 形态 git@github.com:fenixsoft/fenixd.git（需预置 SSH key）
# 下文以 <repo> 指代 fenixd 仓库根目录（= 上面确认的目录里的 fenixd）
```

> 区别：git clone **不含** `core/dashboard/static/dist`（不入 git）——源码形态必须执行
> §4 的 dashboard 构建步与 §7 的 dsh-bundle 构建步。
>
> **Windows 读者注意**：§6 起的循环命令是 bash 语法——建议在 **Git Bash**（§1 安装的 git 自带）
> 中执行后续章节；PowerShell 用户亦可逐条手动执行。

## 4. 阶段 C：安装 fenixd 框架（平台分叉）

### 4a. Linux

```bash
cd <repo>
bash install.sh
```

安装器（幂等，可重跑）自动完成：

- 依赖检查：python3 ≥ 3.10 / git / claude CLI（硬门）；
- pip 依赖：PyYAML ≥ 6.0、httpx ≥ 0.24 必装，jsonschema ≥ 4.17 可选（api 场景 json_schema 断言用）；
- skills 软链：`<repo>/skills/*` → `~/.claude/skills/`
  （8 个 fenix-* 技能：approve/archive/dashboard/new/process/prototype/setup/status；
  Claude Code 原生扫描该目录，dsh web 经 `fenix-skill-provider` 插件扫描，见 §5.4/§6f）；
- `fenix-init` 命令：软链到 `~/.local/bin`（不在 PATH 时按提示写 shellrc）；
- 用户级默认配置：从 `.fenix/config.user.template.yaml` 生成 `~/.fenix/config.yaml`
  （权限 0600；幂等——已存在则跳过不覆盖，存量文件含 apikey 等用户数据）。
  模板只含注释文档、不固化默认值，未写出的键由框架代码默认值兜底、升级自动跟随；
  全新安装后 Dashboard 设置页「用户级」模式不再提示「配置文件不存在」。

**dashboard 构建**（仅 §3B 源码路径需要；§3A 制品已内置 dist，跳过本步）：

```bash
cd <repo>/core/dashboard/static
npm install --no-audit --no-fund
npm run build            # 产出 dist/index.html（umi/max 构建）
```

**验证门 C-Linux**：

```bash
python3 -c "import yaml, httpx, psutil; print('deps ok')"
fenix-init --help 2>&1 | head -3        # 命令可达
ls ~/.claude/skills/ | grep fenix- | wc -l   # = 8
ls ~/.fenix/config.yaml                      # 用户级默认配置已生成
ls <repo>/core/dashboard/static/dist/index.html
```

### 4b. Windows

> **管理员身份**：本节系统准备（长路径注册表、开发者模式、NSSM 落 `C:	ools` + 机器 PATH）
> 与 §8 服务注册（`nssm install` / `pal.install_unit`）需要管理员 PowerShell。
> **dsh 桌面版也建议以管理员启动**（右键 → 以管理员身份运行，或快捷方式属性勾选）——
> 其派生的 agent 会话继承提升令牌，可直接执行服务操作。自检：
> `whoami /groups` 含 `S-1-16-12288`（High Mandatory Level）即为提权态。
> 权限边界：install.ps1 本体、skills 链接（junction 免提权）、fenix-init shim + 用户 PATH
> 均不需要管理员，仅系统准备与服务注册需要。
>
> **控制台与数据链路编码**（显示面 + 数据面都管）：
> ① 显示：GBK 代码页控制台会把中文/✓ 显示为 `?`——执行前 `chcp 65001`；install.ps1 的
> 结果行是 ASCII 标记（`[OK]/[SKIP]/[WARN]/[FAIL]`），按标记判读；
> ② 落盘解析：PS 5.1 的 `>` 重定向默认 **UTF-16LE**——JSON/UTF-8 产物**禁用裸 `>`**，
> 用 Git Bash 重定向或 `| Out-File -Encoding utf8`（裸 `>` 落盘的 JSON 用 UTF-8 解析必炸 BOM）；
> ③ Python 子进程读流：先 `$env:PYTHONIOENCODING='utf-8'`（或 `PYTHONUTF8=1`），
> 防 GBK 控制台下子进程输出捕获 `UnicodeDecodeError: gbk`；
> ④ 读 UTF-8 文件显式 `Get-Content -Encoding UTF8`。
>
> **PATH 时效性**：机器/用户 PATH 变更**只对新进程生效**——同一 shell 里继续执行需要
> 新 PATH 的命令（如 `pal.install_unit` 探测 nssm），先把目录并入当前进程 PATH
> （`$env:PATH += ';C:\tools\nssm'`）或直接用全路径。
>
> **脚本编码**：`install.ps1` 以 **UTF-8 with BOM** 入库（PS 5.1 中文区域按 ANSI 读无 BOM
> 脚本会 ParserError）。用 git clone / codeload tarball 原样获取即可；**复制粘贴内容重建
> 文件会丢 BOM**，此时先补 BOM 或改用 `pwsh -File`（PS7 不依赖 BOM）。

**系统级一次性准备（管理员 PowerShell）：**

> **路径硬性要求**：fenixd 与 dsh-plugins 的克隆目标路径仅限 ASCII 字母数字、
> 无中文/空格（§3：准确路径必须向用户确认，建议放用户目录下）——含中文/空格的路径会使 `fenix-init.cmd` shim
> 与 link: 解析异常（python 报 `[Errno 22] Invalid argument` 或 `can't open file 'C:\????\...'`）。

```powershell
# 长路径支持（fenixd 骨架 junction/symlink 链上常见 >260 字符路径；未开启会间歇性 FATAL）
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -Value 1
# 开发者模式（允许非管理员创建 symlink；不开则安装器降级 junction/copy）
# 首选：设置 → 更新和安全 → 开发者模式 → 打开；自动化可用：
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock" /v AllowAllTrustedApps /t REG_DWORD /d 1 /f
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock" /v AllowDevelopmentSignedApps /t REG_DWORD /d 1 /f
```

**NSSM（daemon 服务承载，Windows 专用）**——版本基线 **2.24 线，推荐 2.24-101+**
（Win10/Server 2016+ 官方推荐；纯 2.24 在 Win10+ 有官方已知的服务启动问题）。
下载逐级降级（nssm.cc 现状：HEAD 可达但 GET 间歇 503，失败即换下一源，勿反复重试）：
① `https://nssm.cc/ci/nssm-2.24-101-g897c7ad.zip`
② `http://files.evilt.win/nssm/nssm-2.24-101-g897c7ad.zip`（Jellyfin 构建镜像）
③ `winget install -e --id NSSM.NSSM`

```powershell
# 解压后校验 win64\nssm.exe 可执行：
New-Item -ItemType Directory -Force C:\tools\nssm | Out-Null
Copy-Item <解压目录>\win64\nssm.exe C:\tools\nssm\
# 勿用 setx PATH /M（1024 字符截断风险），用 .NET API 追加机器 PATH（pal 只探 PATH 找 nssm）：
$mp = [Environment]::GetEnvironmentVariable('Path','Machine')
[Environment]::SetEnvironmentVariable('Path', ($mp.TrimEnd(';') + ';C:\tools\nssm'), 'Machine')
nssm version                                   # 期望 2.24 或 2.24-101+（新开会话生效）
```

**框架安装（普通 PowerShell，在仓库根）：**

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

> 自动化/CI（无控制台、stderr 被重定向）环境：PS 5.1 会把 pip 的 `WARNING: The script xxx.exe is
> installed in ... not on PATH` 转成终止性 NativeCommandError 把安装器中途打断——先手工
> `py -3 -m pip install --no-warn-script-location psutil pywin32 PyYAML httpx jsonschema`
> 再跑安装器（实测 100% 通过）。

安装器（幂等）自动完成：

- 依赖检查：python 3.10+（py launcher 优先）/ git / claude CLI（硬门）；
- pip 依赖（`requirements-win32.txt` 同源）：`psutil>=5.9`、`pywin32>=306` 必选，
  `PyYAML>=6.0`、`httpx>=0.24` 基线，`jsonschema>=4.17` 可选——
  探测用 `importlib.util.find_spec`（pip 包名 ≠ import 模块名：pywin32→win32api、PyYAML→yaml）；
- skills 链接：symlink → junction → copy 三级降级（copy 形态升级需重跑安装器刷新）；
- `fenix-init.cmd` shim 写入 `%LOCALAPPDATA%\Fenixd\bin` 并加入用户 PATH；
- 用户级默认配置：从 `.fenix\config.user.template.yaml` 生成 `%USERPROFILE%\.fenix\config.yaml`
  （幂等——已存在则跳过不覆盖；语义同 4a Linux 段说明）。

**dashboard 构建**（仅 §3B 源码路径需要；§3A 制品已内置 dist，跳过——同 4a：`cd <repo>\core\dashboard\static` 后 `npm install` + `npm run build`）。

**验证门 C-Windows**：

```powershell
py -3 -c "import psutil, win32api, yaml, httpx; print('deps ok')"
fenix-init 2>&1 | Select-Object -First 3
(Get-ChildItem $env:USERPROFILE\.claude\skills -Filter "fenix-*").Count   # = 8
Test-Path $env:USERPROFILE\.fenix\config.yaml                             # True（用户级默认配置）
Test-Path <repo>\core\dashboard\static\dist\index.html                  # True（dashboard 构建产物，与 §4a 门对齐）
```

## 5. 阶段 D：agent harness 选型与 Claude Code 通道

### 5.1 harness 模型

fenixd 的每个子代理（SPEC 实现、验证 Agent 等）跑在一种 harness 进程边界上，
由项目 `.fenix/config.yaml` 顶层 `agent.harness` 选择：

| 值 | 语义 | 依赖 |
| --- | --- | --- |
| `claude`（**缺省**） | 每个子代理一个 Claude Code CLI 子进程（原生 stream-json 事件流） | 仅 claude CLI（§1.4），**无任何 dsh 组件** |
| `dsh` | DSH headless 通道（经 fenix-dsh-bundle 派发） | §2 dsh + §7 bundle 全链 |

要点：配置**热载**，只影响下一次派发（在飞 run 按原通道跑到收口，排水语义不截断）；
`dsh` 通道派发前置健康检查校验 bundle 安装/版本/挂载，不通过该次派发 fail-fast 终态，
**绝不静默回退 claude**；非法值回退 `claude` 并 WARNING。
详细切换/回切运维见 `docs/help/dsh-harness-runbook.md`。

### 5.2 Claude Code CLI 配置（两平台一致）

**认证三选一**：

1. 交互登录：终端跑 `claude` 按引导登录 Anthropic 账号（官方端点）。
2. 环境变量指向兼容端点（自建网关/第三方 Anthropic 兼容 API）：
   ```bash
   # 写入 shellrc（Linux）或系统环境变量（Windows），fenixd spawn 子进程时继承：
   export ANTHROPIC_BASE_URL="https://open.bigmodel.cn/api/anthropic"
   export ANTHROPIC_AUTH_TOKEN="<key>"    # 值即你的 LLM API key（任何提供商，key 本身与变量名无关）
   ```
3. `~/.claude/settings.json` 固化（Windows 为 `%USERPROFILE%\.claude\settings.json`）：
   ```json
   { "env": { "ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic",
              "ANTHROPIC_AUTH_TOKEN": "<key>" } }
   ```

> 可选：cc-switch 是第三方的 provider 管理器（自带数据库）。fenixd 的 cc-import 插件
> （§6b）能把 cc-switch 里的 provider 一键导入 dsh web Models 页——用它可让两个
> harness 共享同一份端点配置，不用各自维护。

**验证门 D-claude**：

```bash
claude --version                       # 版本号可打印
claude -p "reply with exactly: ok"     # headless 一问一答冒烟（认证+端点全链）
```

### 5.3 fenixd 项目侧接入

```yaml
# <项目>/.fenix/config.yaml —— 显式声明（缺省即 claude，写明以免歧义）
agent:
  harness: claude
```

无更多配置：daemon 每轮 dispatch 直接 spawn `claude` 子进程（继承上面的环境变量），
无需 bundle、无需 dsh。切到 dsh 通道只需把该键改 `dsh` 并完成 §6–§7（热载生效）。

### 5.4 skills 与入口

- **CLI**：Claude Code 原生扫描 `~/.claude/skills/`——REPL 内按 "/" 即见
  `/fenix-new /fenix-status /fenix-setup …`（§4 安装的 8 个技能）。
- **web 面板**：Claude Code 通道没有 dsh web GUI；fenixd 自己的 dashboard（§8）直接
  浏览器访问 `http://127.0.0.1:8787`（对外经 frp 等透传时用公网地址），
  这是 harness 无关的 fenixd 原生 web UI。

## 6. 阶段 E：dsh web harness——profile 与 dsh-plugins 全家桶（仅 dsh 通道）

> 每个 dsh 实例（桌面版 / `dsh web`）都有一个**装配 profile**，位于 `$DSH_HOME/profiles/<P>/`
>（`DSH_HOME` 缺省 `~/.dsh`，Windows 为 `%USERPROFILE%\.dsh`；`<P>` 的确定见 §6a）。
> 装配 = **pnpm workspace 依赖（link: 形态）** + **package.json bundles 数组** + **cordis.patch.yml loader 条目** 三件套。

### 6a. 确定你现有 dsh 实例的 profile（关键：作用于现有环境，不建并行环境）

> **设计承诺**：本阶段的全部注册——插件、loader 条目、provider 配置——都写进
> **你正在使用的 dsh 实例（桌面版 / `dsh web`）实际加载的那个 profile**。
> 装完重启该实例即可看到变化；**全程不新建、不并行另一套 GUI 环境**。
> dsh 桌面版与 CLI 共享同一个 `DSH_HOME`（`~/.dsh` / `%USERPROFILE%\.dsh`），
> 因此用 `dsh plugin` 命令写进 profile 的内容，桌面版重启后同样生效。
> 桌面版与 CLI 的**版本可能不同步**（如桌面版内置 rc.3、npm CLI 为 rc.1）：
> 各 profile 的插件版本门由各自宿主判定（fenix profile 按 CLI、desktop 按桌面版），
> 共享 DSH_HOME 但不共享版本裁决。

先确定 profile 名，下文统一以 `<P>` 代指：

- **dsh 桌面版用户**：桌面版 设置页 显示当前 profile（通常为 `desktop`）；`$DSH_HOME/profiles/`
  下 `desktop`（Electron 专用，**CLI 不可管理**——`dsh plugin` 对它硬性拒绝，报
  `profile "desktop" is managed exclusively by the Electron application`）或 `web`（CLI 出厂）；
- **`dsh web` CLI 用户**：你的启动命令里 `--profile` 参数；从未指定过则是出厂 `web`。

```bash
dsh plugin --profile <P> list     # 能列出（可能为空）插件清单即 profile 正确、可写
```

> **desktop profile 的插件装配走专用路径（不用上面命令）**，见 §6c 末尾的分流说明；
> `dsh plugin` 命令仅适用于 CLI 自建/管理的 profile（`web`、`fenix` 等）。
>
> `web` 是出厂 profile，**不能**作为 `--from-default-profile` 的拷贝目标（带了直接报错）；
> 首次 `dsh plugin --profile <P> add ...`（§6c）会自动初始化 profile 目录并自动维护依赖与 bundles 数组。

### 6b. 获取 dsh-plugins 制品

**制品路径（默认）**：dsh-plugins 为**私库**，Release 资产下载需带 token（§3A 同款
GitHub token；`fenixsoft` 凭据）。插件 `lib/` 已在发布流水线预构建——**免 Node 工具链**：

```bash
# Linux/macOS（Git Bash 同理；<token> 换为有 dsh-plugins 读取权限的 token）
# 注意：私库资产的 browser_download_url 对 header 下载返回 404——必须走 API
# 资产端点（Accept: application/octet-stream），两步：查 release → 按 asset id 下载
REL=$(curl -s -H "Authorization: Bearer <token>" https://api.github.com/repos/fenixsoft/dsh-plugins/releases/latest)
V=$(echo "$REL" | grep -m1 '"tag_name"' | cut -d'"' -f4)
AID=$(echo "$REL" | python3 -c "import json,sys; d=json.load(sys.stdin); print(next(a['id'] for a in d['assets'] if a['name']=='dsh-plugins-'+d['tag_name']+'.zip'))")
curl -sL -H "Authorization: Bearer <token>" -H "Accept: application/octet-stream" \
     -o "dsh-plugins-${V}.zip" "https://api.github.com/repos/fenixsoft/dsh-plugins/releases/assets/${AID}"
unzip -q "dsh-plugins-${V}.zip" -d <用户确认的目录>
# 下文以 <plugins> 指代 <用户确认的目录>/dsh-plugins-<版本号>（内含 11 个插件目录，lib/ 已构建）
```

```powershell
# Windows（PowerShell）
$H = @{ Authorization = "Bearer <token>" }
$Rel = Invoke-RestMethod -Headers $H "https://api.github.com/repos/fenixsoft/dsh-plugins/releases/latest"
$V = $Rel.tag_name
$Aid = ($Rel.assets | Where-Object name -eq "dsh-plugins-$V.zip").id
Invoke-WebRequest -Headers @{ Authorization = "Bearer <token>"; Accept = "application/octet-stream" } `
    "https://api.github.com/repos/fenixsoft/dsh-plugins/releases/assets/$Aid" -OutFile "dsh-plugins-$V.zip"
Expand-Archive "dsh-plugins-$V.zip" -DestinationPath <用户确认的目录>
# <plugins> = <用户确认的目录>\dsh-plugins-<版本号>
```

**源码路径（仅开发者）**：`git clone https://github.com/fenixsoft/dsh-plugins.git`
后逐插件安装依赖并**条件构建**（部分插件免构建——`exports` 直指仓库根源码；
Node ≥ 24 / pnpm ≥ 10；制品路径用户**整段跳过**）：

```bash
for p in cc-import fenix-dsh-auth fenix-dsh-brand-fenix fenix-dsh-chat-polish \
         fenix-dsh-clipboard-fallback fenix-dsh-dashboard-bridge \
         fenix-dsh-session-advanced-search fenix-dsh-session-grouper \
         fenix-dsh-settings-dock fenix-skill-provider; do
  (cd <plugins>/$p && pnpm install && pnpm run --if-present build) || echo "BUILD FAIL: $p"
done
```

**验证门 E-build**：以各插件 package.json 的 **`exports` 字段为准**，逐条核验其指向的
文件存在（有构建步的插件产物在 `lib/`，免构建插件直指仓库根文件；部分插件 `main` 与
`exports` 双写）。`Command "build" not found` = 该插件免构建，**预期行为**，不是失败。

**bundle / plain 分流清单**（决定装载机制，§6c 注册前先判别）：

- 声明 `dsh.bundle`（→ 进 bundles 数组，宿主侧启动挂载）：fenix-dsh-auth、
  fenix-dsh-chat-polish、fenix-dsh-clipboard-fallback、fenix-dsh-session-advanced-search、
  fenix-dsh-settings-dock；
- 未声明（**只能**走 §6d loader insert，不得进 bundles）：cc-import、fenix-dsh-brand-fenix、
  fenix-dsh-dashboard-bridge、fenix-dsh-session-grouper、fenix-skill-provider。

判别命令（在 `<plugins>` 目录执行）：

```bash
node -e "for (const p of require('fs').readdirSync('.').filter(d=>!d.startsWith('.'))) { try { const j=require('./'+p+'/package.json'); if(j.dsh) console.log(p.padEnd(36), j.dsh.bundle?'bundle':'plain', JSON.stringify(j.peerDependencies&&Object.keys(j.peerDependencies).filter(k=>k.startsWith('@deepseek-ai'))||[])) } catch(e){} }"
```
（第三列输出 peer 对 `@deepseek-ai/*` 的钉版——精确钉版在更新的 dsh 上会被版本门跳过，
属预期，见 §10「桌面版版本门」。）

> `pnpm add link:` / plugin-manager 安装时的警告
> `linked in dependency will not resolve the peer dependencies … use file:` 为**预期噪音**：
> peer 由 dsh 宿主运行时解析，不代表失败，勿中断重试。

### 6c. 注册进 profile workspace

```bash
cd ~/.dsh/profiles/<P>
for p in cc-import fenix-dsh-auth fenix-dsh-brand-fenix fenix-dsh-chat-polish \
         fenix-dsh-clipboard-fallback fenix-dsh-dashboard-bridge \
         fenix-dsh-session-advanced-search fenix-dsh-session-grouper \
         fenix-dsh-settings-dock fenix-skill-provider; do
  dsh plugin --profile <P> add "link:<plugins绝对路径>/$p"
done
```

> Windows 下 link 路径写绝对盘符形态：`dsh plugin --profile <P> add "link:C:\repo\dsh-plugins\cc-import"`。
> ⚠ 必须用 `link:` 软链形态——`file:` 拷贝装会使副本失去 `node_modules`、peer 断链（真机踩过）。
>
> `plugin add` 报版本风险拦截（`to accept the risk, run: dsh plugin ... allow-version ...`）时，
> 按提示显式放行后重装：`dsh plugin --profile <P> allow-version <pkg>@<version> --dsh-version <已装dsh版本> --accept-risk`。
> 注册时打 `warning: declares no dsh.bundle — installed as a plain dependency` 也是**预期行为**
> （这类插件靠 §6d 的 insert 条目装载，不进 bundles）。**不要**把它们手工塞进
> `dsh.profile.bundles`——boot 时会被 `skip with errors` 拒载（E2E 实证）。

**非 loopback 主机名访问 GUI 时必装**（frp/域名反代场景；仅 127.0.0.1 访问可跳过）：

```bash
dsh plugin --profile <P> add github:6mt/dsh-plugin-loopback-trust
```

`plugin add` 会自动维护 `dsh.profile.bundles`（声明了 `dsh.bundle` 的插件自动入列，无需手工编辑）。
仅在绕过 plugin add 手工改 package.json 时才需要对照下面的形状：

```jsonc
"dsh": { "profile": { "bundles": [
  "@deepseek-ai/dsh-base",
  "@deepseek-ai/dsh-web-app",
  "dsh-plugin-loopback-trust",     // 非 loopback 访问时
  // …保留既有条目（仅列声明了 dsh.bundle 的插件；plain 型禁止入列）
] } }
```

**desktop profile（桌面版）专用装配路径**——`dsh plugin` 对它不可用，按分流走：

1. **bundle 型插件（§6b 清单前 5 个）**：用桌面版 GUI 的插件管理入口（plugin-manager）
   安装，spec 形态 `link:<plugins 绝对路径>/<插件名>`（**正斜杠**；⚠ 路径必须是
   **你的真实克隆目录**——照抄文档示例路径会失败）。失败不污染 profile
   （package.json 与 bundles 均不被改动），改正路径直接重装即可。装完即时挂载并
   自动写入 `dsh.profile.bundles`。agent 读者注意：plugin-manager 同时暴露 agent 工具面
   （`plugin_manager` 工具），注册 bundle 型无需人工点 GUI；
2. **plain 型插件（后 5 个）**：手工编辑 `%USERPROFILE%\.dsh\profiles\desktop\package.json`
   的 `dependencies`（键值用 `link:C:/...` **正斜杠**形态，与官方写入一致），然后在
   profile 目录执行 `pnpm install`（junction 链接自动生成）；cordis.patch.yml 的
   `- insert:` 条目**只写这 5 个 plain 型**——bundle 型已由 plugin-manager/bundles
   挂载，重复 insert 有双重装载风险；
3. 装完**完全退出桌面版（含托盘）再启动**加载（plain 型与 insert 条目仅启动时装配）。

同时确认 profile 的 `pnpm-workspace.yaml` 含（出厂模板已带前两项）：

```yaml
packages:
  - .
nodeLinker: hoisted
autoInstallPeers: false
# 出厂模板不含 minimumReleaseAge，无需配置 exclude；
# 仅当安装报 minimumReleaseAge 拦截时再加：
# minimumReleaseAgeExclude:
#   - <pkg>@<version>
```

### 6d. loader 条目（cordis.patch.yml）

> 本节样例为 **CLI 自管 profile 的口径**（全量 insert）；桌面版只 insert plain 型（§6c）。
> 文件结构：**顶层数组**。既有 `- id:` 条目（如出厂的 bundle 配置覆盖、已有
> `llm-pi-ai` / `agent-default-model` provider）**原样保留**——尤其 profile 已有
> provider 配置时不要重抄本节样例（会造重复）；只把下面的 `- insert:` 块作为
> **新的顶层数组项追加在末尾**。

编辑 `~/.dsh/profiles/web/cordis.patch.yml`，加入插件 insert 列表：

```yaml
- insert:
    - id: cc-import
      name: cc-import
    - id: fenix-dsh-dashboard-bridge
      name: fenix-dsh-dashboard-bridge
    - id: fenix-dsh-auth
      name: fenix-dsh-auth
    - id: fenix-dsh-brand-fenix
      name: fenix-dsh-brand-fenix
    - id: fenix-dsh-chat-polish
      name: fenix-dsh-chat-polish
    - id: fenix-dsh-clipboard-fallback
      name: fenix-dsh-clipboard-fallback
    - id: fenix-dsh-session-advanced-search
      name: fenix-dsh-session-advanced-search
    - id: fenix-dsh-session-grouper
      name: fenix-dsh-session-grouper
    - id: fenix-dsh-settings-dock
      name: fenix-dsh-settings-dock
    - id: fenix-skill-provider
      name: fenix-skill-provider
```

> ⚠ dsh patch 语义要求**容器键**：裸写 `- id:/name:` 列表项会被当作未知 target
> **静默跳过**（不报错、插件不装载）。必须写成 `- insert:` 列表。

### 6e. LLM provider 配置（cordis.patch.yml）

```yaml
- id: llm-pi-ai
  name: "@deepseek-ai/dsh-llm-pi-ai"
  config:
    providers:
      my-llm:                            # 路由名自取（提供商无关）
        apiKeyEnv: LLM_API_KEY           # 兜底：从环境变量读 key（中性名，任何提供商）
        api: anthropic-messages          # Anthropic 兼容端点用此线协议；OpenAI 兼容端点改 openai-completions
        baseURL: https://open.bigmodel.cn/api/anthropic
        models:
          - id: glm-5.3-flash
            contextWindow: 1000000
            input: [text, image]
        displayName: bigmodel.cn
- id: agent-default-model
  name: "@deepseek-ai/dsh-agent-default-model"
  config:
    provider: bigmodel-cn
    model: glm-5.3-flash
```

> 线协议错配（端点是 Anthropic 兼容却配 `openai-completions`）= TRANSPORT 断流，验收期必踩。
>
> **key 优先走 GUI 凭据库，不写进本节**：Models 设置页直接登录提供商，或「从 Claude Code
> 导入」（cc-import 桥接 cc-switch 数据库）——key 存进 harness 凭据库
> （`~/.dsh/.credentials.yaml`，文件形态，不进环境变量、不进配置文件）。
> 本节手工声明（apiKeyEnv 兜底）仅在 GUI 路径覆盖不到时使用。

### 6f-0. 生效时机（排障前先读）

| 变更 | 何时生效 | 动作 |
| --- | --- | --- |
| bundle 型插件注册（plugin-manager / plugin add） | 宿主侧**即时挂载** | 无需重启 |
| 客户端 UI 模块（inject 进 ui-* 的面板/按钮） | **页面重新加载**时拉取 | 浏览器刷新即可 |
| plain 型依赖 + `- insert:`（cordis.patch.yml） | 带 HMR 的 dsh 会**热应用** profile patch（实测 insert 写入后随即 active）；**进程启动时**装配是权威兜底 | 热应用未命中的变更才需要托盘完整退出重启 / 重启 dsh web |

注册后 GUI"没变化"的排查顺序：先插件清单（plugin-manager 页/`list_plugins`）确认装载状态，
再做页面重载，最后才完整重启（验收口径以完整重启后为准）。

### 6f. 重启你现有的 dsh 实例并验证门 E

插件与 loader 配置在实例启动时装配——**让注册生效 = 重启你现有的实例**：

- **dsh 桌面版**：完全退出（含**系统托盘右键退出**，不是关窗口）后重新打开；
- **`dsh web`（CLI）**：停掉现有进程，用你原来的启动命令重开，例如
  （非 loopback 域名访问加 `--trusted-host`，可重复多组）：

```bash
dsh --profile <P> --no-open --port 3080 --trusted-host home.example.com:3080
```

- **全新机器**（还没有任何 dsh 实例在跑）：上面这条命令就是你的首次启动。

逐项确认（都在**重启后的现有 GUI** 里验）：

1. 打开 GUI（桌面版即原入口；`dsh web` 为 `http://127.0.0.1:3080` 或 trusted-host，token 见启动日志首行）；
2. 输入框按 "/"：菜单出现 `/fenix-new /fenix-status /fenix-setup …`
   —— 这是 `fenix-skill-provider` 在扫 `~/.claude/skills` 下 `fenix-*`（§4 安装的技能），
   来源目录新增 skill 数秒内自动反映，无需重启。
   ⚠ 注意：`/` 菜单出现 fenix 条目**不足以证明插件生效**——dsh 原生 skill-filesystem
   本就扫 `~/.claude/skills`；确认插件本体以 plugin-manager 插件清单为准；
3. fenixd dashboard 启动后（§8），侧栏出现 概览/项目/设置/运维/帮助 条目
   —— `fenix-dsh-dashboard-bridge` 反代 `/fenix-dashboard/` 生效；
4. Models 设置页底部「从 Claude Code 导入」按钮可见（cc-import；需 cc-switch 数据库才有候选，可选项）。
5. 细粒度验收复用各插件自带清单（深链/SSE/502 降级/pattern 覆盖等逐项口径）：
   `<plugins>/docs/help/` 下 cc-import / fenix-dashboard-bridge / fenix-skill-provider /
   dsh-session-grouper 各有「安装步骤 + 真机验收清单」。

## 7. 阶段 F：dsh headless 派发通道（dsh-bundle；仅 `agent.harness: dsh` 需要）

> 定位说明：`fenix` 是 headless 派发专用的**工作 profile**（无人值守执行走它），
> 你的桌面版 / `dsh web` **不会**显示它、也不因它改变——GUI 层的全部变化来自 §6。

> fenixd 以无人值守 `dsh headless` 派发实现/验证工作（SPEC 实现、验证 Agent 全走此通道）。
> Claude Code 通道（§5.3）不走这里；装了 bundle 但 `agent.harness` 仍为 `claude` 时也不使用。

```bash
# §3A 制品路径：dsh-bundle/dist 已预构建，下面整段构建步跳过，
# 直接验证后挂载（test -f 那行照跑）：
test -f <repo>/dsh-bundle/dist/index.js && test -f <repo>/dsh-bundle/dist/session-tidy-helper.mjs

# —— 仅 §3B 源码路径需要执行构建（dist/ 不入 git，package.json main/exports 指向 dist/）——
# cd <repo>/dsh-bundle && npm install --legacy-peer-deps
# ↑ bundle 目录内 npm install 仅作独立调试用：dsh 各子包 peer 区间不一致（cordis ~4.0.x vs ~4.1.x），
#   严格 npm 必 eresolve 失败；运行时链路经 plugin add 由 dsh 宿主解析 peer，不受影响。
# pnpm run build      # 产出 dist/index.js 等 11 个文件
# 无 pnpm 或后台无控制台环境 pnpm 挂死时，直接调 tsc：
#   node node_modules\typescript\bin\tsc -p tsconfig.json
#   node -e "require('node:fs').copyFileSync('dist/session-tidy-helper.js','dist/session-tidy-helper.mjs')"
Test-Path <repo>\dsh-bundle\dist\index.js    # PowerShell；Git Bash 用 test -f …，True 才继续

# fenix profile：首次 plugin add 自动创建（headless 同为出厂语义，不能用 --from-default-profile 拷贝）
DSH_HOME=~/.dsh dsh plugin --profile fenix add "link:<repo绝对路径>/dsh-bundle"
```

确认 `~/.dsh/profiles/fenix/package.json` 形如。⚠ `plugin add` 自动写 dependencies，
但 **bundles 数组需人工核对**：dsh CLI 0.2.2-rc.1 实测只自动写入
`["@deepseek-ai/dsh-base", "fenix-dsh-bundle"]`，**不含 `@deepseek-ai/dsh-headless`**
——手工补一行即可（该包随 dsh 安装分发，可直接解析；补后 `--dump-config` 应见 headless 层被 patch）：

```json
{
  "name": "dsh-profile-fenix",
  "private": true,
  "dependencies": {
    "fenix-dsh-bundle": "link:<repo绝对路径>/dsh-bundle"
  },
  "dsh": {
    "profile": {
      "bundles": [
        "@deepseek-ai/dsh-base",
        "@deepseek-ai/dsh-headless",
        "fenix-dsh-bundle"
      ]
    }
  }
}
```

模型三要素以启动期 `--patch` 提供（fenixd spawn 侧会自动渲染；手工调试用同款 YAML）：

```yaml
- id: fenix-model-config
  config:
    model:
      provider: fenix-gateway        # 路由名（任取）
      baseURL: https://open.bigmodel.cn/api/anthropic
      apiKeyEnv: LLM_API_KEY             # 中性名；fenixd 派发链路实际由项目 config.yaml 驱动（见下）
      model: glm-5.3-flash
      api: anthropic-messages        # Anthropic 兼容端点必配（缺省 openai-completions）
- id: agent-default-model
  config:
    provider: fenix-gateway          # 与上面 model.provider 同名——缺此条 headless 会走
    model: glm-5.3-flash             #   dsh 原生默认路由，报 MISSING_CREDENTIAL: no API key
```

**验证门 F**：

```bash
# 手工调试可先 --patch 指定模型三要素（fenixd spawn 侧自动渲染，无需手工时省略此参）：
dsh --profile fenix --patch <模型patch.yaml> "say ok"
dsh --profile fenix --dump-config | grep fenix      # Git Bash；PowerShell 改 Select-String fenix
dsh --profile fenix "say ok"                        # headless 一问一答冒烟
# PowerShell 临时注入 key（Git Bash 用 export LLM_API_KEY=<值>）：
#   $env:LLM_API_KEY = "<值>"
```

> **headless 凭据解析与 key 的正确存放**：fenixd 派发 headless 时按项目
> `.fenix/config.yaml` 的 `llm.providers`（含字面 **`apikey`** 字段，gitignored 文件形态）
> 渲染 spawn 侧配置——**这是 key 的首选存放处**，无需环境变量。仅当你绕过 fenixd 手工
> 调试 `dsh --profile fenix "say ok"` 时，才需要临时给 `apiKeyEnv` 指名的变量（中性名
> `LLM_API_KEY`）export 值；daemon/NSSM 无人值守形态经 `AppEnvironmentExtra` 注入同名变量。
> `~/.dsh/.credentials.yaml` 凭据库**仅对交互式 GUI 通道生效**，headless 车道不读它。

## 8. 阶段 G：项目内初始化与常驻 daemon（harness 无关）

```bash
mkdir -p ~/myproj && cd ~/myproj
fenix-init . --name myproj --type web     # 生成 .fenix 骨架（skills 链接/命令基线）
```

常驻 daemon（任务调度/看护）由 fenix 自身安装，与 harness 选择无关，两平台形态不同：

| | Linux | Windows |
| --- | --- | --- |
| 承载 | systemd user unit（`core/systemd_hosting.py` 自动安装 enable --now） | NSSM 服务 `fenixd-<名>-<8位hex>`（`pal.install_unit` 返回 JSON 的 `unit` 字段为准） |
| 前置 | systemd user session 可用（WSL1 不支持，用 WSL2） | §4b 已装 NSSM 且在 PATH |
| 操作 | 会话内 `/fenix-setup`（或 `pal.install_unit(root)`） | 同左（NSSM 缺失时驱动显式报错） |
| 服务核查 | `systemctl --user status fenixd-<name>` | 服务名带 hash 后缀：`Get-Service *fenixd*` 先列实际名（或取 `pal.install_unit` 返回 JSON 的 `unit` 字段），再 `nssm status <实际名>`（态 4=RUNNING；判态用 SCM/`Get-Service`，勿正则解析 NSSM 输出——它原生 UTF-16LE） |

> **daemon ≠ dashboard**：daemon 只负责任务调度看护，服务 Running 后 8787 **并不监听**——
> dashboard 是独立进程（下方 `fenix_dashboard.py --serve`），需另行常驻
> （Windows 无人值守可再建一个 NSSM 服务跑 `py -3 <repo>\bin\fenix_dashboard.py --serve`，AppDirectory=仓库根）。
> ⚠ `nssm set AppStdout/AppStderr` 指向日志文件前，**必须先确保其父目录存在**
> ——NSSM 不递归创建目录，目录缺失时服务安装成功但立即停止且**零日志**（排障最坑的形态）。
> 提示：fenix-init 已创建的是 `<项目>\.fenix\logs\`（骨架固定布局，项目根**没有** logs/）；
> 服务日志指向 `.fenix\logs\` 可免预建，指向其他位置（含项目根）必须先
> `New-Item -ItemType Directory -Force <日志目录>`。
>
> 不走 `/fenix-setup` REPL 的无人值守 daemon 等价安装（Windows 实测可用）：
>
> ```bash
> py -3 -c "import sys,json; sys.path.insert(0,r'<repo>'); from core.platform.win32 import install_unit; print(json.dumps(install_unit(r'<项目绝对路径>')))"
> ```

**Windows 服务化部署（SYSTEM 账户隔离坑，服务化必读）：**

- **dashboard registry**：服务跑 LocalSystem 时读的是
  `C:\Windows\System32\config\systemprofile\.config\fenixd\dashboard.yaml`，
  与交互用户 `--add-project` 写的主目录配置不同 → `/api/projects` 返回空。
  处置：把用户侧 dashboard.yaml 拷到 systemprofile 同路径并重启服务；
  或 `nssm set <name> ObjectName .\<你的用户>` 让服务以交互用户身份运行。
  ⚠ 这是**持续同步**不是一次性拷贝——以后每次 `--add-project` 都要重新同步
  （或让服务跑交互用户身份，一劳永逸）。
- **skills 目录**：服务化后 `fenix-skill-provider` 扫描的是**服务账户**的 `~/.claude/skills`（空）
  → GUI "/" 菜单无 /fenix-*。处置：junction 对齐
  `cmd /c mklink /J "C:\Windows\System32\config\systemprofile\.claude" "C:\Users\<你>\.claude"`。
- **环境变量**：服务的 `DSH_HOME` 等用 `nssm set <name> AppEnvironmentExtra "DSH_HOME=C:\Users\<你>\.dsh"` 显式注入
  （如走环境变量兜底，key 同法注入 `LLM_API_KEY=<值>`；首选仍是项目 config.yaml 的 apikey 字段）。
- **install_unit 报「需要 NSSM: nssm.exe 不可用」**：刚装完 NSSM/改完 PATH 时，当前进程
  仍持旧 PATH（PATH 变更仅新进程生效）——先 `$env:PATH += ';C:\tools\nssm'` 或用全路径重试。
- **服务化前确认 Python 对 SYSTEM 可见**：服务跑 LocalSystem，若 python.exe 或依赖包
  落在用户 site（`%APPDATA%\Python\...`），服务会 ModuleNotFoundError 秒退（日志可能为空）。
  处置：依赖装系统级/解释器目录，或 `nssm set <name> AppEnvironmentExtra "PYTHONPATH=<用户site路径>"`。

dashboard 就绪验证（fenixd 原生 web UI，两 harness 共用；dsh web 里由 bridge 反代嵌入）：

```bash
python3 <repo>/bin/fenix_dashboard.py --serve   # 默认 127.0.0.1:8787
curl -s http://127.0.0.1:8787/api/projects      # 返回 JSON 即通
```

## 9. 端到端验收清单（按 harness 分组）

### 9.0 框架可执行实测：真实创建 myproj（必做）

验收不是对着清单打勾——先真实建一个项目跑通闭环（路径任选，下称 `<work>`；Linux/macOS
用 `python3`，Windows 用 `py -3`；下述命令在 Git Bash / bash 中执行，PowerShell 自行换
`Select-String` 等价形态）：

```bash
cd <work>
fenix-init . --name myproj --type web          # 生成 .fenix 骨架（config.yaml/STATE.md + core/bin/tests 链接）
# Windows 注意：fenix-init 不代建 git 仓库，如需版本化自行 git init + 首提交
# 骨架链接位于 .fenix/ 下且带隐藏属性——核验用 Get-ChildItem -Force（bash: ls -la），
# 项目根直接 ls 看不到 bin/core 不代表失败
python3 bin/fenix_dashboard.py --serve &       # Linux/macOS（项目根有 bin 链接）
# Windows 用仓库脚本路径：py -3 <repo>\bin\fenix_dashboard.py --serve
#   （项目内等价路径 .fenix\bin\fenix_dashboard.py；§8 服务化形态则直接看服务）
sleep 3 && curl -s http://127.0.0.1:8787/api/projects   # 返回 JSON 且含 myproj 即框架可执行
```

GUI 内最后一步闭环：输入框 `/fenix-new "冒烟测试"` → 创建 SPEC（`spec/` 下出现目录、
STATE.md 注册该 SPEC）→ daemon 存活（`<work>/myproj/.fenix/fenixd/` runtime 有 pid 且进程在）。
全过 = fenix 框架在本机可执行，继续逐项验收。

**通用（两 harness 都验）**：

- [ ] `node --version` ≥ 24；`python3 --version` ≥ 3.10；`claude --version` 可执行
- [ ] 项目内 `/fenix-setup`：daemon 服务 RUNNING（systemctl / nssm status）
- [ ] dashboard 8787 `curl /api/projects` 返回 JSON
- [ ] `/fenix-new "冒烟测试"` 能创建 SPEC（实际走当前 `agent.harness` 指向的通道）
- [ ] （Windows）`nssm version` 输出 2.24 或 2.24-101+；`LongPathsEnabled` = 1；`py -3 -c "import win32api"` 不报错

**Claude Code harness（§5）追加**：

- [ ] `claude -p "reply with exactly: ok"` 冒烟通过（认证/端点全链）
- [ ] claude REPL "/" 菜单含全部 `/fenix-*` 条目
- [ ] `.fenix/config.yaml` `agent.harness: claude`（或缺省）

**dsh web harness（§6–§7）追加**：

- [ ] `dsh --version` 打印版本号（非空；最新稳定版）
- [ ] `dsh --profile fenix --dump-config | grep fenix` 非空（bundle 挂载）
- [ ] **重启后的现有 GUI**（桌面版 / `dsh web`）："/" 菜单含全部 `/fenix-*` 条目
- [ ] **重启后的现有 GUI** 侧栏出现 Fenix 面板（dashboard-bridge）

## 10. 故障排查速查

| 症状 | 根因 | 处置 |
| --- | --- | --- |
| 安装器 `[FAIL] missing: claude` | claude CLI 是安装硬门（两 harness 都要） | `npm i -g @anthropic-ai/claude-code` |
| `claude -p` 报认证失败 | `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` 未导出或未登录 | §5.2 三种方式之一补齐；fenixd spawn 继承的是 shell 环境变量 |
| claude REPL "/" 无 `/fenix-*` | skills 未装（§4 验证门应=8） | 重跑安装器；`ls ~/.claude/skills/` |
| headless 车道 `MISSING_CREDENTIAL` exit 1 | bundle 被 peer 版本校验跳过，或 key 未随进程环境/项目配置就位 | 核对 dsh 版本钉扎表；项目 config.yaml `apikey` 字段（首选）或 `LLM_API_KEY` 环境变量兜底 |
| 配了 `agent.harness: dsh` 但派发 fail-fast | bundle 未挂载/版本不在白名单/实例不健康 | 设计如此（不静默回退）；按报错修链路或临时 `harness: claude` 止血 |
| 插件装了但 web 无变化 | loader 条目没写 `- insert:` 容器键（静默跳过），或包不在 bundles 数组 | 两处都补上后重启 |
| GUI 经域名访问时设置页出「memory 横幅」、写不进 | 非 loopback 访问未装 `dsh-plugin-loopback-trust` | 装 + 进 bundles + `--trusted-host` |
| Fenix 面板 502 | 上游 dashboard 未启动 | `python3 bin/fenix_dashboard.py --serve` |
| （Windows）daemon 间歇 FATAL `[WinError 3] …\node_modules\…` | 长路径未开启 | `LongPathsEnabled=1` 后重启进程 |
| （Windows）服务 `SERVICE_PAUSED` | NSSM 对秒退应用节流；多为 AppParameters/参数表错误 | 读 NSSM 日志定位；判态用 `Get-Service` 勿正则 NSSM 输出（UTF-16LE 乱码） |
| （Windows）skills 装成 copy 形态 | symlink 权限不足降级 | 开发者模式/管理员重跑安装器刷新 |
| （Windows）git/curl/IWR 统一报 `SEC_E_NO_CREDENTIALS (0x8009030E)` 或 curl (35) | schannel 客户端凭据损坏 | `git config --global http.sslBackend openssl`；下载类操作改非 schannel 客户端（node fetch/浏览器） |
| `npm install -g` 长时间无输出 | registry.npmjs.org 不可达 | 切 npmmirror（§1）后重试 |
| pip 装包 403（index 可达、wheel 被拒） | 第三方 pip 镜像劣化 | 逐命令 `-i https://mirrors.aliyun.com/pypi/simple/` 或 `-i https://pypi.org/simple` 覆盖（自动化可 setx FENIX_PIP_INDEX_URL） |
| install.ps1 中途 exit 1，stderr 是 pip 的 WARNING | 无控制台环境 stderr→ErrorRecord + EAP=Stop | 先手工 pip 装 deps（§4b 自动化注记）再跑安装器 |
| `fenix-init` 报 `can't open file 'C:\????\...'` | 安装路径含非 ASCII | 迁移纯 ASCII 路径（§4b 硬性要求）重跑安装器 |
| 插件构建报 `Command "build" not found` | 该插件免构建（exports 直指源码） | 预期行为，跳过；按 §6b E-build 的 exports 语义核验 |
| `dsh plugin add` 被拦提示 allow-version | 插件 engines 与已装 dsh 版本过版本风险门 | 按提示 `allow-version <pkg>@<ver> --dsh-version <dsh版> --accept-risk` 后重装 |
| dashboard 构建大量 `Access is denied`（esbuild-* 临时文件） | 无控制台环境 esbuild 服务进程句柄不释放 | `config/config.ts` 设 `jsMinifier: 'swc'` 并 `npm i @swc/core` |
| daemon 服务 Running 但 8787 不监听、面板 502 | dashboard 是独立进程（§8 注记） | 另行常驻 `python bin\fenix_dashboard.py --serve` |
| 服务化 dashboard `/api/projects` 返回空 | LocalSystem 读 systemprofile 配置 | §8「Windows 服务化部署」对齐 |
| 服务化 GUI "/" 菜单无 /fenix-* | 服务账户无 `~/.claude/skills` | §8「Windows 服务化部署」junction 对齐 |
| `dsh --profile <P> --from-default-profile web` 报 cannot be a custom profile target | web 是出厂 profile，不能作拷贝目标 | 不需要拷贝——直接在你现有 profile 上注册（§6a） |
| install.ps1 一串 `Unexpected token` ParserError | UTF-8 无 BOM 在中文区域 PS5.1 下被按 ANSI 读 | 见 §4b 编码告诫（repo 脚本带 BOM；自建副本需补 BOM 或用 pwsh） |
| `dsh plugin` 报 `profile "desktop" is managed exclusively by the Electron application` | CLI 硬拒绝 desktop profile | 见 §6c desktop 专用装配路径 |
| `pnpm run build`（dsh-bundle）无控制台环境挂死无输出 | pnpm 层挂起 | 直接 `node node_modules\typescript\bin\tsc -p tsconfig.json`（§7） |
| dashboard 裸进程退出（轮询场景几分钟内即死），stderr 有 `ConnectionResetError [WinError 10054]` | 简单 HTTP server 把客户端连接重置当致命异常（非偶发，很快发生） | **一律 NSSM 服务化运行**（§8）；裸进程仅限临时调试 |
| 服务 install 成功但立即停止（EventLog 7031）、AppStdout 日志文件从未创建 | 日志父目录缺失（NSSM 不递归建目录） | 先 `New-Item -ItemType Directory -Force <日志目录>` 再 Start-Service |
| `install_unit` 返回 ok:true 但同进程 stderr 有 sc query 探测告警/编码 traceback | 探测瞬态噪音 | 以返回 JSON `ok` 字段 + `Get-Service` 为准，噪音可忽略（重跑幂等） |
| `fenix-dsh-session-grouper` 被版本门跳过（loader enabled:false），9/10 活跃 | 其 peerDependencies 把 @deepseek-ai/session 系精确钉在旧版（桌面版无法 allow-version——该命令仅 CLI 自管 profile 可用） | **预期结果**，非故障；处置=等上游放宽 pin，或自行改 linked 包 peer 声明（精确 pin 通常意味着内部 API 耦合，强启有稳定性风险） |
| `npm install` 报 `network aborted` | npmjs 直连不稳 | 命令行加 `--registry=https://registry.npmmirror.com`（逐命令，免改全局） |
| git clone 报 `curl 56 schannel: server closed abruptly` / `early EOF` / `invalid index-pack output` | schannel + 代理链路不稳 | `git -c http.sslBackend=openssl clone --depth 1 <url>`（逐命令，免改全局） |

## 11. 卸载

- dsh 插件：从 `cordis.patch.yml` 删 loader 条目 → `dsh plugin --profile <P> remove <name>` → 重启你现有的 dsh 实例；
- dsh-bundle：`dsh plugin --profile fenix remove fenix-dsh-bundle`；
- dsh 整体：`npm uninstall -g @deepseek-ai/dsh` + 删 `~/.dsh/`；
- Claude Code：`npm uninstall -g @anthropic-ai/claude-code` + 删 `~/.claude/`（注意 fenixd skills 也在其中，若仅弃用 claude 通道而保留安装门，则只改 `agent.harness` 不卸 CLI）；
- fenixd skills：删 `~/.claude/skills/fenix-*` 对应链接；copy 形态直接删目录；
- daemon：Linux `systemctl --user disable --now fenixd-<name>`；Windows `Get-Service *fenixd*` 列实际名（含 8 位 hash 后缀）后 `nssm stop <实际名> && nssm remove <实际名> confirm`。
