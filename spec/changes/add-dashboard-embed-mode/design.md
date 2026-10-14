# Design — add-dashboard-embed-mode

## Context

dsh 面板桥（dsh-plugins `add-dsh-dashboard-bridge`，配套 SPEC）把 dashboard v3 以 iframe 嵌进 dsh web 主面板：宿主半在 dsh webserver 注册 `/fenix-dashboard/` 前缀反代（剥离前缀转发 `127.0.0.1:8787`），客户端半以 `<prefix>/?embed=1&apiBase=<prefix>#<route>` 形态深链。dashboard v3 现状：umi max + Ant Design Pro、hash 路由、生产 `publicPath: './'`（静态资源相对引用，前缀挂载天然可用——已核实 `config/config.ts` 与 `routes/static_routes.py` 的根路径回退映射）；API 路径根相对 `'/api/...'`，单点收敛在 `services/dashboard.ts` 的 `request()`（唯一 fetch 位点）与导出常量 `STREAM_URL`（页面 EventSource 共享单源），另一处硬编码在 `ClaudeOutputPane.tsx:342` 自建 `EventSource('/api/stream')`。布局壳为 app.tsx 导出的 `layout: RunTimeLayoutConfig`（line 112）。

前端测试形态：`core/dashboard/static/tests/*.test.mjs`，node 原生 type-stripping 直载 `.ts` 源码 + mock `globalThis.fetch`（`etagCache.test.mjs` 先例），`node --test tests/*.test.mjs` 全量跑。

## Goals / Non-Goals

- Goals：`apiBase` 全局前缀单点；`embed=1` 壳层隐藏；缺省行为逐字节不变；dist 重建回归。
- Non-Goals：后端 Python 改动（零）；主题适配；SPEC 级深链；dsh 侧改动（另一仓库 SPEC）；页面级布局重排。

## Decisions

### D1. 查询参数承载嵌入契约（而不是 base 标签 / 推导）
`apiBase`/`embed` 从 `location.search` 一次性解析（参数位于 hash 前，hash 路由导航不改 search）。不用 `document.baseURI` 推导（今天服务端以根路径挂载、`baseURI` 与 API base 无必然关系，推导是隐式契约）；不用 `<base>` 注入（只影响相对 URL，管不住根相对 `/api/...`）。显式参数零歧义、可测试、缺省即现状。

### D2. 单点收敛于既有 `request()` 封装 + `STREAM_URL` 常量
全部 API 调用已经走 `request()`（唯一 fetch 位点，ETag 缓存/超时/取消分类都在里面），`STREAM_URL` 已是页面 EventSource 共享单源（code-review item ba13417eb1ff 确立的口径）——前缀化只需：`request()` 内 `fetch(withApiBase(path))`、`export const STREAM_URL = withApiBase('/api/stream')`、`ClaudeOutputPane.tsx` 硬编码改引 services 单源。无散弹式改 URL。

### D3. `embedMount.ts` 一个工具模块承载两参数
`withApiBase(path)` / `isEmbedMode()` 同源（同一次 search 解析），模块级惰性缓存 + 测试注入口（node 测试环境无 `location`，沿用 type-stripping 直载 + 先注血后动态 import 的形态）。不拆两个模块（同生命周期、同测试面）。

### D4. 壳层隐藏走 ProLayout 关闭属性
embed 下 `menuRender: false` + `headerRender: false`（ProLayout 标准关闭属性，经 `RunTimeLayoutConfig` 运行时配置下发）；页面自身内容头（PageContainer 面包屑/标题）保留——导航已由 dsh 侧栏承担，全局壳是纯冗余。不 patch 样式、不改 routes 配置（运行时函数内分支即可，非 embed 路径零触碰）。

### D5. dist 声明为 reference（构建产物）
`dist/` 已被 .gitignore 排除（line 31），按不可交付路径规则声明 `reference`（锚点 `dist/index.html`）；实现分支内重建 dist 跑回归（任务 4），部署侧重建随既有流程。

## Risks / Trade-offs

- **[缺省行为回归]** 前缀化改错会打断现有独立访问 → 硬性回归场景「缺省行为逐字节一致」+ 全量前端单测 + dist 重建后手动冒烟；`withApiBase` 缺省恒等返回。
- **[STREAM_URL 常量的求值时机]** 模块级常量在 import 期求值 → 测试以「先注血后动态 import」次序钉住；生产无影响（search 在文档生命周期内不变）。
- **[ProLayout 关闭属性版本差]** `menuRender/headerRender` 是 ProLayout 稳定属性（v7 起在册）；实现期以渲染断言（侧栏/顶栏 DOM 不出现）验证而非只看配置。
- **[iframe 内 SSE 重连风暴]** 面板切换重挂 = 全新启动，无跨重挂的连接复用需求；与 dsh 桥的 keyed 插槽语义对齐（桥 SPEC D8/风险节）。

## Migration Plan

纯前端增量，无数据迁移。上线顺序建议：本 SPEC 先合并（dashboard 支持两参数），dsh 桥 SPEC 后合并启用 iframe 深链——桥在两参数缺失时面板仍可挂载但 API 断（桥 SPEC 验收清单已标注该前置关系）。

## Open Questions

（无——嵌入契约两参数已与桥 SPEC 对端锁定。）
