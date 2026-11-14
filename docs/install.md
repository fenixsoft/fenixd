# fenixd 全新环境部署手册（Linux / Windows × Claude Code / dsh web）

> 目标读者：负责部署的 agent / 运维。目标：在**完全干净**的 Linux 或 Windows 机器上，
> 从零装好 fenixd 框架（含全部依赖），并按需装配 agent 执行 harness——
> **Claude Code**（CLI 通道，缺省）与 **dsh web**（DeepSeek Harness web GUI + 插件全家桶）二选一或双装。
>
> 本手册每阶段末尾带**验证门**；上一阶段验证不过不要进入下一阶段。
> 维护约定：版本钉扎随「版本兼容表」走，升级任一组件前先读它。

## 0. 组件总览与支持矩阵

**支持矩阵**（两 OS × 两 harness 全组合支持）：

| | Claude Code harness（§5） | dsh web harness（§6–§7） |
| --- | --- | --- |
| **Linux** | ✅ §1 → §3 → §4a → §5 → §8 | ✅ 全流程 §1 → §2 → §3 → §4a → §5–§7 → §8 |
| **Windows** | ✅ §1 → §3 → §4b → §5 → §8 | ✅ 全流程 §1 → §2 → §3 → §4b → §5–§7 → §8 |

读法：Claude Code 通道只需 §1 前置 + §3 源码 + §4 框架 + §5 harness 配置 + §8 项目初始化；
dsh web 通道额外需要 §2 dsh 运行时、§6 web profile 与插件全家桶、§7 headless bundle。
两通道可共存于同一机器（fenixd 项目内 `agent.harness` 一键切换，见 §5.3）。

**组件清单**：

| 组件 | 作用 | 来源 | 适用面 |
| --- | --- | --- | --- |
| fenixd 框架 | Fenix 研发闭环本体（CLI/daemon/dashboard/skills） | `github.com:fenixsoft/fenixd.git` | **两 harness 必装** |
| Claude Code CLI | agent 执行通道 A（每子代理一个 claude 子进程）；同时是 §4 安装器硬门 | npm `@anthropic-ai/claude-code` | **两 harness 必装**（dsh 通道装它只为过安装门，运行时不依赖） |
| dsh（DeepSeek Harness） | agent 执行通道 B 运行时 + web GUI（`dsh web`） | npm `@deepseek-ai/dsh` | 仅 dsh 通道 |
| dsh-bundle | fenixd → dsh 的 headless 派发通道（无人值守执行） | fenixd 仓库内 `dsh-bundle/` | 仅 dsh 通道（`agent.harness: dsh` 时） |
| dsh-plugins | dsh web 的 fenix 插件全家桶（skill 桥接/dashboard 面板/品牌/搜索等） | `github.com:fenixsoft/dsh-plugins.git` | 仅 dsh 通道 |
| NSSM（仅 Windows） | fenixd daemon 服务承载 | nssm.cc 2.24 | 两 harness（daemon 承载与 harness 无关） |
| systemd user unit（仅 Linux） | fenixd daemon 服务承载 | fenixd 内建（`core/systemd_hosting.py`） | 两 harness |

**版本兼容表（钉扎，勿自由升版）**

| 组件 | 钉定版本 | 说明 |
| --- | --- | --- |
| dsh CLI | `0.2.2-rc.1` | dsh-bundle peerDependencies 三键精确钉同版；fenixd 侧 `core/agent_runner/harness/dsh_adapter.py` 的 `DSH_VERSION_WHITELIST` 白名单同表。升版必须三处同步重测。Claude Code 通道无此约束 |
| `@deepseek-ai/cordis` | `~4.0.4` | bundle/插件 peer，npm install 自动解析 |
| Claude Code CLI | 跟随官方最新稳定版 | 无钉扎；fenixd 以原生 CLI 子进程方式调用（claude_adapter），只要求 `claude --version` 可执行 |
| Node.js | ≥ 24 | dsh（`node:sqlite`）、插件构建、dashboard 构建统一基线 |
| pnpm | ≥ 10 | 插件构建与 profile workspace |
| Python | ≥ 3.10 | fenixd 框架 |
| billion-context / dshmarket | 任意近期稳定版（现役 `0.1.213` / `1.73.14`） | web profile 推荐生态件 |

## 1. 通用前置（两平台、两 harness 都做）

1. **Node.js ≥ 24** 与 **pnpm ≥ 10**：
   ```bash
   # Linux（nvm）或 Windows（官网安装包）装 Node 24 LTS 后：
   corepack enable && corepack prepare pnpm@latest --activate
   node --version && pnpm --version        # 期望 v24.x / 10.x
   ```
2. **git**。
3. **Python 3.10+**（Windows 用 python.org 安装包，勾选「Add to PATH」与 py launcher）。
4. **Claude Code CLI**：`npm install -g @anthropic-ai/claude-code && claude --version`。
   双重身份：①它本身就是 **Claude Code harness 的运行时**（§5）；
   ②fenixd 两个安装器（§4）都把 `claude --version` 作**硬门**（缺失直接 exit 1、不装 skills/PATH）
   ——即使本机最终只用 dsh 通道也必须装。
5. **LLM API Key**：一个 OpenAI 兼容（或 Anthropic 兼容）端点 + key。
   两 harness 的接入方式不同：Claude Code 走 `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`
   环境变量（§5.2），dsh 走 profile 的 provider 配置（§6e/§7）。
   后文以 `BIGMODEL_CN_API_KEY` 为例（可换）。

## 2. 阶段 A：安装 dsh 运行时（仅 dsh web harness；纯 Claude Code 部署可跳过）

```bash
npm install -g @deepseek-ai/dsh@0.2.2-rc.1
dsh --version              # 期望 0.2.2-rc.1
```

> 为什么钉版：dsh-bundle 以 peerDependencies 精确钉 dsh 版本，版本不符时 dsh 经
> `evaluatePluginCompatibility` **跳过 bundle**（stderr 报版本错误、不静默降级），
> fenixd headless 车道随即以 `MISSING_CREDENTIAL` 退出。升 dsh 必须同步升 bundle。

## 3. 阶段 B：获取 fenixd 源码

```bash
git clone git@github.com:fenixsoft/fenixd.git          # 或 release tar 包（内置 dashboard 预构建 dist）
# 下文以 <repo> 指代 fenixd 仓库根目录
```

> 区别：git clone **不含** `core/dashboard/static/dist`（不入 git）；release 包内置。
> 源码形态必须执行 §4 的 dashboard 构建步。

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
- `fenix-init` 命令：软链到 `~/.local/bin`（不在 PATH 时按提示写 shellrc）。

**dashboard 构建**（源码形态必做）：

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
ls <repo>/core/dashboard/static/dist/index.html
```

### 4b. Windows

**系统级一次性准备（管理员 PowerShell）：**

```powershell
# 长路径支持（fenixd 骨架 junction/symlink 链上常见 >260 字符路径；未开启会间歇性 FATAL）
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -Value 1
# 开发者模式（允许非管理员创建 symlink；不开则安装器降级 junction/copy）
# 首选：设置 → 更新和安全 → 开发者模式 → 打开；自动化可用：
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock" /v AllowAllTrustedApps /t REG_DWORD /d 1 /f
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock" /v AllowDevelopmentSignedApps /t REG_DWORD /d 1 /f
```

**NSSM 2.24（daemon 服务承载，Windows 专用）：**

```powershell
# 从 https://nssm.cc/release/nssm-2.24.zip 下载解压后：
New-Item -ItemType Directory -Force C:\tools\nssm | Out-Null
Copy-Item <解压目录>\win64\nssm.exe C:\tools\nssm\
setx PATH "$env:PATH;C:\tools\nssm" /M        # pal 只探 PATH 找 nssm
nssm version                                   # 期望 2.24
```

**框架安装（普通 PowerShell，在仓库根）：**

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

安装器（幂等）自动完成：

- 依赖检查：python 3.10+（py launcher 优先）/ git / claude CLI（硬门）；
- pip 依赖（`requirements-win32.txt` 同源）：`psutil>=5.9`、`pywin32>=306` 必选，
  `PyYAML>=6.0`、`httpx>=0.24` 基线，`jsonschema>=4.17` 可选——
  探测用 `importlib.util.find_spec`（pip 包名 ≠ import 模块名：pywin32→win32api、PyYAML→yaml）；
- skills 链接：symlink → junction → copy 三级降级（copy 形态升级需重跑安装器刷新）；
- `fenix-init.cmd` shim 写入 `%LOCALAPPDATA%\Fenixd\bin` 并加入用户 PATH。

**dashboard 构建**（同 4a：`cd <repo>\core\dashboard\static` 后 `npm install` + `npm run build`）。

**验证门 C-Windows**：

```powershell
py -3 -c "import psutil, win32api, yaml, httpx; print('deps ok')"
fenix-init 2>&1 | Select-Object -First 3
(Get-ChildItem $env:USERPROFILE\.claude\skills -Filter "fenix-*").Count   # = 8
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
   export ANTHROPIC_AUTH_TOKEN="<key>"    # 也可直接放 BIGMODEL_CN_API_KEY 的值
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

> web profile 是 dsh web GUI 的装配单元，位于 `$DSH_HOME/profiles/web/`
>（`DSH_HOME` 缺省 `~/.dsh`，Windows 为 `%USERPROFILE%\.dsh`）。
> 装配 = **pnpm workspace 依赖（link: 形态）** + **package.json bundles 数组** + **cordis.patch.yml loader 条目** 三件套。

### 6a. 创建 profile

```bash
dsh --profile web --from-default-profile web      # 首次：从出厂模板拷贝创建
dsh web --help                                    # 能打印 web 应用帮助即 profile 可引导
```

### 6b. 获取并构建 dsh-plugins

```bash
git clone git@github.com:fenixsoft/dsh-plugins.git     # 下文以 <plugins> 指代其根目录
```

每个插件目录独立构建（`lib/index.js` + `lib/client.js` 双产物，Node ≥ 24 / pnpm ≥ 10）：

```bash
for p in cc-import fenix-dsh-auth fenix-dsh-brand-fenix fenix-dsh-chat-polish \
         fenix-dsh-clipboard-fallback fenix-dsh-dashboard-bridge \
         fenix-dsh-session-advanced-search fenix-dsh-session-grouper \
         fenix-dsh-settings-dock fenix-skill-provider; do
  (cd <plugins>/$p && pnpm install && pnpm build) || echo "BUILD FAIL: $p"
done
```

**验证门 E-build**：每个插件目录存在 `lib/index.js`（dashboard-bridge / cc-import 另有 `lib/client.js`）。

### 6c. 注册进 profile workspace

```bash
cd ~/.dsh/profiles/web
for p in cc-import fenix-dsh-auth fenix-dsh-brand-fenix fenix-dsh-chat-polish \
         fenix-dsh-clipboard-fallback fenix-dsh-dashboard-bridge \
         fenix-dsh-session-advanced-search fenix-dsh-session-grouper \
         fenix-dsh-settings-dock fenix-skill-provider; do
  dsh plugin --profile web add "link:<plugins绝对路径>/$p"
done
```

> Windows 下 link 路径写绝对盘符形态：`dsh plugin --profile web add "link:C:\repo\dsh-plugins\cc-import"`。
> ⚠ 必须用 `link:` 软链形态——`file:` 拷贝装会使副本失去 `node_modules`、peer 断链（真机踩过）。

**推荐生态件**（context 管理 / 插件市场，registry 安装）：

```bash
dsh plugin --profile web add billion-context@0.1.213
dsh plugin --profile web add dshmarket@1.73.14
```

**非 loopback 主机名访问 GUI 时必装**（frp/域名反代场景；仅 127.0.0.1 访问可跳过）：

```bash
dsh plugin --profile web add github:6mt/dsh-plugin-loopback-trust
```

并把上述三件加进 `package.json` 的 `dsh.profile.bundles` 数组（**只装依赖不进 bundles 不会装载**）：

```jsonc
"dsh": { "profile": { "bundles": [
  "@deepseek-ai/dsh-base",
  "@deepseek-ai/dsh-web-app",
  "dsh-plugin-loopback-trust",     // 非 loopback 访问时
  "billion-context",
  "dshmarket"
  // …保留模板既有条目
] } }
```

同时确认 profile 的 `pnpm-workspace.yaml` 含（现役真机形态）：

```yaml
packages:
  - .
nodeLinker: hoisted
autoInstallPeers: false
minimumReleaseAgeExclude:
  - dshmarket@1.73.14
  - billion-context@0.1.213
```

### 6d. loader 条目（cordis.patch.yml）

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
      bigmodel-cn:                       # 路由名自取
        apiKeyEnv: BIGMODEL_CN_API_KEY   # 从该环境变量读 key（启动前须已导出）
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
> 已用 cc-switch 管理端点的：Models 页「从 Claude Code 导入」一键接管，免手写本节。

### 6f. 启动与验证门 E

```bash
# 非 loopback 域名访问：--trusted-host <域名>:<端口>（可重复多组）
dsh --profile web --no-open --port 3080 --trusted-host home.example.com:3080
```

逐项确认：

1. 浏览器 `http://127.0.0.1:3080`（或 trusted-host）打开 GUI，token 见启动日志首行；
2. 输入框按 "/"：菜单出现 `/fenix-new /fenix-status /fenix-setup …`
   —— 这是 `fenix-skill-provider` 在扫 `~/.claude/skills` 下 `fenix-*`（§4 安装的技能），
   来源目录新增 skill 数秒内自动反映，无需重启；
3. fenixd dashboard 启动后（§8），侧栏出现 概览/项目/设置/运维/帮助 条目
   —— `fenix-dsh-dashboard-bridge` 反代 `/fenix-dashboard/` 生效；
4. Models 设置页底部「从 Claude Code 导入」按钮可见（cc-import；需 cc-switch 数据库才有候选，可选项）。

## 7. 阶段 F：dsh headless 派发通道（dsh-bundle；仅 `agent.harness: dsh` 需要）

> fenixd 以无人值守 `dsh headless` 派发实现/验证工作（SPEC 实现、验证 Agent 全走此通道）。
> Claude Code 通道（§5.3）不走这里；装了 bundle 但 `agent.harness` 仍为 `claude` 时也不使用。

```bash
cd <repo>/dsh-bundle && npm install            # npm 自动装精确版 peer（dsh 三键 + cordis）

DSH_HOME=~/.dsh dsh --profile fenix --from-default-profile headless   # 首次创建
DSH_HOME=~/.dsh dsh plugin --profile fenix add "link:<repo绝对路径>/dsh-bundle"
```

确认 `~/.dsh/profiles/fenix/package.json` 形如（`plugin add` 会写 deps，bundles 缺则手工补）：

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
      apiKeyEnv: BIGMODEL_CN_API_KEY
      model: glm-5.3-flash
      api: anthropic-messages        # Anthropic 兼容端点必配（缺省 openai-completions）
```

**验证门 F**：

```bash
dsh --profile fenix --dump-config | grep fenix     # 可见三条 insert 与各覆盖条目
dsh --profile fenix "say ok"                        # headless 一问一答冒烟（读 key 环境变量）
```

## 8. 阶段 G：项目内初始化与常驻 daemon（harness 无关）

```bash
mkdir -p ~/myproj && cd ~/myproj
fenix-init . --name myproj --type web     # 生成 .fenix 骨架（skills 链接/命令基线）
```

常驻 daemon（任务调度/看护）由 fenix 自身安装，与 harness 选择无关，两平台形态不同：

| | Linux | Windows |
| --- | --- | --- |
| 承载 | systemd user unit（`core/systemd_hosting.py` 自动安装 enable --now） | NSSM 服务 `fenixd-<project>`（`pal.install_unit`） |
| 前置 | systemd user session 可用（WSL1 不支持，用 WSL2） | §4b 已装 NSSM 且在 PATH |
| 操作 | 会话内 `/fenix-setup`（或 `pal.install_unit(root)`） | 同左（NSSM 缺失时驱动显式报错） |
| 服务核查 | `systemctl --user status fenixd-<name>` | `nssm status fenixd-<name>`（态 4=RUNNING；判态用 SCM/`Get-Service`，勿正则解析 NSSM 输出——它原生 UTF-16LE） |

dashboard 就绪验证（fenixd 原生 web UI，两 harness 共用；dsh web 里由 bridge 反代嵌入）：

```bash
python3 <repo>/bin/fenix_dashboard.py --serve   # 默认 127.0.0.1:8787
curl -s http://127.0.0.1:8787/api/projects      # 返回 JSON 即通
```

## 9. 端到端验收清单（按 harness 分组）

**通用（两 harness 都验）**：

- [ ] `node --version` ≥ 24；`python3 --version` ≥ 3.10；`claude --version` 可执行
- [ ] 项目内 `/fenix-setup`：daemon 服务 RUNNING（systemctl / nssm status）
- [ ] dashboard 8787 `curl /api/projects` 返回 JSON
- [ ] `/fenix-new "冒烟测试"` 能创建 SPEC（实际走当前 `agent.harness` 指向的通道）
- [ ] （Windows）`nssm version` = 2.24；`LongPathsEnabled` = 1；`py -3 -c "import win32api"` 不报错

**Claude Code harness（§5）追加**：

- [ ] `claude -p "reply with exactly: ok"` 冒烟通过（认证/端点全链）
- [ ] claude REPL "/" 菜单含全部 `/fenix-*` 条目
- [ ] `.fenix/config.yaml` `agent.harness: claude`（或缺省）

**dsh web harness（§6–§7）追加**：

- [ ] `dsh --version` = 0.2.2-rc.1
- [ ] `dsh --profile fenix --dump-config | grep fenix` 非空（bundle 挂载）
- [ ] dsh web GUI 可开；"/" 菜单含全部 `/fenix-*` 条目
- [ ] web 侧栏出现 Fenix 面板（dashboard-bridge）

## 10. 故障排查速查

| 症状 | 根因 | 处置 |
| --- | --- | --- |
| 安装器 `[FAIL] missing: claude` | claude CLI 是安装硬门（两 harness 都要） | `npm i -g @anthropic-ai/claude-code` |
| `claude -p` 报认证失败 | `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` 未导出或未登录 | §5.2 三种方式之一补齐；fenixd spawn 继承的是 shell 环境变量 |
| claude REPL "/" 无 `/fenix-*` | skills 未装（§4 验证门应=8） | 重跑安装器；`ls ~/.claude/skills/` |
| headless 车道 `MISSING_CREDENTIAL` exit 1 | bundle 被 peer 版本校验跳过，或 `apiKeyEnv` 变量未导出 | 核对 dsh 版本钉扎表；导出 key 环境变量 |
| 配了 `agent.harness: dsh` 但派发 fail-fast | bundle 未挂载/版本不在白名单/实例不健康 | 设计如此（不静默回退）；按报错修链路或临时 `harness: claude` 止血 |
| 插件装了但 web 无变化 | loader 条目没写 `- insert:` 容器键（静默跳过），或包不在 bundles 数组 | 两处都补上后重启 |
| GUI 经域名访问时设置页出「memory 横幅」、写不进 | 非 loopback 访问未装 `dsh-plugin-loopback-trust` | 装 + 进 bundles + `--trusted-host` |
| Fenix 面板 502 | 上游 dashboard 未启动 | `python3 bin/fenix_dashboard.py --serve` |
| （Windows）daemon 间歇 FATAL `[WinError 3] …\node_modules\…` | 长路径未开启 | `LongPathsEnabled=1` 后重启进程 |
| （Windows）服务 `SERVICE_PAUSED` | NSSM 对秒退应用节流；多为 AppParameters/参数表错误 | 读 NSSM 日志定位；判态用 `Get-Service` 勿正则 NSSM 输出（UTF-16LE 乱码） |
| （Windows）skills 装成 copy 形态 | symlink 权限不足降级 | 开发者模式/管理员重跑安装器刷新 |

## 11. 卸载

- dsh 插件：从 `cordis.patch.yml` 删 loader 条目 → `dsh plugin --profile web remove <name>` → 重启 dsh web；
- dsh-bundle：`dsh plugin --profile fenix remove fenix-dsh-bundle`；
- dsh 整体：`npm uninstall -g @deepseek-ai/dsh` + 删 `~/.dsh/`；
- Claude Code：`npm uninstall -g @anthropic-ai/claude-code` + 删 `~/.claude/`（注意 fenixd skills 也在其中，若仅弃用 claude 通道而保留安装门，则只改 `agent.harness` 不卸 CLI）；
- fenixd skills：删 `~/.claude/skills/fenix-*` 对应链接；copy 形态直接删目录；
- daemon：Linux `systemctl --user disable --now fenixd-<name>`；Windows `nssm stop <name> && nssm remove <name> confirm`。
