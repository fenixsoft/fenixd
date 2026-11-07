# v2 运维页（/v2/activities）

<!-- knowledge: capability=v2-ops-page rev=1
     sources=spec/changes/redesign-dashboard-v2-ui,spec/changes/redesign-dashboard-v2-ui-mobile,spec/knowledge/_inbox/done/ops-mobile-nested-bento-removal.md -->

v2 商业化域六页中的运维观测页：处置链观测、自动运维记录与告警记录三页签的页面级形态与数据规则（域级条款见 `v2-commercial-ui`，页签与数据口径与原版运维页 `v3-activities-page` 同构）。

## 规则

- **页签与预选**：三页签 处置链（缺省）/ 自动运维记录 / 告警记录；URL `?tab=` 仅认 `auto`/`alert` 预选，非法值或缺省一律落处置链。
- **标题栏声明**：经 `<V2Page titleBar>` 槽位进统一标题栏——`subtitle` 承载五项统计（待处理告警/在飞链/人工队列/升级中/配额耗尽，链聚合数值取 `summary ?? total`）；处置链页签激活时 `filters` 槽渲染「全部项目」单项目聚合 Select，state 提升宿主页、页签切换后筛选保持。副标题统计移动端不渲染（统一标题栏移动语义：副标题与返回箭头移动端均隐藏，见 `unified-page-title-bar`），移动端标题即设备顶栏。
- **处置链页签**：四块观测按序 在飞链/签名配额/人工队列/升级件（与原版同序）；链数据 fail-soft——刷新失败保留上一帧仅置错误横幅，不与告警/运维记录的加载失败混报。
- **自动运维记录页签**：消费真实端点 `/api/admin-activities`，服务端分页 15/页（与原版 PAGE_SIZE 同语义）；总条数收缩致当前页越界时回退第 1 页重拉；条目行「查看处置过程」开 AdminRunModal（原版同源组件）；无叙述总结的条目以「处置：… · 结果：…」如实占位，不伪装叙述。
- **告警记录页签**：未处理行复用 V2AlertRows（裁决选择题 Select + 执行 / 无选择题「标记已处理」，处置附注 Popover）；已解决条目折叠区默认展开、可收起。
- **加载失败隔离**：告警与运维记录两路 `Promise.allSettled` 双 settle，失败横幅按来源区分文案、一路失败不拖垮另一路渲染；三路数据同走心跳轮询。
- **移动端形态（<768px，UI 真相源为 m-ops.html 2026-11-07 r2 重绘版）**：标题入设备顶栏（副标题统计与返回箭头移动端不渲染）；处置链四块观测表转堆叠行卡（多列观测表窄屏无收缩点，越界治理布局优先）；告警记录 pane 解除嵌套白磁贴、未处理行直接呈现（锚 `ops-alert-list` 保留在裸容器上）；自动运维记录 pane 无嵌套磁贴、行直接呈现。去卡不改行分隔线色档——告警行仍 `V2_SPLIT`、记录行仍 `V2_HAIRLINE`；共用告警行（V2AlertRow）行内边距保持 `10px 2px` 不动，去卡收益来自解除外层磁贴而非改行距。
- **共用组件 prop 分支纪律**：V2AlertRow 为本页告警 pane 与 overview 告警横幅磁贴共用行渲染——本页去卡以 pane 级 `mobile` prop 分支承载，MUST NOT 全局平移共用组件形态，overview 侧零变化。

## 溯源

- 2026-11-05 redesign-dashboard-v2-ui（spec/changes/redesign-dashboard-v2-ui/） — 新建 v2 运维页桌面形态（Bento 壳，原型 ops.html 定源；自愈记录分面彼时为占位态）
- 2026-11-06 交互会话用户指令「页签与原版一致、数据正确加载」（未走 SPEC） — 页签与数据对齐原版三页签：处置链缺省与 `?tab=` 预选语义、自动运维记录转真实端点服务端分页（自愈记录占位页签退役）、处置链四块观测对齐原版并补齐人工队列块
- 2026-11-07 ops-mobile-nested-bento-removal（spec/knowledge/_inbox/done/ops-mobile-nested-bento-removal.md） — 新建本页承载页面级规则；m-ops.html 对齐现产重绘（r2）定为移动端 UI 真相源，移动端去嵌套磁贴直接行呈现、分隔线保色与 V2AlertRow prop 分支纪律成文
