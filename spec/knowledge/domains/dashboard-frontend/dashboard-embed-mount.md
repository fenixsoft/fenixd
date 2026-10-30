# dashboard 嵌入挂载

<!-- knowledge: capability=dashboard-embed-mount rev=1
     sources=spec/archive/2026-10-30-add-dashboard-embed-mode -->

dashboard v3 被外部宿主（dsh web 面板桥 iframe）以「同源前缀代理 + hash 深链」嵌入的挂载支持：API 前缀单点与壳层隐藏两参数，缺省时行为与独立访问逐字节一致。

## 规则

- **API 前缀单点**：前端从启动 URL 的 `location.search` 解析 `apiBase` 查询参数（缺省 `''`）；全部后端请求路径——`request()` 封装内的 fetch、`STREAM_URL` 常量、组件内自建的 EventSource（如会话输出面板）、服务层构造的下发 URL（如 `architectureDiagramUrl()` 供 iframe `src` 加载的架构图地址）——MUST 经该唯一单点拼接，无散弹式改 URL。`apiBase` 缺省时拼接结果与根相对 `/api/...` 形态逐字节一致。
- **embed 壳层隐藏**：`location.search` 含 `embed=1` 时，运行时布局配置隐藏 ProLayout 全局侧栏与全局顶栏（经 `menuRender: false` + `headerRender: false` 标准关闭属性下发），页面自身内容头/面包屑保留；无 `embed=1` 时布局与现状完全一致（非 embed 路径零触碰，不 patch 样式、不改 routes 配置）。`embed`/`apiBase` 两参数独立生效、可组合。
- **嵌入态自动刷新保留**：`embed=1` 形态下各页面 SSE 自动刷新与独立访问等价——EventSource 连接后事件驱动更新、断线自动重连行为不变；iframe 因面板切换重挂后的重新加载视为全新启动，无跨重挂连接复用需求。
- **构建产物可前缀挂载**：生产构建保持 hash 路由 + 相对资源引用（`publicPath: './'`）形态，整站可在任意路径前缀由反代挂载（静态资源相对文档 URL 解析）——既有形态的回归钉，不改变构建配置。
- **参数承载契约**：嵌入契约由查询参数显式承载（参数位于 hash 前，hash 路由导航不改 search）；不用 `document.baseURI` 推导（与服务端挂载路径无必然关系）、不用 `<base>` 注入（管不住根相对 `/api/...`）——显式参数零歧义、可测试、缺省即现状。

## 关键行为

对端消费：dsh 面板桥（dsh-plugins 仓 SPEC）以 `<prefix>/?embed=1&apiBase=<prefix>#<route>` 形态深链 iframe；两参数缺失时面板仍可挂载但 API 断链——本能力先行合并是桥启用的前置。独立访问（daemon `:8787` 直开）不带参数，缺省行为不变是硬性回归项。

## 溯源

- 2026-10-30 add-dashboard-embed-mode（spec/archive/2026-10-30-add-dashboard-embed-mode） — 新增本能力：apiBase 全局前缀单点（fetch/流/自建 EventSource/架构图下发 URL 四路收敛）、embed=1 壳层隐藏、嵌入态 SSE 等价、hash 路由+相对引用回归钉
