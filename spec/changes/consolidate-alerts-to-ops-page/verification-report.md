# Verification Report — consolidate-alerts-to-ops-page

- 日期：2026-11-12
- 分支：`fenix/consolidate-alerts-to-ops-page-1794445489`（implementer worktree）
- 验证人：implementer run（本报告为 tasks.md 5.2 交付物）
- 范围：叙事生成链写侧退役 + 读侧收缩保留 + 概览告警面退役 + 运维徽标 + 清理入口迁移

## 1. 徽标计数口径（tasks 4.1/4.2）

- 计数实现（`core/dashboard/static/src/hooks/useOpsAlertBadge.ts`）：`count = (d.alerts || []).filter(a => Array.isArray(a.choices) && a.choices.length > 0).length`——**choices 非空的可裁决告警计入；知情类（choices 缺省或空数组）不计**。计数源用 `getAlerts()` 全量 alerts，不用 `total_unhandled`（含知情类，与口径不符）。
- 数据面驱动：SSE（`STREAM_URL`）`alerts`/`admin_activities` 事件合帧 500ms（TICK_COALESCE_MS）；永久断连降级 30s 轮询（FALLBACK_POLL_MS，onerror 启动 / onopen 停止）；visibilitychange 门控（隐藏暂停、恢复补拉+补启降级轮询）；卸载全量清理；`loadSeqRef` 序号守卫防过期响应覆写计数；拉取失败保留上次计数。
- 呈现：`app.tsx` `OpsMenuName` 组件包 antd `<Badge size="small" overflowCount={99}>`——**>99 显示 99+**；徽标挂「运维」菜单项。菜单 name 为独立组件节点（menuDataRender 是数据回调不能调 hook）；**embed=1（menuRender:false）时组件不挂载 → hook 不运行，零请求零 SSE 连接**。
- 证据：dist umi 主包含「运维」菜单名与 `overflowCount:99`（构建产物断言）；计数口径语义由源码 filter 表达。design D5 的前端 web E2E 场景（徽标出现/计数口径/清理入口）随验证阶段由验证车道冻结并回归——实现侧以构建产物断言 + 源码语义承载。

## 2. 概览页无告警面（tasks 4.3）

- `overview/components/AlertBanner.tsx` 已删除（components 目录仅存 IntroduceRow/ProjectTable）；`overview/index.tsx` 摘除 `<AlertBanner refreshTick>`、SSE 告警订阅、合帧句柄、降级轮询定时器与标记已处理管线；`getOverview` 30s 心跳 + visibilitychange 门控 + `loadSeqRef` 保留（注释注明告警感知面收敛到运维徽标+运维页）。
- 守卫断言（实现侧复核）：`grep "getAlerts|clearAllAlerts|STREAM_URL|AlertBanner"` 于 overview/index.tsx 与 components/*.tsx **零命中**；全仓 grep 无 AlertBanner 组件引用残留（仅历史溯源注释已改写）。
- 样式面（global.less）：`.ant-alert-banner` 窄屏样式块删除；`.alert-adjudication-row/select/input/desc` 与 `.alert-resolve-msg` 五选择器经 grep 全 src 证实消费者仅为已删的 AlertBanner（现役裁决控件走 `useAlertAdjudication` 共享 hook 形态，类名不同），随横幅一并退役；`alert-adjudication-*` 溯源注释同步改写。`spec-detail-alert`（detail.tsx :1653 在用）保留。
- 构建产物断言：overview chunk 无告警横幅订阅面（bundle 重组后该页仅剩心跳/台账管线）。

## 3. 清理入口两形态可用（tasks 5.1）

- **桌面**：`activities/index.tsx` AlertPanel 顶部操作栏（`justifyContent: flex-end` 行）根因筛选右侧 danger 按钮「清理所有事件」（`data-testid="alert-clear-all"`）。
- **移动**：MobileAlertPane 工具行（`space-between` 两端布局）同款按钮，与根因筛选同行两端。
- 确认弹窗文案**逐字沿用横幅现文案**：title「清理所有事件」；正文「确认清理全部项目的 N 条未处理告警？」+「该操作会把所有项目的未处理告警标记为已处理，且不可撤销；标记后 AdminMonitor 不会对同一告警重新升级，请确认已逐条知悉。」；`okText: '全部清理'` + `okButtonProps: { danger: true }` + `cancelText: '取消'`；`whiteSpace: pre-wrap` 同款。**N 取 `alertsData.total_unhandled`**（后端全量口径，不做可见列表钳制——item b278f6e832bf：如实呈现影响范围）。
- 执行链：`clearAllAlerts()` → 成功 `message.success('已清理所有事件')` / 失败 `message.error('清理失败：…')` → `onResolved()`（宿主页 `load()` 刷新）。message/modal 经 `App.useApp()` 取上下文（SystemPanel 同口径，静态方法不经 ConfigProvider）。
- 后端端点不变：`POST /api/alerts/clear`（`core/dashboard/routes/base.py:725` 注册），端点测试 `tests/test_admin.py:2524`（跨项目一次性清理）在全量回归覆盖内。
- 构建产物断言：activities chunk 含 `alert-clear-all` testid 与按钮/弹窗 title/成功 message 三处文案（minified dist 中文为大写 Unicode 转义，按转义字面匹配命中）。

## 4. 退役后写告警零 LLM 调用零新侧车（tasks 1.x）

- 模块级根除：`core/adjudication_narrative.py`（64KB 生成链：证据采集/prompt/熔断器/后台线程/schedule_narrative）与 `tests/test_adjudication_narrative.py` 整文件删除——任何残留 import 即 ModuleNotFoundError，全仓测试收集零断链。
- 让位判定迁移：`narrative_yielded_to_arbiter` 语义逐字迁至 `core/pm_engine/family.py` `yielded_to_arbiter`（去前缀）；判定矩阵收敛——链头派发可用∧非黑名单 → `True`（arbiter 接管）；无链/enabled=false/黑名单/project_root 缺席/判定异常 → `False` 且**零后台派发**（仅 WARNING，fail-open 不回落 narrative 路径）。
- 旁路发射拆除：mergeback（`G4MergebackMixin`）与 token_budget（`TokenAccountant`）告警发射点零叙事 attach；`token_budget.py` 锁区注释改写消除过时机制描述。
- 契约测试（`tests/test_alert_background_dispatch.py`，新建四块）：迁移判定矩阵全形态；**咽喉零后台派发以 `subprocess.Popen` canary 断言（任何 LLM 子进程调用即测试失败）**；旁路发射零侧车零 attach（mergeback/token_budget 双发射点）；新告警无 narrative 字段、无新侧车目录、读侧无 narrative_pending、级联删除契约保持。
- 保留面回归：`tests/test_narrative_sidecar.py` 重写（读侧合并 8 例/级联删除 3 例/原子写 2 例，生成类用例移除）；`tests/test_arbiter_guardrails.py`（`yielded_to_arbiter` 隔离 + 冻结告警路径 `load_narrative_sidecars == {}` 零侧车断言 + arbiter 报告侧车 model=arbiter 保留）；`tests/test_escalation_chain.py` 降级告警路径 parity 改断零后台派发。

## 5. 存量 config 残留键容忍（tasks 2.1）

- 三键（`narrative_enabled`/`narrative_timeout_seconds`/`narrative_model`）自 `core/config.py` 与 `config_admin.py` 全部登记面移除：`_SOURCE_KEYS`/`_ADMIN_DEFAULTS`/`_ADMIN_RANGE_MIN`/`_managed_admin_keys`/`_SYNC_PAGE_KEYS`/`_ADMIN_VALIDATORS` 六处清空，`DEFAULT_TIMEOUT_SECONDS` 延迟 import 消除（回退值 180 就地内联）。
- 容忍测试（`tests/test_system_settings_config.py` 新增）：`test_read_config_tolerates_legacy_narrative_keys`（raw config 携带 narrative_* → 解析不报错、不回显）；`test_config_loader_admin_tolerates_legacy_narrative_keys`（`ConfigLoader.get_admin_config` 残留键忽略、缺省补齐）。等值断言与键集断言同步去三键并附防回潮注释。
- 前端类型同步：`services/dashboard.ts` AdminConfig 三字段删除（AlertItem.narrative 与收件箱 narrative 条件携带保留——服务历史侧车与 arbiter 报告）。

## 6. 既有告警/裁决/收件箱回归（tasks 3.x + 5.2）

- 后端相关子集（19 文件直接变更面+邻接面）：**479 passed，34.5s**——test_narrative_sidecar / test_alert_background_dispatch / test_arbiter_guardrails / test_escalation_chain / test_system_settings_config / test_arbiter_lane(+resilience) / test_harness_one_shot_forms / test_killpg_self_guard / test_admin_dispatch_escalation / test_alert_lifecycle / test_alert_self_heal / test_alert_supersede / test_arbiter_backlog_sweep / test_command_center_aggregation / test_timeline_arbiter_visibility / test_inconclusive_loop_escalation / test_quality_gates_soft_alert。
- 全量回归：`python3 bin/run_full_suite.py --timeout 3600 --json` → **rc=0，current_failures=[]（零失败），elapsed=750.1s，timed_out=False，hanging_test=nil**（汇总输出见 `.history/full-suite-out.txt`）。既有环境性恒失败项（daemon 占 1900x 端口的 test_v2_dev_server 3 例）本轮未出现。
- 前端构建：`npm run build`（max build）rc=0，dist 产物断言见上文 §1/§2/§3；tsc --noEmit 41 例全为 `src/.umi` 代码生成缺失类环境噪音（@umijs/max 导出/PNG 声明/连锁隐式 any，波及未改动文件），非本任务引入，max build（babel 转译、不做全量类型门）通过。
- 读侧收缩回归：admin_alerts 读侧合并保留 + narrative_pending 派生移除（test_narrative_sidecar 读侧组）；command_center 收件箱定形（test_command_center_aggregation）；前端 `alert-shared.tsx` AlertNarrativePending 组件删除、hasNarrativeReport/AlertReportButton/正文渲染保留。

## Acceptance Deviations

1. **`.fenix/config.template.yaml` 交付形态偏差（reference → modify）**
   - tasks.md deliverable 表（:55-56）与 2.2 称该文件为「gitignored 运行时文件（SPEC 不可交付），由人工在主树清理」。核实为**前提错误**：`.gitignore:36` 白名单 `!.fenix/config.template.yaml` 显式放行，文件被 git 跟踪且有提交史（c679dfc44 等）。
   - `proposal.md:33` Impact 明确将其列为变更面（「core/config.py + .fenix/config.template.yaml（三键退役）」）。
   - 处置：按 proposal 在实现分支直接清理——:447-464 叙事注释段与三键删除、:622 链关闭态文案改写（「既有人工直达路径…叙事生成链已退役」），YAML safe_load 验证通过，随 merge-back 进主树。人工项被自动化吸收，内容零缺口；kind 登记与实际交付不符之处以本条登记备审计。
2. **`docs/help/09-config.md`「移除三键文档段」为 no-op，改为最小真实注记**
   - tasks.md 2.2 前半句要求移除三键文档段，但该文件从未收录三键（grep `narrative` 全文零命中；admin 键以「设置页系统页签可编辑五项」prose 表达，本无 narrative 项）——移除动作无对象。
   - deliverable 表 kind: modify 要求真 diff。处置：在 admin 键段落补「退役注记」一条（三键退役 + 存量 config 残留键被 loader 忽略的兼容指引，交叉引用 06-governance.md）——履行文档面退役告知义务与「既有用户配置兼容」impact 告知，非凑数 diff。
3. **design D5 前端 web E2E 场景职责归属**
   - tasks.md 5.2「徽标与清理入口的前端 web 验证场景随验证阶段冻结并回归（design D5）」——场景冻结与浏览器回归属框架验证车道职责（update_spec 直达 implemented 后由 verifier 出题），非实现者交付物。实现侧已以源码语义 + dist 构建产物断言（徽标 overflowCount/清理入口 testid 与文案）承载可验证性，供验证车道冻结场景时引用。

## 知识投递

退役结论已投递 `spec/knowledge/_inbox/alert-narrative-generation-chain-retired.md`（背景/结论当前事实/证据三段）。
