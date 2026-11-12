# 项目详情页签

<!-- knowledge: capability=project-page-tabs rev=6
     sources=spec/archive/2026-09-23-add-project-detail-tabs,spec/archive/2026-09-24-add-code-review-agent-and-quality-tab,spec/archive/2026-09-26-add-spec-list-filter-stickiness,spec/changes/add-project-home-tab,spec/knowledge/_inbox/done/quality-tab-body-padding-align-dev-tab.md -->

项目页（`/projects/:name`）的分面导航容器：项目首页/功能开发/代码审查/测试回归/架构蓝图/项目知识六分面与按需加载门控。

## 规则

- 项目页在项目名称下方渲染 `Tabs` 分面导航容器，分面组成为「项目首页」「功能开发」「代码审查」「测试回归」「架构蓝图」「项目知识」六个分面（顺序固定，「项目首页」居首位）；默认选中仍为「功能开发」——「项目首页」仅占据菜单位，不改变默认选中分面；Tabs 容器在桌面与移动端两种视口下均渲染。
- 页签选中态持久化到 URL 查询参数 `tab`（合法值 `home`/`dev`/`quality`/`regression`/`architecture`/`knowledge`，缺省 `dev` 且缺省不写参——选中态为缺省值时 URL 无 `tab` 参数）；写入采用 replace 语义，不为切换操作新增浏览器历史条目；刷新页面后恢复刷新前选中分面，URL 无 `tab` 参数时回到「功能开发」。`tab=home` 时浏览位置由 `path` 参数持久化（语义由 `project-home-tab` 能力承载，`tab≠home` 时 `path` 不出现）。
- 页签切换原地切换内容：不整页刷新、路由路径保持 `/projects/:name` 不变。
- 「功能开发」分面承载既有项目 SPEC 列表及其全部能力——搜索框、状态/类型/归档筛选、桌面表格与移动端卡片、行操作菜单、文档弹窗等，行为与「项目首页」分面引入前保持一致（零回归）。
- 「代码审查」分面承载当前代码仓的 code-review 质量视图——问题台账表格、手动触发审查按钮、真实进度条与取消、生成修复 SPEC 入口；内容由 `code-review-quality-tab` 能力的 `QualityTab` 承载，数据经 `GET /api/code-review/items` 拉取并随 SSE/心跳兜底刷新。
- 按需加载门控：各分面仅在自身被选中时拉取数据与订阅事件——未选中「代码审查」不拉取 `/api/code-review/items` 或订阅质量事件（避免项目页首屏无谓请求与订阅泄漏），未选中「项目首页」不请求 project-files API；切离分面时释放该分面持有的事件订阅、在飞请求结果静默丢弃。
- 分面包裹卡与卡体内边距对齐：六分面各分面自带包裹卡（非共享单卡），分面顶层卡体在桌面视口的 body 内边距统一 8px 档——「功能开发」卡挂 `projects-page` 类，经 `global.less` 的 `#root .projects-page > .ant-card-body { padding: 8px }` 生效；「代码审查」「测试回归」「架构蓝图」「项目知识」四分面顶层卡经共享助手 `facetCardStyles(isMobile)` 落同档（padding 以单边键展开为 8）。助手 `extraBody` 参数供分面在 8px 档上追加/覆盖单边内边距（项目知识总目录视图以 `paddingTop: 0` 顶贴分面导航），移动端同样生效。
- antd v6 css-var 模式缩写陷阱：`styles.body` 只传纯数字 `padding: 8` 缩写会被 antd 样式合并改写（padding-top 被缺省 24px 顶回），分面卡体内边距 MUST 以单边键（paddingTop/paddingRight/paddingBottom/paddingLeft）展开传递。
- 移动端耦合红线：`facetWrap` 对「功能开发」以外分面套 `margin: 0 -20px` 负边距抵消，该口径按 antd 缺省 24px 卡体调校（抵后余 4 + 内容容器 12 = 每侧 16px 视觉边距）；分面卡体内边距与 facetWrap 负边距是一对耦合参数，改其一必须同步校核另一。移动端分面卡体保持 antd 缺省 24px 不收窄（`facetCardStyles` 移动档返回 undefined 或仅 extraBody），桌面收窄 MUST 以 `isMobile` 分档豁免移动端，否则两侧压穿、内容贴屏幕缘。
- 几何验证锚点：桌面（1440 视口）任意两分面卡体 contentLeft/contentTop 应相等（分面对齐判据）；移动端（390 视口）分面卡 cardLeft=-8、wrapMargin=-20px、卡体 24px 为不变基线。

## 代码锚点

- 主实现：`core/dashboard/static/src/pages/projects/components/facetCardStyles.ts`（四分面卡体 8px 档单源助手）
- 消费方：`core/dashboard/static/src/pages/projects/list.tsx`（facetWrap 移动端负边距与 DevTab 卡 projects-page 类）；`core/dashboard/static/src/pages/projects/components/QualityTab.tsx`、`RegressionTab.tsx`、`ArchitectureTab.tsx`、`KnowledgeTab.tsx`
- 守卫测试：`core/dashboard/static/tests/pageChrome.test.mjs`（projects-page 8px 规则与 DevTab 卡类钉行）

## 溯源

- 2026-09-23 add-project-detail-tabs（spec/archive/2026-09-23-add-project-detail-tabs） — 建立项目页分面导航（开发/质量/会话三分面、默认开发、选中态不持久化）、开发分面零回归承载、质量空态占位与会话分面内联契约（含按需加载门控）
- 2026-09-24 add-code-review-agent-and-quality-tab（spec/archive/2026-09-24-add-code-review-agent-and-quality-tab） — 「质量」分面由空态占位改为承载 code-review 质量视图（QualityTab、按需拉取、桌面与移动端可用）
- 2026-09-26 add-spec-list-filter-stickiness（spec/archive/2026-09-26-add-spec-list-filter-stickiness） — 页签选中态改为 URL `tab` 参数持久化（replace 语义、刷新恢复、缺省不写参），分面扩为含「回归」的四分面
- 2026-11-08 协作拓扑与会话接入退役批（用户指令，无归档 SPEC，登记见 log.md） — 镜像条款收口：「会话」分面条款删除（项目级自由会话整体退役），分面组成与 URL 合法值域同步现役五分面
- 2026-11-10 add-project-home-tab（spec/changes/add-project-home-tab/） — 分面组成由五分面扩为六分面（「项目首页」居首位、默认选中「功能开发」不变），URL `tab` 合法值域增加 `home`；「功能开发」零回归条款、replace 写回与按需加载门控语义维持
- 2026-11-12 分面卡体内边距对齐与 facetWrap 移动端校准（spec/knowledge/_inbox/done/quality-tab-body-padding-align-dev-tab.md） — 折叠分面卡体桌面内边距与「功能开发」对齐 8px 的口径（「代码审查」分面先行对齐的实测结论）；含 facetWrap 移动端负边距按 24px 卡体调校的耦合红线与 isMobile 分档豁免要求、antd v6 缩写陷阱单边键纪律与桌面/移动几何验证锚点（桌面口径现以 facetCardStyles 单源推广至四分面）
