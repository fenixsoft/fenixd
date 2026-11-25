/**
 * @name umi 的路由配置
 * @doc https://umijs.org/docs/guides/routes
 */
// 页题 name 从文案目录单源取中文（add-framework-i18n-zh-en 3.1）：本文件被
// config.ts 构建期 Node 环境加载，不可 import '@umijs/max' 运行时 API——
// name 静态快照取 zh 目录（zh 渲染与现状一致）；运行时 document.title 由
// app.tsx layout().pageTitleRender 按当前语言渲染期求值（语言切换即时更新），
// 本静态 name 仅作构建期后备快照。
import zhCN from '../src/locales/zh-CN';

export default [
  {
    path: '/',
    redirect: '/overview',
  },
  {
    path: '/overview',
    name: zhCN['menu.overview'],
    icon: 'dashboard',
    component: './overview',
  },
  {
    path: '/projects',
    name: zhCN['menu.projects'],
    icon: 'project',
    component: './projects',
  },
  {
    // 管理指挥中心（add-command-center 3.2；2026-11-04 用户指令去脱壳改版）：
    // 原脱壳全屏深色页改为 ProLayout 内容区常规页（侧栏/顶栏/PageContainer
    // 页头与全菜单一致，配色继承 theme.ts 白底单源）；菜单项仍由
    // app.tsx menuDataRender 注册（routes name 仅供 PageContainer 标题链路）。
    path: '/command-center',
    name: zhCN['menu.commandCenter'],
    icon: 'control',
    component: './command-center',
  },
  {
    // 处置链并入运维页三页签（2026-11-05 用户指令；add-escalation-chain-admin-arbiter
    // 5.2 的独立观测页退役）：原独立路由保留重定向，老深链/书签落地运维页处置链
    // 页签（hash 路由，query 随 hash 传递，activities 页 initialTab 读取预选）。
    path: '/chain',
    redirect: '/activities?tab=chain',
  },
  {
    path: '/projects/:name/:spec',
    component: './projects/detail',
  },
  {
    path: '/projects/:name',
    component: './projects/list',
  },
  {
    path: '/settings',
    // 名「配置」（2026-11-05 用户指令）：与 app.tsx 菜单单源，避让 dsh web 既有「设置」
    name: zhCN['menu.settings'],
    icon: 'setting',
    component: './settings',
  },
  {
    path: '/activities',
    name: zhCN['menu.ops'],
    icon: 'history',
    component: './activities',
  },
  {
    path: '/help',
    name: zhCN['menu.help'],
    icon: 'question',
    component: './help',
  },
  // v2 商业化界面域六页已于 2026-11-07 用户指令整体退役删除（pages/v2/ 目录
  // 与 /v2/* 路由一并移除，原版页面为唯一界面）；存量 /v2/* 深链由底部 '*'
  // 兜底重定向回 /overview。
  {
    path: '*',
    redirect: '/overview',
  },
];
