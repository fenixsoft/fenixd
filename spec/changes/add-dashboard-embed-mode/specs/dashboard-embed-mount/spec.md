## ADDED Requirements

### Requirement: API 前缀单点
dashboard 前端 SHALL 提供唯一的 API 路径前缀化入口：从启动 URL 的 `location.search` 解析 `apiBase` 查询参数（缺省 `''`），全部后端请求路径（`request()` 封装内的 fetch、`STREAM_URL` 常量、组件内自建的 EventSource、服务层构造的下发 URL——如 `architectureDiagramUrl()` 供 iframe `src` 加载的架构图地址）MUST 经该单点拼接。`apiBase` 缺省时拼接结果 MUST 与现状逐字节一致（根相对 `/api/...`）。

#### Scenario: 缺省行为逐字节一致
- **WHEN** 用户直接访问 `http://127.0.0.1:8787/#/overview`（URL 无 `apiBase` 参数）
- **THEN** 页面发出的全部请求 URL 与改造前一致（`/api/overview`、`/api/stream` 等，无前缀），页面功能与改造前无差异

#### Scenario: 前缀化请求
- **WHEN** 页面以 `?apiBase=/fenix-dashboard` 启动
- **THEN** `request()` 封装的全部调用、`STREAM_URL` 的 EventSource 连接均打到 `/fenix-dashboard/api/...`

#### Scenario: 组件内自建流连接同单点
- **WHEN** 以 `?apiBase=/fenix-dashboard` 启动并打开会话输出面板（ClaudeOutputPane）
- **THEN** 其 EventSource 连接地址为 `/fenix-dashboard/api/stream`，不再出现硬编码根路径

#### Scenario: 服务层构造的下发 URL 同单点
- **WHEN** 以 `?apiBase=/fenix-dashboard` 启动并打开项目架构图页签（ArchitectureTab 渲染 iframe）
- **THEN** iframe `src` 为 `/fenix-dashboard/api/architecture/diagram?...`（经同一单点前缀化），架构图正常加载

### Requirement: embed 壳层隐藏
`location.search` 含 `embed=1` 时，运行时布局配置 SHALL 隐藏 ProLayout 全局侧栏与全局顶栏（页面自身内容头/面包屑保留）；无 `embed=1` 时布局 MUST 与现状完全一致。两参数（`embed`/`apiBase`）MUST 可独立生效、可组合。

#### Scenario: embed 隐藏壳层
- **WHEN** 页面以 `?embed=1` 启动并进入概览页
- **THEN** 全局侧栏与全局顶栏不渲染，概览内容区正常渲染且其 SSE 自动刷新持续工作

#### Scenario: 非 embed 布局不变
- **WHEN** 页面不带任何参数启动
- **THEN** 侧栏、顶栏、面包屑与改造前渲染一致

#### Scenario: 参数组合
- **WHEN** 页面以 `?embed=1&apiBase=/fenix-dashboard` 启动
- **THEN** 壳层隐藏且请求走前缀（两者互不干扰）

### Requirement: 嵌入态自动刷新保留
`embed=1` 形态下各页面的 SSE 自动刷新 MUST 与独立访问等价：EventSource 连接建立后事件驱动更新，断线自动重连行为不变（iframe 因面板切换重挂后的重新加载视为全新启动）。

#### Scenario: embed 下 SSE 驱动刷新
- **WHEN** `?embed=1` 打开概览页且上游产生新事件
- **THEN** 页面数据随事件自动更新，无需人工刷新页面

### Requirement: 构建产物可前缀挂载
生产构建产物 SHALL 保持 hash 路由 + 相对资源引用（`publicPath: './'`）形态，使整站可在任意路径前缀下由反代挂载：静态资源请求相对文档 URL 解析。本项为既有形态的回归钉（不改变构建配置）。

#### Scenario: 前缀下资源加载
- **WHEN** 反代把 `/fenix-dashboard/` 映射到 dashboard 服务且产物为当前构建形态
- **THEN** `index.html` 引用的相对资源（`./umi.<hash>.js` 等）全部 200 加载，应用正常启动
