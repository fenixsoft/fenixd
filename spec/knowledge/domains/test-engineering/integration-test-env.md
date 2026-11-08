# Docker 集成测试环境

<!-- knowledge: capability=integration-test-env rev=3
     sources=spec/knowledge/_inbox/done/2026-11-07-it-env-runsh-dotenv-load-gap.md,spec/changes/add-integration-test-env -->

本机一键跑通框架对外交付形态（新机装 harness → 克隆框架 → 初始化项目 → daemon 自动闭环）端到端真实验证的 Docker 化装置：`tests/integration/` 自包含测试子系统，双 harness 各跑一轮真实闭环，三插件面（skill / dashboard / dsh web）安装与使用验证，产物落盘 fail-loud。

## 规则

**入口与编排链**：`tests/integration/run.sh` 是唯一本地触发入口（无 CI workflow）：构建或复用镜像后 `docker run` 启动容器，容器内顺序完成 HTTPS 克隆框架 → `install.sh` 安装 → 创建夹具项目 → 按注入配置生成 `.fenix/config.yaml` → 启动 daemon → 程序化注册 fast-track 简单 SPEC → 轮询 `STATE.md` 至终态 → 执行断言。

**镜像契约**：基底 `debian:bookworm-slim`（glibc 生态——dsh web 的 node-pty 原生模块、Playwright Chromium 与 claude CLI 在 musl 上有兼容坑），预装 Python 3.11、Node 20、git、tmux、Playwright+Chromium 与构建工具链，双 harness CLI（`@anthropic-ai/claude-code`、`@deepseek-ai/dsh` 钉版 `0.2.0-rc.2`）。镜像=纯环境：fenix 框架代码一律运行期克隆、不烘入镜像层；编排脚本与夹具模板经只读卷挂载（`/opt/it:ro`），产物经读写卷落容器内固定路径 `/artifacts`——脚本迭代不需重建镜像。镜像 tag 取 Dockerfile 内容哈希（`fenix-it-env:<hash>`），本地已有同 hash 镜像即复用跳过构建，`--build-only` 支持单独预热。

**环境变量契约**：外部注入统一走 `FENIX_IT_` 前缀——LLM 三要素 `FENIX_IT_LLM_BASE_URL` / `FENIX_IT_LLM_API_KEY` / `FENIX_IT_LLM_MODEL`（claude 轮映射 `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_MODEL`，dsh 轮映射 bundle 模型显式配置三要素）、克隆源 `FENIX_IT_GIT_REPO` / `FENIX_IT_GIT_REF`（默认 GitHub 公开仓与分支 `main`）、插件仓 `FENIX_IT_PLUGINS_REPO`（宿主路径挂载或 git URL 克隆双形态，宿主既有本地仓存在时默认挂载）、超时 `FENIX_IT_TIMEOUT`（真实模式每轮 3600s，smoke 900s）、产物目录 `FENIX_IT_ARTIFACTS_DIR`（默认 `.history/integration-runs/<UTC时间戳>/`，gitignored）、构建期源站加速 `FENIX_IT_APT_MIRROR` / `FENIX_IT_NPM_REGISTRY` / `FENIX_IT_PIP_INDEX`（可选，分别覆盖镜像构建期 apt/npm/pip 源站，官方源停滞时换可达镜像）。

**凭据注入与 .env 自动加载**：真实模式凭据自检判定缺项前，自动加载宿主机预置文件 `tests/integration/.env`（gitignored，`KEY=VALUE` 行，bash source 语义）作为环境变量缺省值；进程环境变量优先于文件值（加载前记录已有 `FENIX_IT_*` 原值，source 后恢复）。文件不存在时回退纯环境变量；缺项即 fail-loud——先于任何容器启动、克隆与真实模型调用，输出缺失清单与修复指引并以非零码退出（用法/装置错误档）。key 明文只落该文件，禁止写入任何入库文件、镜像层或日志输出。

**缺凭据 fail-loud 场景的验证前提**：该场景只能在未预置 `.env` 的环境验证——本机已预置 `.env` 时须先移走该文件再触发，否则文件值回填使凭据齐备、fail-loud 分支不可达。场景不设环境文件豁免开关，收窄验证前提即其豁免形态。

**镜像纯度静态断言排除 .env**：镜像纯度的静态层断言（入库文件无真实 key 形态字面值：`sk-` + ≥8 位字母数字）grep 时必须 `--exclude=.env`——`.env` 是设计内 gitignored 本机凭据注入文件，配置好凭据的机器上必然命中，不排除即确定性误报。运行期层断言：镜像文件系统无框架残留、env 无 LLM 变量声明、`docker history` 无 key 形态残留。

**框架克隆源形态**：`FENIX_IT_GIT_REPO` 支持仓库 URL（默认 GitHub）与本地目录两种形态。目录形态取 `git rev-parse --git-common-dir` 的共享对象库只读挂载进容器、容器内本地克隆，消除克隆网络抖动，属自建夹具通道；普通仓与 worktree 形态统一——worktree 的 `.git` 是指向宿主 gitdir 的指针文件，直接挂工作树会使容器内克隆报 not a git repository，挂 common dir 则两种形态一致。「每次运行从 GitHub 拉取」是回归底线：smoke 主链场景不可钉本地源，仅编排类验证场景（如双轮汇总）允许钉 `$PWD` 本地仓形态消除 GitHub 外联。

**GitHub 大克隆失败指纹判 env**：克隆失败出现 `GnuTLS recv error (-110)`、`RPC failed, curl 92 HTTP/2 stream CANCEL`、`early EOF`、`fetch-pack: invalid index-pack output` 任一指纹，属传输中断型网络故障；同源克隆数分钟后成功即可判 env 类失败，非产品缺陷。

**双 harness 轮次**：真实模式下 claude 与 dsh 两通道各完整执行一轮夹具 SPEC 闭环（单容器内 `/work/round-claude/` 与 `/work/round-dsh/`），两轮独立夹具项目、独立配置（仅 `agent.harness` 不同）与独立超时预算；任一轮失败记录后继续另一轮，摘要汇总双轮终态/耗时/判定，任一失败整体非零退出。dsh 轮经 fenix-dsh-bundle 走 headless 车道：容器内部署 bundle——创建自定义 profile 后 `dsh plugin add "link:<repo>"` 软链挂入（shipped 模板名被 CLI 禁止作为自定义 profile 目标，profile 名须与 `agent.dsh_profile` 一致）；模型显式配置三要素缺一即该轮 fail-loud。

**夹具项目与 SPEC 注册**：夹具项目为 git 初始化的静态小站（`fixture/index.html` + `fixture/app.js`），SPEC 刻意极简（添加带稳定 testid 的徽标元素、点击切换文案）以被 web 验证场景 DOM 断言。注册复用 fenix-new 机械层：`fenix_spec.py new` 生成脚手架后以挂载种子覆写 proposal/tasks，经 `core.state_machine.add_spec` 注册为 fast-track。生成 `.fenix/config.yaml` 含 `project.type: web`（Playwright DOM 场景形态需显式声明）与 `gates.approve_mode: manual`（断言终态 `done`，不推送）。容器内 daemon 以 `nohup python3 fenixd.py` 直跑、不做 supervisor 托管——集成环境生命周期等于容器生命周期。

**三插件面验证**：真实与 smoke 模式均执行——
1. **skill**：install.sh 装配的 fenix-* skills 在 `~/.claude/skills/` 可见、`fenix-init` 在 PATH、SPEC 生成器在夹具项目内可运行；
2. **dashboard**：`fenix_dashboard.py --serve` 起服 :8787、HTTP 可达、夹具项目可查询；源码克隆形态下 dist 构建产物缺席时编排先执行前端构建（对齐 install.sh 的源码使用者口径）；
3. **dsh web 完整 GUI**：`DSH_HOME` 隔离目录 + `--from-default-profile web` 自定义 profile 初始化，bridge 插件 `pnpm build` 后软链挂入（`file:` 拷贝断 peer 链），`dsh web` 起服 :3080，Playwright 打开页面断言面板桥「项目」菜单行 iframe 存在且 src 含 `embed=1`，`frame_locator` 进入 iframe 断言 dashboard 前端根节点渲染，截图落产物目录。

任一面失败 fail-loud 报告失败面与原始错误（含失败阶段），不静默跳过。

**smoke 免凭据模式**：`run.sh --smoke` 不执行任何真实 LLM 调用与 SPEC 闭环轮次，仅做镜像环境自检（双 harness CLI / Playwright / 基础工具）、克隆安装、夹具创建 + daemon 启动健康检查与三插件面全量验证；无凭据环境可重复执行，并作为本子系统自身验证场景的确定性执行目标（cli 形态、退出码即判定）。

**产物与退出码契约**：每轮产物落 `FENIX_IT_ARTIFACTS_DIR`——`summary.json`（mode、exit_code、rounds、plugin_faces、failures、artifacts_dir、finished_at 与 git_repo 溯源值）、编排/安装/前端构建/daemon 日志、验证报告副本、dsh web GUI 截图。退出码：0=全绿；1=判定失败（摘要含失败明细）；2=用法/装置错误（凭据缺项、Docker 不可用、镜像构建期错误等）。

## 代码锚点

- 宿主入口（.env 自动加载、凭据自检 fail-loud、镜像构建复用、GIT_REPO 目录形态挂载）：`tests/integration/run.sh`
- 容器内编排与断言（双轮分派、bundle 部署、config 生成、summary.json）：`tests/integration/e2e.sh`
- 镜像定义（纯环境基底）：`tests/integration/Dockerfile`
- 插件面检查脚本：`tests/integration/checks/check_skills.sh`、`tests/integration/checks/check_dashboard.sh`、`tests/integration/checks/check_dsh_web.py`
- 夹具模板（bundle 前端壳 + SPEC 文档样例）：`tests/integration/fixture/index.html`、`tests/integration/fixture/app.js`、`tests/integration/fixture/spec-proposal.md`、`tests/integration/fixture/spec-tasks.md`
- 使用文档：`tests/integration/README.md`

## 溯源

- 2026-11-08 2026-11-07-it-env-runsh-dotenv-load-gap（spec/knowledge/_inbox/done/2026-11-07-it-env-runsh-dotenv-load-gap.md） — 折叠集成测试环境裁决遗留事实：.env 自动加载语义、缺凭据场景与 .env 预置的互斥验证前提、镜像纯度 grep 排除 .env、GIT_REPO 目录形态夹具通道与 smoke 主链回归底线、GitHub 大克隆失败指纹判 env；条目中「.env 未实现自动加载」一条已随打回修复落地失效，按当前实现态收编。
- 2026-11-08 add-integration-test-env（spec/changes/add-integration-test-env/） — 整体重写本页：收编 SPEC 全量契约（镜像、环境变量、编排链、双 harness 轮次、三插件面、smoke 模式、产物退出码）为规则主体，凭据注入与克隆源形态裁决规则并入当前态。
