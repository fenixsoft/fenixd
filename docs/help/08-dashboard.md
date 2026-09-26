# Dashboard 使用指南

Fenix Web Dashboard（`http://localhost:8787`）是跨项目的可视化监控与运维入口。日常查看进度、处理告警、调整配置都可以在这里完成，本章按五个页面逐一讲解。

## 启动

```bash
/fenix-dashboard
```

命令会输出可直接粘贴到浏览器的访问 URL。Dashboard 进程是独立的长驻服务，由 `/fenix-dashboard` 启动或复用已有实例；目标端口被占用时由旧 dashboard 实例自动接管，不会出现两个实例抢端口。

## 侧边栏菜单

| 菜单 | 路径 | 用途 |
|------|------|------|
| 概览 | `/overview` | 跨项目状态统计、任务进度、问题、活跃运行 |
| 项目 | `/projects` | 项目列表与各项目聚合摘要 |
| 设置 | `/settings` | 配置管理、验证契约、token 预算面板 |
| 运维 | `/activities` | Administrator 活动时间线 + 人工告警处置 |
| 帮助 | `/help` | 帮助文档中心（本文档集） |

## 五页逐面板

### 概览页（/overview）

概览页是打开频率最高的一页，回答「现在整体怎么样」。它聚合跨项目的 SPEC 总数与按状态分类的计数、任务完成率（task_done/task_total）、各项目的问题计数（阻塞/告警），以及正在进行的 Agent run 列表（按类型分组）。

### 项目列表页（/projects）

项目页列出所有已注册项目，每张卡片展示 daemon 健康状态、SPEC 数、状态分布、任务进度、验证场景数与项目简介。项目级操作也集中在这里：启停 daemon（start/stop）、安装托管（install-hosting）、软删除（delete）、重新生成简介。

#### 托管态徽标与「安装托管」

每张卡片的 daemon 状态徽标按托管态三态渲染（数据字段 `daemon` + `hosting`，来自 `/api/projects` 与 `/api/overview`）：

| 显示 | 托管态（hosting） | 含义 |
|------|-------------------|------|
| `运行中` | `managed` | daemon 受 supervisor 托管，restart_request / 审批推送等文件信号有消费方 |
| `运行中·未托管` | `unmanaged` | 裸 daemon——进程在跑但无 supervisor，文件信号无人消费（存量项目典型状态） |
| `未运行` | `stopped` | daemon 未运行 |

`unmanaged` 项目的操作菜单会多出「安装托管」项：一键执行「停止裸 daemon → 经 supervisor 启动」，使其转入 `managed`（对已托管项目幂等返回、不重启）。`unmanaged` 项目上的「重启」与「审批推送」操作会被拒绝并提示先安装托管——写文件信号前必须确认有消费者，避免信号永久滞留锁死该项目后续全部审批推送。

#### 项目详情页分面（/projects/:name）

点进项目卡片进入详情页，顶部 Tabs 分五个分面：「功能开发」（默认，SPEC 列表与状态操作）/「代码审查」（code-review 问题台账 + 手动触发与五类操作，见下文）/「测试回归」/「项目架构」/「会话接入」。各分面 active 门控：仅在选中时拉取数据，未选中零请求。

「功能开发」分面的筛选条件（页签 / 搜索词 / 状态多选 / 类型 / 已归档过滤）会写入 URL（`core/dashboard/static/src/pages/projects/listFilters.ts`），刷新、分享链接、浏览器前进后退都能保留；解析走白名单 + fail-safe，非法参数静默忽略，不影响列表渲染。

「测试回归」分面（`GET /api/regression/result`）按最近一次全量回归快照 `.fenix/regression/last-run.json` 渲染三态：
- **全绿（passed）**：概览卡片展示测试路径（`cmd`）、用例总数、通过数、执行时间（本地时区）、总耗时；若存在长耗时用例（单用例耗时 > `verify.yaml` 的 `regression.long_test_threshold_seconds`，缺省 8s）仍在其下展示长耗时用例表；
- **存在失败/错误/超时/长耗时**：概览之下渲染结果表格，逐条列出异常用例（用例名 / 文件:行 / 耗时 / 分类——失败 / 错误 / 超时 / 长耗时），超时用例附中止原因；
- **未执行（never_run）/ 结果不可解析（parse_error）**：展示引导态（「尚未执行过全量回归」/「结果不可解析 + 原因」），不报错、不显示空表。

分面不承载周期开关（归设置页「质量」页签），提供「立即执行全量回归」按钮（`POST /api/regression/run`，写 `.fenix/regression_request.json` 信号由 daemon 主循环消费，不在 HTTP 线程内同步跑——回归可运行 1800s）。运行中态以服务端快照的 `running` 字段为准（marker 新鲜度判定），跨刷新不丢失。

结果存在失败/错误/超时条目时，分面提供「自动修复回归问题」按钮：点击后写 `.fenix/code_fix_request.json` 信号（daemon 消费，`manual_authorized` 随链持久化），按钮进入回链轮询（受理 → 执行 → 完成，约 1 秒间隔），修复执行进度由「代码修复进度卡」（CodeFixProgressCard，读 `.fenix/code-review/fix-progress.json` 与 fix-deferred 台账状态）展示——进度卡为**条级**粒度（done/total 逐条可见），并合成 code-fix run 的启动阶段（startup_stage，如选批/WIP 预检等前置阶段）一并呈现；失败/错误/超时/长耗时用例以 `regression-` 前缀转入 code-fix 台账（超时条目锚定 `verify.yaml` 的 regression 配置），同一指纹复发会自动重开条目。

「代码审查」分面是 code-review 问题台账的展示与操作入口（`QualityTab`），提供五个动作：「全库审查」「当期审查」「自动修复」「生成修复 SPEC」（确认框三档）与「全部忽略」。手动触发的受理是异步回链的：请求受理后按 run-result 三态反馈——`started`（已受理开跑）/ `dropped`（判重复或窗口外丢弃）/ `failed`（受理失败）；受理窗口内重复触发返回 409 `code_review_ack_pending`（上一轮仍处窗口内且无新 run），前端对应禁用按钮并两段轮询，受理凭据落 `.fenix/code-review/code_review_request_result.json`。台账条目支持以 `[fenix-ignore:<item_id>] <理由>` 注释固化误报裁决（审查 LLM 复核 MUST NOT 再上报）；「全部忽略」批量置 ignored 终态，code-fix 只对可豁免拒绝理由（false_positive / not_worth_fixing）走 mark_ignored。

「项目架构」分面承载按需生成的项目架构图。系统**不自动生成**：从未生成过时展示空态文案与「刷新架构图」按钮，点击后后端仅受理（`POST /api/architecture/refresh`），起后台线程 spawn 一次性 headless claude（archify skill 以 vendored 形式随库分发于 `vendor/archify/`，指引原文直接注入生成提示词，无需安装、零网络依赖）阅读项目代码，产出自包含交互式 HTML 架构图，按项目存于 `.fenix/architecture/`（gitignored 运行时产物），经 `GET /api/architecture/diagram` 下发、前端以 `sandbox="allow-scripts"` 的 iframe 沙箱渲染（不带 allow-same-origin，产物脚本与主站隔离）。生成期间按钮置灰并以 3 秒间隔轮询状态（`GET /api/architecture/status`）；同一项目同时最多一个在飞生成（重复触发返回 409）。图的形态契约：只保留 8–16 个核心组件、突出且仅一条主要路径、标出外部依赖与信任边界、辅助信息进说明卡片不增加连线、节点与说明中文标注；产物按「退出码 → 文件存在且非空 → 自包含 HTML 特征 → 组件数 ∈ [8, 16]」机械判定，不采信 agent 自述（组件数无法提取时记空放行，可用性优先）。刷新即覆盖旧图，只保留最近一次。

失败排查：archify skill 随库分发于 `vendor/archify/`（溯源见 `VENDORED.md`），无需安装，生成零网络依赖；生成前会校验包完整性（`SKILL.md` 存在且非空），若报「包缺件，属部署损坏」的 failed 错误，说明部署目录缺件或损坏，对照 `vendor/archify/VENDORED.md` 恢复包后重新点击「刷新架构图」即可。生成采用**两段式超时**（总预算 1800 秒不变）：探索段 ≤720 秒、出图段 ≤1080 秒分段计时，超时按当前阶段击杀 claude 进程及其派生子进程并判 failed（错误文案带阶段前缀）；状态接口的 `status` 含 `stage` 键（exploring/authoring）可区分当前所处阶段；HEAD 指纹与上次生成一致时重试会跳过探索段直接出图。**daemon 重启会中断在飞生成**：页签会把残留的「生成中」状态合成为失败（错误注明生成被中断），无需清理文件，直接重新点击「刷新架构图」即可。

「会话接入」分面把一个 Claude Code 会话直接接进浏览器（composer 组件 `SessionComposer` 位于 `core/dashboard/static/src/components/claude-composer/`，路由在 `core/dashboard/routes/session_routes.py`）。会话是**显式开始**的：点击「开始会话」才拉起；会话输出经 SSE 实时流（`/api/stream`）推送，事件按 uuid 去重，断线重连不会出现重复消息。

输入框（composer）的能力：

- 输入 `/` 唤起斜杠命令与 skill 补全（150ms 防抖），↑↓ 选择、Tab 补全、Enter 确认、Esc 关闭；历史命令按项目存 localStorage（`command_history_<project>`）；
- 输入 `@` 唤起文件提及补全，候选来自 `/api/session/files`（`git ls-files`，上限 5000 个；超时或非 git 仓库返回空数组）；
- 命令与 skill 列表来自 `/api/session/commands`（会话 init 事件的缓存；无在飞会话时返回空数组）;
- 草稿按项目自动持久化到 localStorage，切走再切回不丢；Enter 发送、Shift+Enter 换行；
- 「停止会话」随时中止当前会话进程；输出被截断时显示 truncated 提示；
- 移动端经 VisualViewport 适配软键盘弹起，输入框不被键盘遮挡。

空闲回收：会话空闲 1800 秒（30 分钟）被自动回收（`core/dashboard/session_manager.py` 的 `SESSION_IDLE_TIMEOUT_SECONDS`），再次使用时重新开始即可。

### SPEC 详情页（/projects/:name/:spec）

详情页上半部分是 SPEC 元数据：状态、优先级、创建/更新时间、分支与 error。元数据之下是**页面级页签**，共五个（实读 `detail.tsx`）：「运行时间轴」（run 与事件流）、「场景结果」（验证场景逐条结果）、「Bug 列表」、「失败截图」、「Hook」。

SPEC 的设计文档不在页面页签里，而是经**文档弹窗**（SpecDocModal）查看，弹窗内五个页签：需求背景（proposal）/ 详细设计（design）/ 任务清单（tasks）/ 测试场景清单 / 验证报告。两个层级不要混淆：「Hook 页签在失败截图之后」说的是页面级页签的排列；「五个页签的文档」说的是弹窗。

详情行工具条集中了针对单个 SPEC 的运维操作：设置优先级（1-9，P1 最高）、冻结/解冻（人工冻结为 blocked + 标记，解冻恢复）、清除错误（在线清除 error 字段并写回 STATE.md）、恢复运行（取消保持态 SPEC 的一键恢复：先判定能否保留实现分支——命中则保留分支续做、清零相关计数并即时唤醒派发；未命中降级为普通重派；终态/冻结/非保持态幂等拒绝）、归档（终态 SPEC 目录移入 archive）、删除（软删除，剔除 STATE.md 条目并把目录移入 archive），以及呼叫 Admin（手动唤起 Administrator，写 admin_invoke_request.json）。

**冻结**操作会立即终止该 SPEC 名下所有在跑的 agent（包括评审、实现、验证、修复等），现场经 WIP checkpoint 保全；解冻后若保留分支有未合并提交，自动在保留分支上 resume 续做（无需从零重做）。**删除**操作会先停止该 SPEC 的所有在跑 agent 并等待终态，终态齐备后才移入归档目录；有在跑 agent 时为异步受理（API 返回 `stopping: N`，前端提示「已受理，正在停止 N 个进行中的 agent」，spec 行在完成后消失），daemon 未托管时返回 409 拒绝。

详情页还有「Hook」页签（页面级页签，排在「失败截图」之后）分三个区块：「生效中的 Hooks」合并展示全局 hooks 与该 SPEC 的 spec 级 hooks（来源列标注「全局/本 spec」，含启停状态）；「本 spec 的 Hooks」对该 SPEC 的专属订阅做增删改与启停，表单为订阅事件多选 + 动作下拉 + 按动作类型显隐的参数（Webhook URL / Shell 命令 / 提交信息模板 / 超时秒数 / 目标 tmux 会话）；「最近执行」展示该 SPEC 的 hook 审计尾部（时间/动作/结果/耗时/摘要，失败可见错误详情）。事件与动作的完整语义见[配置参考](09-config.md#hooks)。

### 质量门禁 Card

实现完成后的收尾阶段，SPEC 详情页展示「质量门禁」卡片，把收尾链的六道门按固定顺序排列（`core/dashboard/data/quality_gates.py` 的 `GATE_ORDER`）：**full-suite**（全量测试套件）→ **frontend-build**（前端构建）→ **code-review**（代码质量审查）→ **interaction-contract**（交互契约）→ **result-artifact-gate**（结果产物硬门）→ **deliverable-guard**（交付物守卫）。

每道门六种状态：passed / failed / running / skipped / pending / unknown；「done」判定 = passed + skipped。其中三项落盘自 `.fenix/verify-progress/<spec>/quality-gates.json`（嵌套 `{"gates": ...}` 形态是唯一合法写入；平铺旧形态仅容错读取），其余三项由框架合成；非法 JSON 或不可识别的键会落对账告警，展示层用兜底文案而不是空白。

**终态豁免**：SPEC 到达终态后 full-suite 显示 skipped（验证链已收口，不要求补跑）；交互契约门的对比基准等于当前提交（merge_base == head_commit）时豁免。

**列表页联动**：项目列表页的 SPEC 行在两个窗口会显示橙色「门禁」阶段——实现中且任务全勾但尚未了结、或验证中且交互契约审查在跑（`core/dashboard/data/summary.py`）。排查「卡在哪道门」：看详情页卡片中非 passed/skipped 的那一道，再对照验证报告与 run 记录。

**运行记录（时间轴）的可读性**：「运行时间轴」页签对事件流做了降噪与聚合（`core/dashboard/static/src/components/claude-msg/`）：心跳类事件静默不显示；信息类事件渲染成语义系统条——provider 切换显示「模型路由 <model> @ <provider>（第 i/n 棒）」、瞬断重试显示退避提示；同类工具调用聚合为一组；thinking 块折叠（默认不展开，可在输出面板开关）；事件过多时「加载更早事件」向前分页，不做一次性全量渲染。

### 设置页（/settings）

设置页承担配置管理职责。页签按作用域分两层（实读 `core/dashboard/static/src/pages/settings/index.tsx`）：**用户级** 11 个页签——LLM / 智能体（agents）/ 提示词（prompts）/ 并行（parallel）/ Token / 验证（verify）/ 质量（quality）/ 审批（approval）/ 杂项（misc）/ 系统（system）/ 自进化（self-evolution）；选定具体项目后**追加** 3 个项目级页签——自省（self-review）/ 项目（project-profile）/ Hook（hook）。主要能力：分项目读写受管配置键（llm / agents.models / gates.approve_mode）；查看与编辑 verify.yaml 验证契约；查看/调整 token 预算与消耗；以及管理提示词：查看通用层 agents/ 提示词、编辑项目级附加提示词。「Hook」面板管理当前项目的全局 hooks（对所有 SPEC 生效），表单结构同 SPEC 详情页的 Hook 页签，并展示跨 SPEC 的最近执行记录。

「质量」页签（内部 key `quality`，位于「验证」之后）承载代码质量门与周期性审查/回归设置，现状为**两张卡片**（节标题「代码质量」/「回归测试」置于卡片外）+ 页签顶部的 ocr 环境探测提示。第一张「代码质量」卡：单个开关「收尾代码质量审查」（`verify.impl_code_review`，键路径不变）——开启后由框架在该实现 merge-back 成功、tester 派发的同一时点自动启动收尾代码审查（`bin/ocr_review.py`）**异步并行车道**——审查与验证车道并行在飞，不占 agent turn、实现者无需等待，tester 判定 verified 时于 testing 出口 join 裁决；环境未安装 ocr 时自动按 unavailable 降级跳过（该开关原置于「验证」页签，独立成页后验证页不再承载它，避免双入口）。「周期性代码审查」开关（`admin.code_review.enabled`，从项目页「代码审查」分面迁来，项目页分面只保留结果展示与手动触发）**并入同一张卡片**：开启后与每日自省同周期派发 code-review agent 审查产品代码质量，问题入台账供「代码审查」分面消费。第二张「回归测试」卡：开关「周期性全量回归」（`admin.regression.enabled`）：开启后与每日自省同周期自动执行一次全量回归（需项目 `.fenix/verify.yaml` 配置 `regression` 段），结果落到 `.fenix/regression/last-run.json` 供「测试回归」分面展示；同一自然日防重，与 implementer 收尾的全量套件互斥（主机级锁）；手动触发（项目页「立即执行全量回归」）不受本开关约束。长耗时用例阈值来自 `verify.yaml` 的 `regression.long_test_threshold_seconds`（缺省 8 秒），属项目测试体系声明，在项目页「验证」面板的 `verify.yaml` 编辑入口中调整，本卡片不提供第二个写入路径。

开关下方另有三项运行参数设置（add-impl-code-review-tuning，键 `verify.impl_code_review_timeout_sec` / `verify.impl_code_review_concurrency` / `verify.impl_code_review_effort`，缺省 600 / 4 / `low`）：
- **审查超时（秒）**：ocr LLM 单请求超时，写入 run 级 ocr provider 配置（`custom_providers.fenix-impl.timeout_sec`），**确定性生效**——不配置时 ocr 走其内置 300s 默认，实测 8 路并发 + 300s 会撞穿首字节等待导致大面积文件级 timeout。数字输入，须正整数，单位「秒」。
- **审查并发**：ocr 并发子任务上限（`--concurrency`）。实测 8 路并发同时打同一 provider 网关会把首字节延迟放大到撞穿超时线，2 路对大 diff 又明显喂不饱，缺省取 4。数字输入，须正整数。
- **审查力度**：ocr 审查力度预设（`--effort`），下拉 `low` / `medium` / `high`。`low` 更快更省但 recall 偏低（ocr precision 优先的刻意取舍），`medium` 为 ocr 官方默认，`high` 深度审查。

**生效方式**：`--concurrency` 与 `--effort` 均由框架在审查车道启动时**直接注入命令行**（车道命令注入、确定性生效），实现者无需照抄任何命令串；审查超时则写入 run 级配置、同样确定性生效。三项缺省值均比 ocr 官方默认（300s / 8 / `medium`）更保守：宁慢勿废，用户可随时上调。

页签顶部有一行 open-code-review 环境状态（`GET /api/quality/ocr-status`，按 `shutil.which("ocr")` 探测，与 `bin/ocr_review.py` 的 PATH 解析同源）：已安装时显示版本号并放行开关；未安装时显示橙色提示 + 「一键安装」按钮，**开关置灰不可用**（避免开启一个运行期必然降级跳过的开关）。点「一键安装」调用 `POST /api/quality/ocr-install`，后端执行 `npm install -g @alibaba-group/open-code-review`（固定字面量，无用户输入拼接，不做提权）——成功后重新探测并解锁开关，失败（如权限不足 EACCES）返回 400 并把 npm 报错末尾透出，用户可自行 `sudo npm install -g @alibaba-group/open-code-review` 安装后刷新页面。**后端不拦「未安装时保存 `impl_code_review: true`」**：存量已勾选的配置不应因环境探测而保存失败，运行期降级语义保持不变。

「自进化」页签（原「自愈」改名，内部 key `self-evolution`）下自上而下两张卡片，页签内容最下方为**唯一**的右对齐「保存」按钮——点击后一次提交同时写回两节配置（`stale_code_selfheal` + 用户级作用域下的 `self_evolution`）；两张卡片内均不自带保存按钮：
1. **代码陈旧自愈**（既有 `stale_code_selfheal` 面板，配置键/缺省值/控件全部不变）：`enabled` 开关（缺省开启）与 `idle_confirm_seconds` 连续空闲确认秒数（缺省 120），附语义说明——陈旧状态 + 启用 + 托管 + 连续空闲达到阈值后 daemon touch `.fenix/restart_request` 触发优雅重启；未托管项目不自愈、仅维持陈旧告警。保存经页签底部唯一按钮，非法值（非布尔 / 非正整数秒数）被后端拒绝返回可读错误。
2. **建议改进项**（新增 `SuggestedImprovementsPanel`）：标题「建议改进项」位于卡片外（与第一张卡片同构），其下为功能注解；卡片内为全局配置控件——「允许框架自改进」开关（`self_evolution.auto_accept`，缺省关闭，开关与名称同行不换行）与「每轮分析条目上限」数字输入（1..200，缺省 20，独占一行、后缀单位「条」），两者下方各有功能注解。用户级作用域可保存（写用户级配置）；项目级作用域下两项置只读并提示「全局键，请在用户级作用域修改」，此时底部保存按钮仅提交项目级可写的 `stale_code_selfheal`。配置表单之外另有全局动作按钮「清理所有项目自省内容」（实心红底白字告警样式，项目级作用域下禁用）：二次确认后调用 `POST /api/evolution/clear-todo`，把所有已发现项目的 `.fenix/todo.md` 截断为空文件（保留文件本体），只清这一份自省文本——下方条目列表读的是 `items.jsonl`，不受影响；也不代各项目提交 git，清空结果由下一次每日自省一并提交。无 `todo.md` 的项目计入「跳过」，单个项目失败不中断其余，完成后提示「已清空 N / 跳过 M / 失败 K 个」。其下为跨项目建议改进项表格，列序：项目 / 日期 / 类别 / 问题 / 评估结论 / 状态 / 操作，默认按入库时间倒序；状态中文映射：待决策 / 不需要立项 / 草稿生成失败 / 已同意 / 已自动接受 / 已拒绝 / 接受失败。操作列「更多」下拉提供查看分析结论 / 查看 SPEC 草稿 / 同意 / 拒绝（拒绝为危险项），同意与拒绝均需二次确认弹窗；「查看分析结论」在抽屉中渲染评估结论全文（含三项判定与证据）；「查看 SPEC 草稿」可切换 proposal / design / tasks / spec 四类文档。移动端表格横向滚动 + 操作列固定右侧（不做卡片式降级）。

### 运维记录页（/activities）

运维记录页是告警处置的工作台。自动运维视图展示 Administrator 的活动时间线（处置记录与结果标签）；人工告警视图列出未处理的升级告警并提供「标记已处理」操作。页面顶部的横幅汇总跨项目未处理告警总数，每条告警都带有信号类型、严重度、证据与建议。

## 帮助页自身用法

「帮助」菜单（运维之下）进入本文档中心。桌面端左侧是文档目录（选中高亮），右侧为 Markdown 正文；移动端（<768px）正文置顶，通过顶部「文档目录」按钮打开抽屉切换。URL 采用 `#/help?doc=<name>` 形式，可以直链到具体文档，刷新或分享都不会丢失；目录点击与正文内相对链接均可完成页内切换。

## 安全边界

Dashboard 仅绑定 `127.0.0.1`，不对公网开放；同时它没有鉴权机制，因此不要把端口暴露到公网或不可信的内网网络。所有 API 均有防穿越校验与错误容错，不会因异常数据而 500。

## 相关文档

- [帮助中心首页](README.md) — 返回本帮助中心
- [核心概念与架构](02-concepts.md) — 多项目机制
- [配置参考](09-config.md) — Dashboard 设置页与配置键映射
