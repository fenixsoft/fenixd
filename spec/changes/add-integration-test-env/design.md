# Design: add-integration-test-env — Docker 集成测试环境与双 harness 端到端验证

## Context

fenixd 的既有质量面是宿主机 pytest 套件（`tests/`）与 dsh 通道验收脚本（`bin/dsh_acceptance.py`，fixture/smoke/accept 三模式，fail-loud 哲学）。框架对外形态是「新机器安装 → 克隆框架 → 初始化项目 → daemon 自动闭环」，这条全链没有隔离环境验证。本 SPEC 在 `tests/integration/`（用户已确认归入既有 tests/ 树）新增自包含集成测试子系统，不触碰核心代码。

已确认的需求边界：目录 `tests/integration/`；双 harness（claude code + dsh）各跑一轮真实 e2e；HTTPS 公开克隆框架；本地脚本触发（无 CI workflow）；dsh web 插件走**完整 GUI 验证**；执行模式 full；立项后立即调度。

相关既有机制（复用不重建）：`install.sh` 安装链（依赖检查 + skills 软链 + fenix-init 入 PATH）、`.fenix/bin/fenix_spec.py` + `core.state_machine.add_spec` 程序化注册链（fenix-new skill 的机械层）、`fenix_dashboard.py --serve`（:8787）、`agent.harness` 全局开关与 fenix-dsh-bundle 五件套（模型显式配置三要素 provider/baseURL/apiKeyEnv/model，版本钉 `@deepseek-ai/dsh@0.2.0-rc.2`）、`bin/dsh_acceptance.py` 的 fail-loud 与信号式自检范式。

## Goals / Non-Goals

**Goals**

- 一条命令（`tests/integration/run.sh`）完成「构建/复用镜像 → 容器内克隆框架 → 安装 → 夹具项目 → 双 harness 各跑一个简单 SPEC 至 done → 三插件面验证 → 产物落盘」。
- 镜像只装环境不装框架；LLM 配置运行期注入、零落盘。
- `--smoke` 免凭据模式可重复执行，并作为本 SPEC 自身验证场景的执行目标。
- fail-loud：任一面失败给出失败面 + 原始错误，退出码 0/1/2 语义清晰。

**Non-Goals**

- 不做 CI workflow（用户已确认后续再接）。
- 不验证 dashboard/dsh web 的界面视觉回归（只验「能安装、能启动、面板桥真实挂载」）。
- 不改动框架核心任何行为；不为集成环境引入新的 Python 依赖（容器内脚本用标准库 + 镜像内预装的 Playwright Python 包）。
- 不覆盖验证引擎自身的深度回归（那是既有 pytest 面的职责）。

## Decisions

**D1 基底镜像：`debian:bookworm-slim`（备选：alpine、ubuntu slim）**。选 debian：glibc 生态——dsh web 依赖 node-pty 原生模块、Playwright Chromium 与 claude code CLI 在 musl 上均有兼容坑；slim 变体体积可控。alpine 仅在体积敏感压倒兼容性时才值得。Node 20 经 NodeSource 装入；构建期含 `build-essential`（node-pty 编译）与 Chromium 系统依赖，装完不清理构建工具以换取可调试性（体积代价 <200MB，可接受）。

**D2 镜像=纯环境，脚本与夹具运行期挂载**。`docker run -v <repo>/tests/integration:/opt/it:ro` 把编排脚本、检查脚本、夹具模板以只读方式挂入——脚本迭代不需要重建镜像；产物目录另以**读写卷**挂载（run.sh 在宿主侧创建时间戳目录后 `-v <FENIX_IT_ARTIFACTS_DIR>:/artifacts`，容器内统一写 `/artifacts`）——`/opt/it` 只读，容器内产物仅能经该卷落回宿主；框架代码另在容器内从 GitHub 克隆（满足「每次从 GitHub 拉取」）。镜像复用策略：tag `fenix-it-env:<dockehash>`（Dockerfile 内容哈希），`run.sh` 检测本地已有同 hash 镜像则跳过构建；`--build-only` 支持单独预热。

**D3 环境变量契约（`FENIX_IT_` 前缀，容器内统一注入）**：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `FENIX_IT_LLM_BASE_URL` / `FENIX_IT_LLM_API_KEY` / `FENIX_IT_LLM_MODEL` | 默认源自 `tests/integration/.env`（gitignored 运行时凭据文件，见下）；文件与环境变量均缺失时真实模式必填 | LLM 三要素；claude 轮映射 `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_MODEL`，dsh 轮映射 bundle 模型显式配置三要素（provider/baseURL/apiKeyEnv——apiKeyEnv 指向容器内注入的键名变量） |
| `FENIX_IT_GIT_REPO` / `FENIX_IT_GIT_REF` | `https://github.com/fenixsoft/fenixd.git` / 仓库默认分支 | 框架克隆源 |
| `FENIX_IT_PLUGINS_REPO` | 宿主 `/root/dsh-plugins`（存在则挂载）；否则必填 | dsh 面板桥插件源：支持宿主路径（挂载进容器）或 git URL（容器内克隆） |
| `FENIX_IT_TIMEOUT` | 3600（真实模式每轮秒数；smoke 900） | 单轮超时预算 |
| `FENIX_IT_ARTIFACTS_DIR` | `.history/integration-runs/<UTC时间戳>/` | 产物输出（宿主侧，遵循 AGENTS.md 临时文件约定）；时间戳目录由 run.sh 在宿主侧创建，并以读写卷挂至容器内固定路径 `/artifacts`（见 D2） |

真实模式启动前，run.sh 以 `set -a; source tests/integration/.env; set +a` 自动加载宿主机预置凭据文件（已入 .gitignore，进程环境变量优先于文件值），随后自检凭据齐备性，缺项即列清单退出（exit 2），不发起任何容器/网络动作——对齐 `bin/dsh_acceptance.py accept` 的人工信号式哲学。本机已预置该文件：provider `bigmodel.cn`（Anthropic 兼容端点，模型 `glm-5.3-flash`），url/key 取自 `.fenix/config.yaml` providers 段同名条目；key 只落该 gitignored 文件，禁止写入任何入库文件、镜像层或日志输出。

**D4 夹具 SPEC 的程序化注册**：容器内经 `.fenix/bin/fenix_spec.py new` 生成脚手架，以挂载的种子文件（`fixture/spec-proposal.md` / `fixture/spec-tasks.md`）覆写 proposal/tasks，`core.state_machine.add_spec` 注册为 fast-track——完全复用 fenix-new skill 的机械层，不走交互式 /fenix-new。夹具项目 = git 初始化的静态小站（`fixture/index.html` + `fixture/app.js`），SPEC 内容为「添加一个带稳定 testid 的徽标元素，点击切换文案」——足够简单（单文件改动）且可被 web 验证场景做 DOM 断言，真实驱动实现 → Playwright 验证 → 裁决全链。

**D5 容器内 daemon 承载**：slim 镜像无 systemd，daemon 以 `nohup python3 fenixd.py` 直跑（日志落 `.fenix/logs/`），不做 supervisor 托管（集成环境生命周期 = 容器生命周期，无需崩溃自愈）。`.fenix/config.yaml` 由编排脚本按注入环境变量生成（provider baseurl/key/model + `agent.harness` + `project.type: web`——夹具为静态小站，Playwright DOM 场景形态需显式声明；`project.type` 缺失时由消费方默认兜底，不保证出 web 验证场景 + `gates.approve_mode` 保持人工档——断言终态为 `done`，不推送）。轮询循环机械读 `STATE.md` 状态行至 `done`/`blocked`，超时按 `FENIX_IT_TIMEOUT`。

**D6 双轮编排**：单容器内顺序两轮——`/work/round-claude/`、`/work/round-dsh/` 各自独立夹具项目 + 独立配置（仅 `agent.harness` 不同）+ 独立超时。任一轮失败记录后继续另一轮；摘要 JSON 汇总双轮终态/耗时/判定，任一失败整体 exit 1。dsh 轮前置条件含 bundle 容器内部署与装配自检：按 `dsh-bundle/README.md` 部署段先创建自定义 profile（`dsh --profile <p> --from-default-profile headless`）再 `dsh plugin --profile <p> add "link:<repo>/dsh-bundle"` 软链挂入——shipped 模板名被 CLI 禁止作为自定义 profile 目标（dsh_adapter 实测 fail-loud），profile 名须与 `agent.dsh_profile` 一致；模型三要素缺失即该轮 fail-loud。

**D7 dsh web 完整 GUI 验证**：容器内 `DSH_HOME` 隔离目录 + `dsh --profile <web-profile> --from-default-profile web` 初始化自定义 profile（同 D6：shipped 模板名禁作自定义 profile 目标，必须携带 `--profile` 自定义名），bridge 插件（`FENIX_IT_PLUGINS_REPO` 供源）`pnpm build` 后以软链挂入 profile（对齐 dsh-bundle README 的软链安装口径，`file:` 拷贝会断 peer 链）。dashboard 服务先行启动（:8787；dist 构建产物不入 git——源码克隆形态下若 `core/dashboard/static/dist/index.html` 缺失，编排须先执行 `npm install --no-audit --no-fund && npm run build` 构建前端，对齐 install.sh 的源码使用者提示），随后 `dsh web` 起服（容器内固定 :3080）。GUI 断言脚本 `checks/check_dsh_web.py`（Playwright sync API + 镜像内 chromium headless）：打开 `http://127.0.0.1:3080` → 定位面板桥注入的「项目」菜单行元素 → 断言其 iframe 存在且 src 含 `embed=1` → `page.frame_locator` 进入 iframe 断言 dashboard 前端根节点已渲染（Playwright 经 CDP 驱动，跨 origin iframe 可进入）→ 截图落产物目录。

**D8 smoke 模式与本 SPEC 自验证**：`--smoke` 跳过双轮真实闭环，执行：镜像自检（CLI/Playwright/基础工具版本打印）→ 克隆安装 → 夹具项目创建 + daemon 启动健康检查 → 三插件面验证（含 D7 完整 GUI）。本 SPEC 自身的验证场景为 cli 形态、执行 `run.sh --smoke` 以退出码判定（时间预算按验证场景超时配置放宽至 ≥20 分钟，镜像已预热时实际约 5-10 分钟）。

**D9 产物契约**：摘要 `summary.json`（模式、双轮终态/耗时/判定、三插件面结果、失败明细）、编排与 daemon 日志、验证报告副本、GUI 截图，全部落 `FENIX_IT_ARTIFACTS_DIR`。退出码 0/1/2 语义见 spec。

## Risks / Trade-offs

- [fenixsoft/fenixd 若非公开仓，HTTPS 克隆失败] → `FENIX_IT_GIT_REPO` 可覆盖为可达地址；克隆失败 fail-loud 并在 README 给出 PAT/SSH 手工改造指引；smoke 模式同样依赖克隆，故同样暴露该风险。
- [dsh-plugins 源不可达或构建失败] → 双形态供源（宿主路径挂载 / git URL）；失败不静默，dsh web 面 fail-loud（用户已确认完整 GUI 验证为必需面）。
- [真实 e2e 受模型质量/速度影响，耗时长且可能 bugfound 打回多轮] → 夹具 SPEC 刻意极简（单文件、确定性 DOM 断言）；每轮独立超时预算；打回循环由框架预算机制自然兜底，超时即判该轮失败并在摘要留证据。
- [镜像构建耗时长（apt/npm/pip/playwright 下载）] → Dockerfile 分层排序（低频变动层在前）+ 内容哈希 tag 复用 + `--build-only` 预热；构建工具不清理换取可调试性。
- [dsh web node-pty 原生编译在容器内失败] → 构建期预装 `build-essential` + python3；失败属镜像构建期错误，exit 2 即时暴露。
- [验证引擎跑本 SPEC 场景时 Docker 权限/耗时问题] → 场景声明 cli 形态并放宽超时；若验证环境 Docker 不可用，按「环境类失败豁免握手」既有机制处置，不误判 bugfound。
- [集成运行产物污染 git] → 默认落 `.history/`（gitignored）；`FENIX_IT_ARTIFACTS_DIR` 覆盖时由调用者自担路径纪律。

## Migration Plan

纯新增目录，无迁移。回滚 = 删除 `tests/integration/`（不影响任何既有面）。上线顺序：合并后人工首次执行 `run.sh --build-only` 预热镜像，再择机执行真实双轮（需注入凭据）；smoke 模式可随时重复。

## Open Questions

- `FENIX_IT_PLUGINS_REPO` 的长期默认值（dsh-plugins 仓的公开 git URL）待插件仓定址后钉入 README；当前默认取宿主 `/root/dsh-plugins` 挂载，不影响功能闭环。
