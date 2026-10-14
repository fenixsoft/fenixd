## Why

Fenix Dashboard v3 即将被 dsh web 面板桥（dsh-plugins 仓库 SPEC `add-dsh-dashboard-bridge`）以 iframe 嵌入 dsh web 主面板，挂载形态为「dsh web 同源前缀代理 + hash 深链」。现状两处不兼容：① 全局 API 路径是根相对（`/api/...`），经前缀代理后会打到 dsh web 自身的 `/api` bridge 而断链；② dashboard 自带完整侧栏 + 顶栏，嵌进面板会出现双重菜单挤占空间。需要 dashboard 支持嵌入挂载形态。

## What Changes

- 新增 `src/utils/embedMount.ts`：启动参数单点——从 `location.search` 一次性解析 `apiBase`（默认 `''`，行为与现状逐字节一致）与 `embed=1` 两参数；导出 `withApiBase(path)`（API/流路径前缀化）、`isEmbedMode()`，附测试注入口。
- `services/dashboard.ts`：`request()` 内 fetch 路径与导出常量 `STREAM_URL` 统一经 `withApiBase()` 前缀化（全部 `/api/...` 字面量收敛过单点）；`ClaudeOutputPane.tsx` 自建的 `EventSource('/api/stream')` 硬编码同改（改用 services 单源常量）。
- `app.tsx`：`embed=1` 时运行时布局配置隐藏 ProLayout 全局侧栏与全局顶栏（页面自身内容头保留）；无参数时行为与现状完全一致。
- dist 重建 + 前端全量回归（`node --test tests/*.test.mjs`）。
- 非目标：不做主题适配、不做 SPEC 级深链、不改后端 `core/dashboard/`（Python 侧零改动）、不改 dsh 侧（另一仓库 SPEC）。

## Capabilities

### New Capabilities

- `dashboard-embed-mount`: dashboard v3 嵌入挂载支持——`apiBase` API 前缀单点与 `embed=1` 壳层隐藏形态；两参数缺省时行为与现状完全一致

### Modified Capabilities

（无——dashboard v3 前端此前无既有能力 spec；本 SPEC 为其首个能力条目。）

## Impact

- 前端改动收敛于 `core/dashboard/static/src/`（utils 新增 + services/app/claude-msg 三处修改）+ `tests/` 新增；后端 Python 零改动。
- 直接调用方：dsh 面板桥（iframe src 携带两参数）；现有独立访问（daemon `:8787` 直开）不带参数——缺省行为不变是硬性回归项。
- 风界面：无参数场景 UI 零变化；`embed=1` 场景仅 dsh 面板 iframe 内可见。
- dist 为构建产物（gitignored），由本 SPEC 任务在实现分支重建并跑回归；部署侧重建随框架既有发布流程。
