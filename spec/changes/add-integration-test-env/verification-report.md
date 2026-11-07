# 验证报告：add-integration-test-env

> ⚠️ 本报告由框架于 2026-11-07T16:44:50Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-07T16:43:12.716182+00:00+run-result@mtime1794069879107151432

## 结论：✅ 通过（verified）

**状态：verified — 5/6 场景通过，1 失败，0 错误（结构化数据存在失败明细，终局判定以 verification.verdict 为准）**

6 场景 5 过 1 挂，零产品 Bug。唯一失败 it-smoke-mode-full-green 判 env：容器内对 github.com 网络不可达（浅克隆回退完整克隆仍失败，15:20→16:37 约 17 分钟），属场景描述已声明的环境依赖且不可自建替换（覆盖 FENIX_IT_GIT_REPO 即失去本场景承担的 GitHub 公开克隆契约）；产品侧行为正确（fail-loud 报错并落盘 summary.json），按 env 豁免处置不阻塞。旁证：it-plugin-repo-unreachable-fail-loud 同窗同源克隆同败（15:41→16:43），非偶发，与豁免同窗并行上下文一致（batch 3/5 observed_parallel=1）。观察项（非 Bug 不阻塞）：it-dual-round-independent-summary 运行中 e2e.sh line 346 command substitution 语法报错两次（' || echo read_error)' 引号/括号解析缺陷，错误上报路径），该场景为设计负例、全部契约断言通过，仅 stderr 噪音。

| 指标 | 数量 |
| --- | --- |
| 通过 | 5 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.32M |
| 本链增量 Token（输出） | 0.10M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| it-image-build-and-dual-harness-cli | 镜像构建成功且双 harness CLI 可用（spec「轻量测试镜像契约」场景1）：run.sh --build-only 构建成功退出、二次调用幂等复用镜像（内容哈希 tag 复用回归点）、镜像内 claude --version 输出版本号、dsh --version 输出钉版 0.2.0-rc.2。镜像名 fenix-it-env:<内容哈希>（design D2），步骤以 docker images 前缀探测不硬编码哈希。另登记交互契约候选 link（design.md:49 的 dsh plugin add "link:<repo>" 为插件软链安装语法记号，非页面交互元素，声明纯展示）。环境依赖（基础镜像与 npm 包拉取；有 fallback: Dockerfile 层缓存 + hash tag 复用，已预热时秒级通过） | pass | 0/6 | - |
| it-real-mode-missing-credentials-fail-loud | 真实模式缺凭据 fail-loud 且零调用（spec「一键运行编排契约」场景1 + design D3）：显式卸载三个 LLM 环境变量执行 run.sh（真实模式），须在任何容器/克隆/网络动作之前输出缺失项清单并以 exit 2 退出（对齐 bin/dsh_acceptance.py accept 的人工信号式哲学）；断言缺失清单点名三个缺失变量、输出无克隆动作痕迹（零容器/零网络调用）。宿主侧纯检查，不依赖 Docker 与外部网络 | pass | 0/5 | - |
| it-image-purity-no-framework-no-llm-residue | 镜像纯度契约（spec「轻量测试镜像契约」场景2）：Dockerfile 静态层无框架烘焙痕迹（无 git clone、无框架源码 COPY）、tests/integration 入库文件无 LLM key 字面值残留（运行期注入形态只允许出现变量名，不允许出现键值字面量；设计内 gitignored 本机凭据注入文件 tests/integration/.env 除外——tasks 1.2/design 明确 key 只落该文件、禁止入库）；并进入镜像文件层运行期复查无 fenixd.py 框架源码（框架只允许运行期克隆，design D2） | pass | 0/4 | - |
| it-smoke-mode-full-green | smoke 免凭据全绿（spec「smoke 免凭据模式」场景1，design D8 本 SPEC 自身验证的确定性执行目标）：免凭据执行 run.sh --smoke——镜像环境自检（双 harness CLI/Playwright/基础工具）、GitHub 克隆安装、夹具项目创建 + daemon 启动健康检查、三插件面验证（skill 装配 / dashboard 服务 / dsh web 完整 GUI 面板桥 iframe 挂载）全部通过且 exit 0；产物目录落 summary.json（可解析且含模式字段）与 GUI 截图。超时预算 1800s（≥20 分钟，design D8）。环境依赖（GitHub 公开仓克隆 + npm registry；有 fallback: FENIX_IT_GIT_REPO/FENIX_IT_PLUGINS_REPO 可覆盖为可达源） | fail | 2/5 | env |
| it-dual-round-independent-summary | 双 harness 独立轮执行并汇总（spec「双 harness 各跑一轮」场景1 的可机械验证面）：注入占位凭据（http://127.0.0.1:1 恒拒绝，零真实模型调用零费用）与 FENIX_IT_TIMEOUT=240 执行真实模式——claude 与 dsh 两轮各自独立夹具/配置/超时，占位凭据下两轮均失败但互不阻断、摘要 JSON 汇总双轮终态/耗时/判定（含双轮标识）且整体 exit 1（退出码契约：判定失败=1）。dsh 轮模型三要素经同源注入恒齐备，缺项 fail-loud 负例经公开接口不可达，轮级失败以摘要留痕验证。框架源钉定本机仓库目录形态（FENIX_IT_GIT_REPO=$PWD，spec proposal L12 明示仓库/引用可经环境变量覆盖），消除 incidental 的 GitHub 网络依赖；GitHub 公开克隆契约由 it-smoke-mode-full-green 场景覆盖 | pass | 0/4 | - |
| it-plugin-repo-unreachable-fail-loud | 插件仓不可达时明确报告（spec「三插件面安装与使用验证」负例场景 + 退出码契约）：FENIX_IT_PLUGINS_REPO 指向不可解析域名的 git URL 执行 --smoke，dsh web 插件面须 fail-loud 报告失败阶段与原始错误、整体退出码 1（判定失败档），不静默降级为通过；摘要落盘且记录 dsh 插件面结果。环境依赖（前置克隆/安装各面正常推进；有 fallback: FENIX_IT_GIT_REPO 覆盖可达源） | pass | 0/4 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| it-smoke-mode-full-green | exit_code == 0（smoke 全绿退出） | env | 环境因素（非产品缺陷） | 容器内对 github.com 网络不可达：浅克隆失败回退完整克隆后仍失败，error=框架克隆失败 repo=https://github.com/fenixsoft/fenixd.git；网络环境不可达，无法验证。该依赖为场景描述已声明的环境依赖（GitHub 公开仓克隆，有 FENIX_IT_GIT_REP... |
| it-smoke-mode-full-green | dir_contains .history/it-verify/smoke/**/*.png ≥1 | env | 环境因素（非产品缺陷） | 截图缺失是克隆失败的级联结果：smoke 流程在克隆阶段终止，未进入夹具项目/daemon/三插件面验证与截图阶段，与同场景 exit_code 失败同根因，非独立缺陷 |

## 本轮场景集变更

当前稳定场景集共 6 个（第 1 轮）。

- 首轮写入 6 个场景

