## MODIFIED Requirements

### Requirement: embed 壳层隐藏
`location.search` 含 `embed=1` 时，运行时布局配置 SHALL 隐藏 ProLayout 全局侧栏与全局顶栏，并由统一标题栏控件（unified-page-title-bar）自动渲染内容区首行标题栏（48px，承载标题/副标题/过滤项，页面无需逐页声明壳位分支）；无 `embed=1` 时布局与独立访问形态一致。两参数（`embed`/`apiBase`）MUST 可独立生效、可组合。（原条款「页面自身内容头/面包屑保留」随 unified-page-title-bar 退役：PageContainer 页头全站摘除、面包屑全局移除，嵌入态页面标识由统一标题行承担。）

#### Scenario: embed 隐藏壳层
- **WHEN** 页面以 `?embed=1` 启动并进入概览页
- **THEN** 全局侧栏与全局顶栏不渲染，内容区首行为统一标题栏（「跨项目概览」+ 副标题随迁），概览内容正常渲染且其 SSE 自动刷新持续工作

#### Scenario: 非 embed 布局不变
- **WHEN** 页面不带任何参数启动
- **THEN** 侧栏、顶栏（含标题栏控件与右上过滤项）与独立访问形态渲染一致

#### Scenario: 参数组合
- **WHEN** 页面以 `?embed=1&apiBase=/fenix-dashboard` 启动
- **THEN** 壳层隐藏且请求走前缀（两者互不干扰），标题行正常承载
