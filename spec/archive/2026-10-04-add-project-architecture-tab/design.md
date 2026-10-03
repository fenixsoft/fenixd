# Design: add-project-architecture-tab

## Context

Dashboard 项目详情页已有 4 个页签（功能开发 / 代码审查 / 测试回归 / 会话接入），页签
以 `<Tabs items={[...]}>` 的内联数组定义在 `core/dashboard/static/src/pages/projects/list.tsx`
（约 1274–1413 行；注意 `tabItems` 命名属 `detail.tsx` 的另一组件，勿混淆），
每个非默认页签由 `components/<X>Tab.tsx` 承载并按 `active` prop 门控请求。页签 key
的权威类型是 `listFilters.ts` 的 `ListTab` 联合类型与 `LIST_TABS` 数组（URL
`?tab=` 选中态按 `LIST_TABS.includes` 校验）。
后端路由走 mixin 形态（`core/dashboard/routes/*_routes.py`，handler 用
`self._json` / `self._error`，在 `server.py` 汇聚）。

daemon 侧已有两套按项目 spawn headless claude 的先例：

- **session_manager.py**：长驻交互式（stream-json），env 构建口径 = `os.environ.copy()`
  剔除 agent-run 专用键（`FENIX_RUN_PROJECT_ROOT` / `FENIX_RUN_WORKTREE` /
  `CLAUDE_CODE_ENABLE_TODO_TOOLS`）；
- **regression_routes.py autodraft**：HTTP 线程内同步 `Popen(["claude","-p",prompt,
  "--permission-mode","bypassPermissions"])` + `start_new_session`（进程组击杀孙进程）+
  `communicate(timeout=900)` + stdout 尾部 marker 判定 + 「权威 = 重新读产物，不信
  claude 自述」。

archify（`npx skills add tt-a1i/archify -g`）是 agent skill：装好后 agent 读仓库即可产出
**自包含交互式 HTML**（内置主题切换 / PNG/SVG 导出），恰好满足「读项目代码 → 高层运行时
架构图」诉求；产物单文件、无外部资源引用，适合后端直接下发 + iframe 沙箱渲染。

用户已定：full 模式、立即执行、**轻量一次性 spawn**（不走框架 agent run / 车道 / 预算）。

## Goals / Non-Goals

**Goals**

- 「项目架构」页签：空态引导 → 手动点击生成 → 轮询进度 → 沙箱渲染 → 可重复刷新。
- 生成完全解耦于开发主链路（无 run 台账、无车道、无预算、无新配置项）。
- 进程与状态治理对齐既有先例（单飞 / 进程组超时杀 / 重启残留合成 / 原子写）。

**Non-Goals**

- 不做架构图历史版本留存（刷新即覆盖旧图，只保留最近一次）。
- 不做自动/定时再生成（纯手动触发）。
- 不新增配置键（超时等用模块常数，对齐 autodraft 先例）——避免触发「新增配置项必须带
  Dashboard 界面」的配套负担。
- 不解析/改写 archify 产物内容（只做存在性、自包含 HTML 特征、组件数三项机械校验）。

## Decisions

### D1. 异步后台线程 + 轮询，而非 autodraft 同步范式

autodraft 在 HTTP 线程内同步等 900s，是「分钟级可预期」任务。archify 全库分析可达
10–30 分钟，同步 HTTP 请求在浏览器休眠 / 代理超时下不可靠（参照 CodeFixProgressCard
切后台冻结、SSE 长连接事故族）。→ `POST refresh` 只受理（起 daemon 守护线程），前端
`generating` 期间 3s 间隔轮询 `GET status`；生成状态经 `status.json` 原子写持久化，
刷新页面/重开标签不丢态。备选「复用 SessionManager 交互式会话」被否：会话是长驻共享
进程（复用存活实例），与「一次性任务、单飞、超时杀」语义不合。

### D2. 产物存储 `.fenix/architecture/{diagram.html, status.json}`

项目根 `.fenix/` 已是既定运行时目录族（regression_request.json 等同族），gitignored、
不进交付物。`status.json` 结构：`{state, generated_at, started_at, error, duration_ms,
component_count}`，每次状态迁移 tmp+rename 原子写。dashboard 进程内
`ArchitectureManager` 持单飞锁与在飞进程句柄，为唯一写者（单写者原则）。

### D3. spawn 形态与 env

`Popen(["claude","-p",prompt,"--permission-mode","bypassPermissions"], cwd=项目根,
start_new_session=True)`，`communicate(timeout=GEN_TIMEOUT_SECONDS=1800)`，超时
`os.killpg` 整组击杀（autodraft 同款，防孙进程残留）。env = `os.environ.copy()` 剔除
session_manager 同款三键。daemon 进程内后台线程跑，不占 HTTP 线程。

### D4. archify skill 检测与自动安装

探测顺序：`$CLAUDE_CONFIG_DIR/skills/archify/SKILL.md` → `~/.claude/skills/archify/
SKILL.md`（settings env 可能覆盖 CLAUDE_CONFIG_DIR，两处都查）。缺失 →
`subprocess.run(["npx","skills","add","tt-a1i/archify","-g"], timeout=120)`；失败/超时
→ `failed`，error 文案原样携带 `npx skills add tt-a1i/archify -g`。安装命令在后台
线程执行，同样不阻塞 HTTP。

### D5. 提示词契约与产物机械校验

提示词（中文）固定五项形态约束 + 输出路径 + marker 协议（stdout 末行
`ARCHIFY_DONE <组件数>`，autodraft marker 范式）。判定权威链：进程退出码 → 产物文件
存在且非空 → 起始 `<html`/`<!DOCTYPE html` 特征 → 从 marker/产物提取组件数 ∈ [8,16]。
任一环不满足即 `failed`，不信 claude 自述。组件数提取失败（marker 缺失）时不硬判
failed，记 `component_count: null` 并放行（形态校验尽力而为，产物可用性优先）——
与 spec「越界必判 failed」不冲突：**能提取**才校验范围。

### D6. 前端渲染与移动端

`<iframe src="/api/architecture/diagram?project=…" sandbox="allow-scripts">`，不给
`allow-same-origin`（生成产物脚本与主站隔离）。容器用显式 flex 布局定高
（`height: calc(100vh - <头部实测偏移>px)`，minHeight 兜底，参照 SessionPanel 先例），
避免移动端越界（改布局不改宽度定调）。useIsMobile 下高度公式换移动档常数。

### D7. 路由与文件清单

新 mixin `H13ArchitectureRoutesMixin`（`routes/architecture_routes.py`），`server.py`
继承链追加（H12 已被 `H12RegressionRoutesMixin` 占用，按序取 H13）。单测：`tests/test_dashboard_architecture_api.py`（fake Popen 按 `cmd[0]`
分发 + 布防门控，对齐测试隔离双陷阱先例；覆盖单飞 409 / 超时杀 / 重启残留合成 /
产物校验 / 安装失败路径）。前端逻辑薄（轮询 + 四态渲染），不设独立 .test.mjs，
由后端单测 + 构建冒烟覆盖。

## Risks / Trade-offs

- [archify 产物含 JS，渲染面等于执行第三方模板代码] → iframe sandbox 无
  allow-same-origin，产物与主站 cookie/DOM 隔离；产物仅本项目代码分析结果。
- [npx 安装依赖外网可达性] → 120s 限时 + 失败文案给人工命令；服务器已有代理配置。
- [claude 分析大库烧 token（单次估计 $0.5–3）] → 手动触发天然节流 + 单飞 + 1800s
  上限；无自动再生成通道。
- [组件数机械校验依赖 marker 自觉] → marker 缺失时降级放行（D5），不为校验牺牲可用性。
- [daemon 重启杀在飞生成] → status.json 残留 generating 由读侧合成 failed，按钮即可
  重试，无死态。

## Migration Plan

纯增量：新路由 mixin、新前端组件、list.tsx 插一项。无数据迁移；`.fenix/architecture/`
首次生成时按需创建。回滚 = 还原三个接线点即可。后端改动需 daemon 重启生效（既有约定）。

## Open Questions

无（执行模式 full / 立即执行 / 轻量 spawn 三决策已由用户确认）。
