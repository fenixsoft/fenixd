# v2 六页标题收编统一标题栏（titleBar 槽位）+ 帮助页白底 + 正文标题去重

2026-11-06 用户指令三则（本会话 fenixd-61 执行 help 侧，其余页由并行会话按协作分工迁移，
挂法经跨会话协调定案统一）：「帮助中心背景改白」「v2 页标题入标题栏控件（所有 v2 共性）
」「帮助正文标题去重（自动生成 + markdown 文件标题双显）」。

## 生效规则（待蒸馏进 dashboard-frontend 域）

1. **v2 标题经 V2Page titleBar 槽位声明**：六页（overview / projectDetail / specDetail /
   settings / help / ops）标题元数据一律 `<V2Page titleBar={<PageTitleBar … />}>`（四槽位
   title/subtitle/back/filters），自画标题带 V2TitleBand 与配套 V2BackArrow 已删除。
   **挂法关键**：titleBar 渲染在 `.v2-page` 直下、`.v2-inner` 之前——行壳位（embed 档
   60px sticky；同日二次指令后移动端行壳位退役、标题/过滤项经 HeaderSlot/actionsRender
   落 global header）满宽贴顶依赖此结构；若把 PageTitleBar 直挂进 `.v2-inner` 会被
   1400px 收窄 + 页顶内边距架空（embed sticky 初始跳位）。曾出现「直挂子节点」过渡
   形态（overview 上一版），已统一回槽位。
2. **v2 白底变体族**（v2.less 镜像）：`variant="overview"` 与 `variant="projects"`
   = 白底 + 去 1400px 收窄满宽 + 左右 30px；`variant="white"`（help 页）= 仅页底改白、
   1400px 居中列保留——`.v2-white` 不覆写 `.v2-inner` 即无特异性压制，移动端断点规则
   照常生效，无需 overview 式移动侧距回填。
3. **帮助正文标题去重**：DocPane 不渲染自动 `doc.title`——后端
   `help_routes._help_doc_title` 本就从 markdown 首个一级标题解析标题，自动行与正文
   H1 同文双显；保留正文 H1 为唯一标题（headingComponent 注入 GitHub slug id，
   锚点跳转不受影响），DocPane 的 marginTop 包裹层一并删除。
4. **关联全站改动（fenixd-44 报备）**：PageTitleBar 行壳位副标题仅 `!isMobile` 渲染
   （用户指令「副标题移动端不显示」）——help 页「N 篇文档」副标题在移动档隐藏属预期；
   该条归 `unified-page-title-bar` 能力页改写对象，与 v2 迁移分属两个用户指令。
5. **守卫**：`tests/v2TitleBarGuard.test.mjs` 四层钉死（六页槽位声明零 V2TitleBand
   代码残留 / {titleBar} 先于 .v2-inner / .v2-white 仅改底色 / DocPane 无自动标题）。
   源码扫描一律先剥块注释+行注释再做字面量断言——退役说明与迁移注记里的
   「V2TitleBand」字面量会误命中（ops 方协同踩坑报备）。
6. **跨会话协作面**：用户在四个并行会话下发了相邻指令（44=overview+PageTitleBar 副标题
   移动端隐藏、6a=ops 数据对齐+迁移、ce=projectDetail+projects 白底变体、61=help 三项+
   settings/specDetail 收尾迁移）。V2TitleBand 在 61 侧曾删又临时恢复（供在飞页编译），
   六页迁完后由 61 终删——多会话同仓时序：删共享导出前先 grep 全部引用方。

## 溯源

- 落地面：`src/pages/v2/shared.tsx`（V2Page titleBar 槽位 + white/projects 变体、
  V2TitleBand/V2BackArrow 删除）、六页 tsx（槽位声明）、`v2.less`（.v2-white，
  overview/projects 变体注释改写）、`tests/v2TitleBarGuard.test.mjs`（新建守卫）。
- playwright 实拍（8787，2026-11-06）：help 桌面（顶栏「帮助中心 · 15 篇文档」+
  白底 rgb(255,255,255) + 1400 居中 + 正文单 H1）/ 移动（行带满宽贴顶 + 目录按钮
  filters 右端）；settings（顶栏「配置」+ 作用域 Select 落顶栏右上）；specDetail
  （返回箭头+富标题+胶囊换行收纳+rightActions 落右上）；全量 367 测试 0 失败。
  截图 `.history/v2-*-1106.png` 五张。
- 知识页待改写对象：`unified-page-title-bar.md`（「7 个常规页」清单扩及 v2 六页、
  副标题移动端隐藏规则）、`v2-commercial-ui.md`（V2TitleBand 形态句退役、白底变体族、
  titleBar 槽位声明方式）、`help-center.md`（正文标题去重与白底）。
