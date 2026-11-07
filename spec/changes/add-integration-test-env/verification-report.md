# 验证报告：add-integration-test-env

> ⚠️ 本报告由框架于 2026-11-07T17:56:40Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-07T17:54:02.154638+00:00+run-result@mtime1794074187688450681

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 9/10 场景通过，1 失败，0 错误（1 个真实产品 Bug）**

10 场景：9 pass / 1 failed（product-bug，无 warning）。唯一失败 it-env-file-auto-load-cred-gate 根因为 run.sh 缺失 design D3 的 .env 自动加载（全文无 source .env，凭据门仅读环境变量），2 条失败断言同根级联合并为 1 个 major bug 走 implementer 修复链；其余 9 场景（语法门/参数契约/缺凭据 fail-loud/镜像构建复用/镜像纯度/smoke 全绿/产物落盘/双轮独立汇总/插件仓不可达 fail-loud）全绿。

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 7.92M |
| 本链增量 Token（输出） | 0.21M |


## 真实产品 Bug

### BUG-01（severity=major）· output_match

- 关联场景：it-env-file-auto-load-cred-gate
- 描述：run.sh 未实现 design D3 要求的 tests/integration/.env 自动加载：真实模式凭据门（run.sh L100-120）仅读进程环境变量，全文无 set -a; source; set +a 逻辑。宿主机预置凭据文件成为死文件，真实双轮必须手工 export 三要素，违反 tasks 1.2 / design.md L43 契约
- 根因：as-built run.sh 缺失 D3 规定的 .env 自动加载步骤；级联后果：凭据门先行 exit 2，FENIX_IT_GIT_REPO 目录检查（L155-157）不可达（GIT_GATE_HIT=no 同根级联，合并为 1 个 bug）
- 证据（场景 it-env-file-auto-load-cred-gate 结构化证据，引用）：
  - failed_assertions: [{"type": "output_match", "selector": "ENVFILE_LOADED", "expected": "ENVFILE_LOADED=yes", "actual": "ENVFILE_LOADED=no（stdout 实录 \"RC=2/ENVFILE_LOADED=no/GIT_GATE_HIT=no\"，预置 .env 后凭据门仍输出缺少 LLM 凭据清单）"}, {"type": "output_match", "selector": "GIT_GATE_HIT", "expected": "GIT_GATE_HIT=yes", "actual": "GIT_GATE_HIT=no（凭据门先行 exit 2，未抵达 FENIX_IT_GIT_REPO=/tmp/it-not-a-repo 的目录检查）"}]
  - screenshots: []
  - first_failed_step: 步骤1(envload)：向 tests/integration/.env 写入三要素假凭据并卸载进程变量后执行真实模式，凭据门仍报「缺少 LLM 凭据」exit 2——.env 未被加载


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| it-delivery-syntax-gate | 交付物完整性与语法门（tasks.md Deliverables 清单 + 任务 4.2 收尾自检）：tests/integration 下 11 件交付物在场（Dockerfile、run.sh、e2e.sh、checks/×3、fixture/×4、README），run.sh/e2e.sh/check_skills.sh/check_dashboard.sh 过 bash -n、check_dsh_web.py 过 py_compile；.gitignore 覆盖 tests/integration/.env（gitignored 运行时凭据文件契约，design D3）。出处：spec/changes/add-integration-test-env/tasks.md Deliverables 段与任务 4.2、.gitignore:85 | pass | 0/3 | - |
| it-cli-arg-help-unknown | run.sh 参数解析与用法文档契约：--help 输出用法（含 --smoke/--build-only 指引、FENIX_IT_GIT_REPO 默认 GitHub 克隆源 https://github.com/fenixsoft/fenixd.git、退出码 0/1/2 语义）且 exit 0；未知参数输出「未知参数」提示且 exit 2（用法/装置错误档，覆盖退出码语义的场景面之一）。出处：tests/integration/run.sh:38-45（arg 分支）、run.sh:5-28（用法注释块经 sed -n '3,30p' 输出） | pass | 0/8 | - |
| it-real-mode-missing-creds-fail-loud | 真实模式缺凭据 fail-loud 且零调用（spec「一键运行编排契约」场景1）：显式卸载三个 FENIX_IT_LLM_* 环境变量执行真实模式（验证树无 .env 或其不被消费时同判——缺项判定发生在凭据门），期望在任何容器/克隆/网络动作之前 exit 2，输出缺失项清单（点名三个变量）与修复指引（含免凭据 --smoke 指引），且无「启动容器」痕迹（对齐 bin/dsh_acceptance.py accept 的信号式自检哲学）。宿主侧纯检查零容器动作。出处：tests/integration/run.sh:100-119 与 spec.md 同名 Scenario | pass | 0/8 | - |
| it-image-build-dual-harness-cli | 镜像构建成功且双 harness CLI 可用（spec「轻量测试镜像契约」场景1）：run.sh --build-only 构建成功退出（输出「预热完成」）、二次调用幂等复用镜像（输出「镜像已存在」，内容哈希 tag fenix-it-env:<sha256 前 12 位> 复用回归点，design D2）；镜像内 claude --version 可输出版本、dsh --version 含钉版 0.2.0-rc.2（spec 版本钉扎要求）。环境依赖（Docker daemon 与基础镜像/npm 包拉取；有 fallback: Dockerfile 层缓存 + 内容哈希 tag 复用——本机镜像 fenix-it-env:89ad0e0af6d4 已预热，命中秒级复用路径）。出处：tests/integration/run.sh:72-98、Dockerfile 全文 | pass | 0/8 | - |
| it-image-purity-no-framework-no-llm | 镜像纯度契约（spec「轻量测试镜像契约」场景2）：静态层——Dockerfile 无 git clone 指令、tests/integration 入库文件无真实 key 形态字面值（sk-+≥8 位字母数字；--exclude=.env：设计内 gitignored 本机凭据注入文件豁免，tasks 1.2/design 明确 key 只落该文件，第一轮裁决 test-defect 修复口径沿用）；运行期层——镜像文件系统无 fenixd.py/.fenix 框架残留（框架只在运行期克隆，design D2）、镜像 env 无 FENIX_IT_LLM_* 声明、docker history 无 key 形态残留。依赖镜像已构建（depends_on it-image-build-dual-harness-cli）。出处：tests/integration/Dockerfile:1-31、spec.md 同名 Scenario | pass | 0/7 | - |
| it-env-file-auto-load-cred-gate | 预置 .env 自动加载使凭据门放行（spec「一键运行编排契约」场景2「预置 .env 自动加载跑通真实模式」的凭据门机制面，design D3：凭据缺项判定前 MUST 自动加载 tests/integration/.env 作环境变量默认值，set -a; source; set +a）：备份既有 .env（如有）后临时写入假凭据，环境变量卸载三要素 + FENIX_IT_GIT_REPO 指向非 git 目录触发装置检查——期望凭据自检因 .env 自动加载而放行（输出无「缺少 LLM 凭据」清单）、命中「FENIX_IT_GIT_REPO 目录不是 git 仓库」die2 exit 2（证明流程已越过凭据门）、假 key 明文不出现在输出（key 不入日志）。跑完恢复/清理 .env。出处：design.md D3、tests/integration/run.sh:100-157 | failed | 2/5 | product-bug |
| it-smoke-mode-full-green | smoke 免凭据全绿（spec「smoke 免凭据模式」场景1 + 场景2「被验证引擎复用」——本场景即引擎复用的 cli 执行目标，design D8）：免凭据执行 run.sh --smoke 全链——镜像自检（双 harness CLI/Playwright/Chromium 版本打印）、克隆安装（FENIX_IT_GIT_REPO=$PWD 本地仓形态，spec 环境变量契约内的覆盖面，消除容器内 GitHub 外联的不可自建环境依赖；运行期克隆框架不入镜像契约不变，第一轮 smoke 场景 GitHub 默认源已按 env 豁免留档）、夹具项目创建 + daemon 启动健康检查、三插件面（skill 装配 / dashboard HTTP 200 + 夹具项目可见 / dsh web 完整 GUI：面板桥「项目」菜单行、iframe src 含 embed=1、dashboard 前端 iframe 内渲染、截图落盘）全部 pass 且 exit 0；summary.json 落盘（mode=smoke、exit_code=0、plugin_faces 三面全 pass、rounds[0]=pass）。环境依赖（容器内 npm/pnpm 安装与 Chromium；有 fallback: FENIX_IT_GIT_REPO/FENIX_IT_PLUGINS_REPO 可覆盖可达源——本场景已用本地仓形态）。出处：tests/integration/e2e.sh:489-507（smoke 分派）、e2e.sh:529-546（三插件面）、run.sh:148-162（本地仓形态挂载） | pass | 0/9 | - |
| it-artifacts-complete-contract | 产物完整落盘契约（spec「产物落盘与退出码契约」场景1）：依赖 smoke 运行的产物目录（.history/it-verify/smoke，gitignored 临时产物约定）下存在可解析的 summary.json（含 mode/exit_code/rounds/plugin_faces/failures/artifacts_dir/finished_at 七字段与 git_repo 溯源值）、编排日志 orchestrate.log、安装日志 install.log、前端构建日志 frontend-build.log、daemon 日志 daemon-smoke.log 与 dsh web GUI 截图 dsh-web-embed.png。出处：tests/integration/e2e.sh:54-88（write_summary 字段契约）、e2e.sh:41/155/167/433/500（日志路径）、checks/check_dsh_web.py:348（截图名）、spec.md 同名 Scenario | pass | 0/11 | - |
| it-dual-round-independent-summary | 双 harness 独立轮执行并汇总（spec「双 harness 各跑一轮」场景1 的可机械验证面 + 场景2 dsh 轮 bundle 车道的编排面）：注入占位凭据（http://127.0.0.1:1 恒拒绝，零真实模型调用零费用）与 FENIX_IT_TIMEOUT=240 执行真实模式——claude 与 dsh 两轮各自独立夹具项目/配置/超时预算，占位凭据下两轮均 fail 但互不阻断（dsh 轮含 fenix-dsh-bundle 容器内部署：npm install + 自定义 profile 创建 + dsh plugin add "link:<repo>" 软链挂入 + bundles 追加 + dump-config 挂载自检），摘要 JSON 汇总双轮终态（rounds 同时含 claude 与 dsh 各自 fail）与三插件面记录且整体 exit 1（退出码契约：判定失败=1）。dsh 轮模型显式配置三要素经同源注入恒齐备；三要素缺失 fail-loud 负例分支需真实凭据轮触达、占位凭据轮不可达，不作断言。真实 LLM 全链闭环（编排契约场景3）按 proposal L20 属人工/CI 触发步骤、不在验证场景面。交互契约候选 link（design.md:49 的 dsh plugin add "link:<repo>" 为插件软链安装语法记号，非页面交互元素）声明纯展示。环境依赖（Docker；有 fallback: FENIX_IT_GIT_REPO=$PWD 本地仓形态消除 GitHub 外联）。出处：tests/integration/e2e.sh:509-518（双轮分派）、e2e.sh:373-427（bundle 部署）、run.sh:206-211（退出码语义） | pass | 0/8 | - |
| it-plugin-repo-unreachable-fail-loud | 插件仓不可达时明确报告（spec「三插件面安装与使用验证」场景3 + 退出码契约判定失败档）：FENIX_IT_PLUGINS_REPO 指向保留 TLD 不可解析域（https://it-unreachable.invalid/...，失败确定且快速）执行 --smoke，dsh web 插件面须 fail-loud——摘要 plugin_faces.dsh_web=fail、failures 非空且明细点名 dsh 面（含失败阶段与原始错误）、整体 exit 1（不静默降级为通过，design D7 与风险段）；skills/dashboard 两面不受牵连仍在场记录。环境依赖（前置克隆/安装/daemon 各面正常推进；有 fallback: FENIX_IT_GIT_REPO=$PWD 本地仓形态）。出处：tests/integration/e2e.sh:542-546（dsh web 面 fail-loud）、checks/check_dsh_web.py（插件源克隆段）、spec.md 同名 Scenario | pass | 0/7 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

当前稳定场景集共 13 个（第 1 轮）。

- 无理由缺失 3 个场景，已以持久化集补齐：it-image-build-and-dual-harness-cli、it-image-purity-no-framework-no-llm-residue、it-real-mode-missing-credentials-fail-loud
- 新增场景 it-image-build-dual-harness-cli（重新规划，第 1 轮）
- 无理由缺失且备份缺定义的场景 3 个定义不可恢复，已剔除：it-image-build-and-dual-harness-cli、it-image-purity-no-framework-no-llm-residue、it-real-mode-missing-credentials-fail-loud

> ⚠️ 本轮 planner 产出缺少既有场景且无理由，已以持久化集补齐后继续验证（不中断验证）。

