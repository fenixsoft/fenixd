# ProLayout 内层 scope 派生族覆盖与运行时布局配置热切档陷阱

- 现象：深档下侧栏 Menu 选中项药丸呈浅灰 rgb(215,216,216)+白字不可读，且热切档后内容区一半组件停旧档、刷新才全量翻转。
- 陷阱 A（派生族覆盖）：ProLayout 内层 ConfigProvider scope 以 `token:{colorPrimary}` 重播种（pro-components ProLayout.js），根 ConfigProvider `components.Menu.itemSelectedBg` 不生效；scope 内缺省派生 `colorPrimaryBg`——白主色种子（#f9fafb）下 darkAlgorithm 派生出**浅灰**（白种子的高亮底族），于是药丸浅灰。凡「内层 scope + 白/黑种子」场景，选中/hover/active 底必须显式给值（dshLayoutTokenDark.sider.colorBgMenuItemSelected + global.less `!important` CSS 兜底同构双保险，与 darkSeedBgToken 陷阱同族）。
- 陷阱 B（热切档不重跑）：umi 插件 Layout 的运行时布局配置（app.tsx `layout()`，含 navTheme/colorPrimary/token）只在 route/initialState 变化时重跑；主题翻档不触发，内层 scope 停旧档=半明半暗混合态，手动刷新才全量。修法=按档 `Fragment key={scheme}` 重挂 rootContainer children（含插件 Layout），切档即免刷新整跑运行时配置；代价=切档瞬间页面级状态（滚动位/未提交表单）随重挂重置。
- 取证锚点：修复 commit d9daee94d（fenixd）；实测深档药丸 rgba(255,255,255,0.06)、dark↔light 免刷新往返 card #ffffff↔#232324。
- 补充（c3227a8c2，第三件冻结物）：`.ant-pro-layout-bg-list`（pointer-events:none 全视口装饰层）以 inline style 携带 bgLayout 渐变，同样只在 ProLayout 首次挂载（整页加载）按档求值，切档/路由变化不重算——浅档白色渐变横带恒残留且盖住内容区顶签行（深档白字落白带=幽灵）。取证陷阱：该层 elementsFromPoint 不可见（pointer-events 穿透）且底色走 background-image 非 background-color，两轮 DOM 扫描均漏检；「body 涂红反证」是最快定位法（涂红后白带不变→其上有不透明层→枚举 pointer-events:none 层命中）。修复=global.less 深档块 `.ant-pro-layout-bg-list` 渐变 `!important` 压内联（值=重载深档实测字节 #232324→#151517 28%）。
