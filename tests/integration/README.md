# tests/integration — Docker 集成测试环境

## 用途与架构

fenixd 对外可信交付（GitHub 分发形态）的回归底线：在轻量 Docker 镜像内从零
复现真实使用全链——「新机器装好 harness → 克隆框架 → 初始化项目 → daemon
自动跑完一个 SPEC（实现 → Playwright 验证 → 裁决 → done）」，并验证 skill、
dashboard、dsh web 三个插件面可正常安装与使用。

架构（自包含，不侵入框架核心代码）：

| 文件 | 职责 |
| --- | --- |
| `Dockerfile` | 纯环境镜像：python3.11 / Node 22 LTS / git / tmux / build-essential / pnpm / Playwright+Chromium / `@anthropic-ai/claude-code` / `@deepseek-ai/dsh@0.2.0-rc.2`（钉版）。**框架代码不烘入**、LLM 凭据零残留 |
| `run.sh` | 宿主侧唯一入口：镜像按 Dockerfile 内容哈希 tag（`fenix-it-env:<hash>`）构建/复用 → `docker run` 注入环境变量与挂载（`tests/integration`→`/opt/it:ro`、插件仓、产物卷→`/artifacts`）→ 转发容器退出码 |
| `e2e.sh` | 容器内主编排：克隆 → install.sh → 夹具项目 → config.yaml 生成 → 前端 dist 构建（缺失时）→ daemon 启动健康检查 → `fenix_spec.py new` + 种子覆写 + `add_spec` 程序化注册 fast-track SPEC → 轮询 STATE.md → 断言 → `summary.json`；双 harness 各一轮（`agent.harness` 切换，独立夹具项目与超时） |
| `checks/check_skills.sh` | skill 面：fenix-* 软链、fenix-init PATH、claude CLI、夹具项目内 `fenix_spec.py status` |
| `checks/check_dashboard.sh` | dashboard 面：幂等启动 `--serve`、HTTP 200、注册夹具项目后 `/api/projects` 可见 |
| `checks/check_dsh_web.py` | dsh web 面（**完整 GUI**）：bridge 插件 pnpm build → link: 挂入自定义 profile → `dsh web` :3080 → Playwright 断言「项目」菜单行、iframe `embed=1`、dashboard 根节点渲染、截图 |
| `fixture/` | 夹具静态小站模板（index.html + app.js）与 SPEC 种子（spec-proposal.md / spec-tasks.md：添加带稳定 testid 的徽标元素、点击切换文案，单文件改动） |

## 快速开始

```bash
# 1) 构建预热（分层缓存；镜像构建期耗时长，预热一次后复用）
tests/integration/run.sh --build-only

# 2) smoke 免凭据全链（镜像自检 + 克隆安装 + 夹具 + daemon + 三插件面含 GUI）
tests/integration/run.sh --smoke

# 3) 真实双 harness e2e（人工注入凭据后触发；详见「人工步骤」）
export FENIX_IT_LLM_BASE_URL=https://<gateway>/v1
export FENIX_IT_LLM_API_KEY=sk-xxx
export FENIX_IT_LLM_MODEL=<model-id>
tests/integration/run.sh
```

## 环境变量契约（设计 D3）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `FENIX_IT_LLM_BASE_URL` / `FENIX_IT_LLM_API_KEY` / `FENIX_IT_LLM_MODEL` | 无（真实模式必填） | LLM 三要素；claude 轮映射 `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_MODEL`，dsh 轮映射 bundle 模型显式配置三要素。仅注入容器 env，零落盘 |
| `FENIX_IT_GIT_REPO` | `https://github.com/fenixsoft/fenixd.git` | 框架克隆源；值为宿主已存在目录路径时只读挂载该仓的 git 共享对象库（`--git-common-dir`，worktree 与普通仓统一）进容器并从本地路径克隆（离线开发替代；`FENIX_IT_GIT_REF` 仍按引用选取） |
| `FENIX_IT_GIT_REF` | `main` | 克隆引用（分支/tag） |
| `FENIX_IT_PLUGINS_REPO` | 宿主 `/root/dsh-plugins`（存在时）；否则必填 | dsh 面板桥插件源：宿主目录路径（挂载进容器）或 git URL（容器内克隆） |
| `FENIX_IT_TIMEOUT` | 真实 3600 / smoke 900 | 单轮超时预算（秒） |
| `FENIX_IT_ARTIFACTS_DIR` | `<repo>/.history/integration-runs/<UTC时间戳>/` | 产物输出目录（gitignored；覆盖时路径纪律自担） |
| `FENIX_IT_APT_MIRROR` | 空（官方源） | 构建期 apt 源站 origin 替换（官方 `deb.debian.org` 在部分网络停滞时传 `http://mirrors.aliyun.com` 加速；传 origin 而非带 `/debian` 路径，sed 按域名整体替换） |
| `FENIX_IT_NPM_REGISTRY` | 空（官方源） | 构建期 npm registry 镜像（官方源停滞/过慢时传 `https://registry.npmmirror.com`；写入镜像 root 级 .npmrc，运行期容器内 npm/pnpm 同享） |
| `FENIX_IT_PIP_INDEX` | 空（官方源） | 构建期 PyPI index 镜像（官方 CDN 停滞时传 `https://mirrors.aliyun.com/pypi/simple`；镜像已预装 playwright/pyyaml/httpx/jsonschema，运行期 install.sh 依赖检查 import 即过、不再外联 PyPI） |

## 产物目录与退出码

产物（每轮均落盘，无论成败）：

- `summary.json` — 运行摘要：模式、双轮终态/耗时/判定、三插件面结果、失败明细
- `orchestrate.log` / `install.log` / `frontend-build.log` / `daemon-<harness>.log` / `dashboard.log` / `dsh-web.log` — 编排与各服务日志
- `.fenix/verify-progress/<spec>/report.json` 副本见夹具项目（断言目标本体）
- `dsh-web-embed.png` — dsh web GUI 截图

退出码契约：

| 码 | 语义 |
| --- | --- |
| 0 | 全绿 |
| 1 | 判定失败（fail-loud；`summary.json` 内含失败明细与失败面） |
| 2 | 用法/装置错误（缺凭据、Docker 不可用、镜像构建失败等；真实模式凭据自检在任何容器/克隆/网络动作之前） |

## 人工步骤

- **真实 e2e 轮需外部注入 LLM 凭据**（baseurl/key/model 环境变量），属人工/CI
  触发步骤——凭据不落任何入库文件，仅经容器 env 注入。smoke 模式免凭据、可
  随时重复，也是本 SPEC 自身验证场景的执行目标（cli 形态，退出码即判定）。
- **`FENIX_IT_PLUGINS_REPO` 长期默认地址**待 dsh-plugins 仓定址公开后钉入本
  README；当前默认取宿主 `/root/dsh-plugins` 目录挂载。
- 单轮真实 e2e 耗时受模型速度影响可达数十分钟；`FENIX_IT_TIMEOUT` 按需放宽。

## 故障排查

- **GitHub 克隆失败（私有仓/网络不通）**：`FENIX_IT_GIT_REPO` 覆盖为可达
  HTTPS 地址（私有仓配 PAT：`https://<token>@github.com/owner/fenixd.git`）；
  或走 SSH 改造（容器内注入 key 后把 URL 换成 `git@github.com:...`）；离线
  环境可直接给宿主目录路径（见环境变量表）。
- **插件仓不可达/构建失败**：dsh web 面 fail-loud（完整 GUI 验证为必需面，
  不静默降级）；检查 `FENIX_IT_PLUGINS_REPO` 与 `fenix-dsh-dashboard-bridge`
  目录在插件源内存在、`pnpm build` 产物 `lib/index.js` 落盘。
- **dashboard 页面 404/空白**：源码克隆形态下 dist 不入 git——编排会自动
  `npm install --no-audit --no-fund && npm run build`；手工复现时在
  `core/dashboard/static/` 下先执行同款构建。
- **dsh web 启动失败（报错口径）**：shipped 模板名（`web`/`headless` 等）
  被 CLI 禁止作为自定义 profile 目标——`dsh --profile <名> --from-default-profile
  web` 必须携带自定义 `--profile` 名，否则报
  `profile "web" is shipped and cannot be a custom profile target`。profile
  名须与 `agent.dsh_profile` 一致（headless 轮缺省 `fenix`）。
- **dsh 轮 `MISSING_CREDENTIAL`**：bundle 模型显式配置三要素
  （provider/baseURL/apiKeyEnv/model）由注入环境变量渲染，缺任一该轮
  fail-loud；另 Anthropic 兼容形态 baseurl（`*/anthropic`）须线协议
  `anthropic-messages`（编排按同款判据自动配 `agent.dsh_api`）。
- **镜像构建期网络失败**：Playwright 浏览器下载默认走 npmmirror 镜像路径
  （`PLAYWRIGHT_DOWNLOAD_HOST`）；apt/npm/pypi 源按需在构建期以环境变量
  覆盖（见环境变量表三镜像行；构建日志可见各层是否命中缓存）。
