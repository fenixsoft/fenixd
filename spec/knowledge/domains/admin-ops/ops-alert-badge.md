# 运维菜单告警徽标

<!-- knowledge: capability=ops-alert-badge rev=1
     sources=spec/changes/consolidate-alerts-to-ops-page -->

侧栏「运维」菜单项上的红点数字徽标：让用户不进运维页也能看到当前有多少告警等待人工裁决，是告警消费面（运维页告警记录页签之外）的唯一常驻提示位。

## 规则

- **常驻性**：徽标随壳级侧栏「运维」菜单项常驻展示，不依赖概览页或运维页处于激活态；刷新管线属壳级挂载，不随任何页面卸载。
- **计数口径**：未处理（未标记已处理、未 superseded 失效）且携带非空裁决 `choices` 的告警条数；知情类告警（choices 缺省或空数组）与已处理/已失效告警 MUST NOT 计入。计数归零徽标隐匿（不显示「0」），超 99 显示「99+」。
- **数据源单源**：复用 `GET /api/alerts` 跨项目聚合口径（含夹具告警过滤），客户端按「choices 非空」过滤计数，与运维页告警列表天然同源，不设独立徽标端点；不消费 `total_unhandled`（该口径含知情类，与徽标语义不符）。
- **刷新管线**：SSE `alerts`/`admin_activities` 事件驱动、合帧 500ms 防抖；SSE 永久断连降级 30s 周期轮询（连接恢复回到事件驱动）；页面不可见时暂停、恢复可见时补拉一次；拉取失败保留上次计数，序号守卫防过期响应覆写。
- **嵌入态豁免**：`embed=1`（menuRender 关闭，无侧栏）时徽标组件不挂载，hook 不运行，零请求零 SSE 连接，MUST NOT 产生报错或控制台异常。

## 代码锚点

- 主实现：`core/dashboard/static/src/hooks/useOpsAlertBadge.ts`（计数过滤 + SSE 合帧/降级轮询/可见性门控/序号守卫）
- 消费方：`core/dashboard/static/src/app.tsx`（`OpsMenuName` 组件包 antd `Badge size="small" overflowCount={99}` 挂运维菜单项 name；菜单 name 为独立组件节点，menuDataRender 数据回调内不得调 hook）
- 数据源：`core/dashboard/routes/alert_routes.py`（GET /api/alerts 聚合读出口）
- 守卫：徽标场景由 web 验证场景体系承载（计数口径/归零隐匿/嵌入态豁免）；dist 构建产物断言含运维菜单名与 overflowCount=99

## 溯源

- 2026-11-12 consolidate-alerts-to-ops-page（spec/changes/consolidate-alerts-to-ops-page/） — 新增本能力：红点数字徽标计数口径（未处理且 choices 非空；知情/已处理/失效不计、归零隐匿、99+ 封顶）、复用 GET /api/alerts 客户端计数不新增端点、壳级刷新管线（SSE 合帧+断连降级轮询+可见性门控）与 embed 豁免
