# Tasks: add-integration-test-env — Docker 集成测试环境与双 harness 端到端验证

## Deliverables

```yaml
- path: tests/integration/Dockerfile
  kind: new
- path: tests/integration/run.sh
  kind: new
- path: tests/integration/e2e.sh
  kind: new
- path: tests/integration/checks/check_skills.sh
  kind: new
- path: tests/integration/checks/check_dashboard.sh
  kind: new
- path: tests/integration/checks/check_dsh_web.py
  kind: new
- path: tests/integration/fixture/index.html
  kind: new
- path: tests/integration/fixture/app.js
  kind: new
- path: tests/integration/fixture/spec-proposal.md
  kind: new
- path: tests/integration/fixture/spec-tasks.md
  kind: new
- path: tests/integration/README.md
  kind: new
- path: .gitignore
  kind: modify
  note: 追加 tests/integration/.env 忽略规则
```

## 1. 测试镜像与一键入口

- [x] 1.1 编写 `tests/integration/Dockerfile`：基底 `debian:bookworm-slim`，分层安装 python3.11、Node 20（NodeSource）、git、tmux、curl、ca-certificates、build-essential、pnpm；全局安装 claude code CLI（`@anthropic-ai/claude-code`）与 `@deepseek-ai/dsh@0.2.0-rc.2`（版本钉扎）；pip 安装 playwright 并 `playwright install --with-deps chromium`；镜像内不包含 fenix 框架代码与任何 LLM 凭据；在本机 Docker 环境完成构建验证并记录镜像大小（若实现环境 Docker 不可用，按 unattainable 申报并交付构建指令）
- [x] 1.2 编写 `tests/integration/run.sh`：环境变量契约全量实现（`FENIX_IT_LLM_BASE_URL/API_KEY/MODEL`、`FENIX_IT_GIT_REPO/GIT_REF`、`FENIX_IT_PLUGINS_REPO` 支持宿主路径或 git URL 双形态、`FENIX_IT_TIMEOUT`、`FENIX_IT_ARTIFACTS_DIR` 默认 `.history/integration-runs/<UTC时间戳>/`）；`--build-only` / `--smoke` 旗标；镜像按 Dockerfile 内容哈希 tag `fenix-it-env:<hash>` 复用；真实模式启动前先自动加载宿主机预置凭据文件 `tests/integration/.env`（`set -a; source; set +a`；文件已随本 SPEC 预置于主树且已入 .gitignore，内容为 provider bigmodel.cn 的 baseurl/key/model=glm-5.3-flash，进程环境变量优先于文件值），随后凭据自检——缺项列清单以 exit 2 退出且不发起任何容器/克隆/网络动作；key 明文禁止出现在入库文件、镜像层与日志输出；`docker run` 注入环境变量并只读挂载 `tests/integration` → `/opt/it` 与 `FENIX_IT_PLUGINS_REPO`（路径形态时），另将 `FENIX_IT_ARTIFACTS_DIR` 以读写卷挂至容器内固定路径 `/artifacts`（时间戳目录由 run.sh 宿主侧创建；`/opt/it` 只读，产物仅能经该卷落回宿主）；转发容器退出码并落盘产物；本任务自检：`bash -n run.sh` 通过；临时移开 `tests/integration/.env` 后无凭据执行 exit 2 且输出缺失项清单，恢复后重新执行自检通过（证明自动加载生效）
- [x] 1.3 编写 `tests/integration/e2e.sh`（容器内主编排）：HTTPS 克隆框架（`FENIX_IT_GIT_REPO`/`FENIX_IT_GIT_REF`）→ 执行 `install.sh` → 夹具项目创建（复制 `/opt/it/fixture` 模板、git init/commit）→ 依注入环境变量生成 `.fenix/config.yaml`（provider baseurl/key/model、`agent.harness`、`project.type: web`、审批门保持人工档）→ dashboard 前端 dist 缺失时先构建（`npm install --no-audit --no-fund && npm run build`；dist 不入 git）→ `nohup python3 fenixd.py` 启动 daemon 并做健康检查 → 经 `.fenix/bin/fenix_spec.py new` + 种子覆写 + `core.state_machine.add_spec` 程序化注册 fast-track 简单 SPEC → 按 `FENIX_IT_TIMEOUT` 轮询 STATE.md 至 `done`/`blocked` → 断言（终态 done、merge-back 后夹具页面含预期元素、验证报告 pass verdict、`.fenix/runs/` 存在 run jsonl）→ 写 `summary.json`；smoke 模式跳过 SPEC 注册与闭环轮次
- [x] 1.4 实现 `e2e.sh` 双轮编排：`/work/round-claude/` 与 `/work/round-dsh/` 独立夹具项目、独立配置（仅 `agent.harness` 不同）与独立超时预算；dsh 轮前置完成 fenix-dsh-bundle 容器内部署（按 `dsh-bundle/README.md` 部署段：`dsh --profile <p> --from-default-profile headless` 创建自定义 profile → `dsh plugin --profile <p> add "link:<repo>/dsh-bundle"` 软链挂入 → package.json bundles 追加；profile 名与 `agent.dsh_profile` 一致；shipped 模板名被 CLI 禁止作为自定义 profile 目标），随后校验模型显式配置三要素齐备（缺任一该轮 fail-loud）；任一轮失败记录后继续另一轮；汇总双轮终态/耗时/判定入 `summary.json`，任一失败整体 exit 1

## 2. 三插件面检查脚本

- [x] 2.1 编写 `tests/integration/checks/check_skills.sh`：断言 `~/.claude/skills/` 下 fenix-* skill 软链存在且 SKILL.md 可读、`fenix-init` 在 PATH、`claude --version` 可执行、在夹具项目内 `.fenix/bin/fenix_spec.py status` 运行成功；任一失败输出失败项与原始错误并 exit 1
- [x] 2.2 编写 `tests/integration/checks/check_dashboard.sh`：启动 `fenix_dashboard.py --serve`（幂等：已监听则复用）、轮询 HTTP 200、注册夹具项目（`--add-project`）后经 dashboard 接口/页面确认项目可见、输出可达 URL；失败 fail-loud exit 1
- [x] 2.3 编写 `tests/integration/checks/check_dsh_web.py`（Playwright 完整 GUI 验证）：`DSH_HOME` 隔离目录 + `dsh --profile <自定义名> --from-default-profile web` 初始化自定义 profile（shipped 模板名被 CLI 禁止作为自定义 profile 目标，必须携带 `--profile`）；bridge 插件供源（宿主路径挂载或 git URL 克隆）后 `pnpm build` 并以软链形态挂入 profile（对齐 dsh-bundle 软链安装口径）；dashboard 服务先行就绪后启动 `dsh web`（容器内 :3080）；Playwright 打开页面 → 断言面板桥「项目」菜单行元素存在 → 断言其 iframe src 含 `embed=1` → `frame_locator` 进入 iframe 断言 dashboard 前端根节点渲染 → headless chromium 截图落产物目录；插件源不可达/构建失败时输出失败阶段与原始错误并 exit 1（不静默降级）

## 3. 夹具模板与 smoke 模式

- [x] 3.1 编写夹具模板四件：`fixture/index.html`（静态小站骨架，含标题与容器节点）、`fixture/app.js`（极简交互脚本）、`fixture/spec-proposal.md` 与 `fixture/spec-tasks.md`（简单 SPEC 种子：添加带稳定 testid 的徽标元素、点击切换文案，任务粒度为实现 Agent 可独立完成的单文件改动，含 Deliverables 声明段且路径指向夹具项目内文件）
- [x] 3.2 将 `--smoke` 模式贯通 `run.sh`/`e2e.sh`：免凭据执行镜像自检（双 harness CLI 与 playwright/chromium 版本打印）→ 克隆安装 → 夹具项目创建 + daemon 启动健康检查 → 三插件面检查（含 dsh web 完整 GUI）→ `summary.json` 落盘 exit 0；在本机 Docker 环境实际执行一次 `run.sh --smoke` 全绿并保留 `summary.json` 于 `.history/integration-runs/`（若实现环境 Docker 不可用，按 unattainable 申报附已完成的静态自检证据）

## 4. 文档与收尾自检

- [x] 4.1 编写 `tests/integration/README.md`：用途与架构一段、快速开始（构建预热 → smoke → 真实双轮）、环境变量契约表（与 D3 一致）、产物目录与退出码语义、**人工步骤**专节（本机已预置 `tests/integration/.env`（gitignored，provider bigmodel.cn / glm-5.3-flash），真实双轮无需手工注入即可触发；新环境需自行创建该文件或 export 环境变量，模板见 README；`FENIX_IT_PLUGINS_REPO` 长期默认地址待插件仓定址后钉入）、故障排查（GitHub 私有仓 PAT/SSH 改造指引、插件仓不可达处置、dashboard dist 缺失需先 `npm run build`、dsh web 启动失败排查——含 shipped 模板名禁作自定义 profile 目标的报错口径）
- [x] 4.2 收尾自检：`bash -n` 覆盖 run.sh/e2e.sh/check_skills.sh/check_dashboard.sh；`python3 -m py_compile` 覆盖 check_dsh_web.py；run.sh 无凭据 dry-run exit 2（临时移开 `.env` 验证，后恢复）；`shellcheck`（如可用）零 error 级告警；夹具 SPEC 种子的 Deliverables 声明路径与 lint 规则自洽（具体文件路径、无目录/占位符）；`tests/` 既有 pytest 套件零受累（新增文件不进 pytest 收集路径或以显式忽略规避）

## 验证修复（原地打回第 2 轮）

- [ ] 先复核失败有效性：逐条核对 `spec/changes/add-integration-test-env/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
