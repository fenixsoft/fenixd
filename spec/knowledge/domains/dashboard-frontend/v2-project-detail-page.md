# v2 项目详情页

<!-- knowledge: capability=v2-project-detail-page rev=1
     sources=spec/changes/redesign-dashboard-v2-ui,spec/knowledge/_inbox/done/v2-projects-page-parity-1106.md -->

v2 域的项目详情工作台（`/v2/projects/:name`）：单项目全部分面的入口页——标题进全站统一标题栏，六分面页签承载功能开发与现产五类面板，SPEC 表、状态筛选与分页对齐现产口径。域级条款（路由隔离、主题单源、双形态分支）见 `v2-commercial-ui`。

## 规则

- **页面形态**：`V2Page variant="projects"`——白底满宽变体：页底白（V2_WHITE）、`.v2-inner` 去 1400px 居中收窄、随外部容器满宽、左右固定 30px，移动断点回填 14px 侧距；变体契约与移动特异性守卫见 `v2-commercial-ui`「页面壳与白底变体」条款。
- **标题声明形态**：标题元数据经 V2Page `titleBar` 槽位挂统一标题栏控件（渲染于 `.v2-page` 直下、`.v2-inner` 之前，壳位机制见 `unified-page-title-bar`）——`back` 回 `/v2/overview`、`title`=项目名、`subtitle`=「共 N 个 SPEC · M 个活跃」（计数 `TitleBarNum` 等宽）；声明形态与现产 projects/list 一致，页面零自画标题带。
- **状态筛选单源**：状态过滤 options 取模块级 `STATUS_OPTIONS` 常量——由 `listFilters.ts` `LIST_STATUSES` 全 11 态恒显派生、label 单源 `statusMeta`；不得从表内出现过的状态键派生（空表与新状态也恒显全量值域）。桌面工具条与移动筛选双下拉两处同源消费。antd Select 256px 虚拟滚动窗口与现产行为一致（11 项滚动可见、末项「已推送」），属控件默认行为非缺陷。
- **SPEC 表分页**：桌面形态分页 `pageSize: 20` + `showSizeChanger` + 「共 N 条」合计，口径与现产 projects/list DevTab 同款；移动卡片流不分页（原型形态维持）。
- **页签六分面**：功能开发（SpecDevPane 实体渲染）+ 代码审查/测试回归/架构蓝图/项目知识/会话接入五分面复用 `pages/projects/components` 现产组件（QualityTab/RegressionTab/ArchitectureTab/KnowledgeTab/SessionPanel），`project` + `active` 双 prop 门控按需加载（未选中零请求）；页签键域单源 import `ListTab`；占位说明页签（PlaceholderPane）退役。
- **页签选中态内存态**：页签选中态维持页内内存态，不引入现产 URL `tab` 参数契约（现产 tab 持久化属过滤粘滞域，v2 页不做）。
- **行点击下钻**：SPEC 表整行点击进 `/v2/projects/:name/:spec`，跳转语义由整行承载。

## 溯源

- 2026-11-05 redesign-dashboard-v2-ui（spec/changes/redesign-dashboard-v2-ui/） — 项目详情页原型定源：桌面 project-detail.html 与移动 m-project-detail.html 卡片流形态、SPEC 表列集与行点击下钻、四页签占位形态
- 2026-11-06 v2-projects-page-parity-1106（spec/knowledge/_inbox/done/v2-projects-page-parity-1106.md） — 现产对齐六项落页：白底满宽变体 projects、标题收编统一标题栏（back/title/subtitle 声明形态）、状态筛选 LIST_STATUSES 全 11 态单源、分页 20/showSizeChanger/showTotal（移动卡片流不分页）、页签四改六分面复用现产组件（PlaceholderPane 退役）、选中态维持内存态
