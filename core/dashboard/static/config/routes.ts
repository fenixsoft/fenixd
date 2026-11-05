/**
 * @name umi 的路由配置
 * @doc https://umijs.org/docs/guides/routes
 */
export default [
  {
    path: '/',
    redirect: '/overview',
  },
  {
    path: '/overview',
    name: '概览',
    icon: 'dashboard',
    component: './overview',
  },
  {
    path: '/projects',
    name: '项目',
    icon: 'project',
    component: './projects',
  },
  {
    // 管理指挥中心（add-command-center 3.2；2026-11-04 用户指令去脱壳改版）：
    // 原脱壳全屏深色页改为 ProLayout 内容区常规页（侧栏/顶栏/PageContainer
    // 页头与全菜单一致，配色继承 theme.ts 白底单源）；菜单项仍由
    // app.tsx menuDataRender 注册（routes name 仅供 PageContainer 标题链路）。
    path: '/command-center',
    name: '指挥中心',
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
    // SPEC 协作拓扑大屏（add-spec-topology-bigscreen 4.1）：layout:false 脱壳
    // ——独立全屏深色页面，无 ProLayout 侧边栏/顶栏（从 SPEC 列表「协作拓扑」
    // 菜单项进入，退出大屏返回来源列表页）。
    path: '/projects/:name/:spec/topology',
    layout: false,
    component: './projects/topology',
  },
  {
    path: '/projects/:name',
    component: './projects/list',
  },
  {
    path: '/settings',
    // 名「配置」（2026-11-05 用户指令）：与 app.tsx 菜单单源，避让 dsh web 既有「设置」
    name: '配置',
    icon: 'setting',
    component: './settings',
  },
  {
    path: '/activities',
    name: '运维',
    icon: 'history',
    component: './activities',
  },
  {
    path: '/help',
    name: '帮助',
    icon: 'question',
    component: './help',
  },
  // ── v2 商业化界面域（redesign-dashboard-v2-ui D1 路由隔离）──────────────
  // 开发期全部 v2 页面挂 /v2/ 前缀，与既有页面并存；上方既有条目零改动。
  // v2 条目不写 name/icon：menuDataRender 白名单（app.tsx 现产菜单单源）不
  // 消费路由表，无 name 即不产生菜单/页头兜底污染——现产侧栏菜单逐字不变。
  // 未匹配的 /v2/* 路径落底部 '*' 兜底重定向（回退既有兜底，不影响既有匹配）。
  {
    path: '/v2/overview',
    component: './v2/overview',
  },
  {
    // 声明序：:name/:spec 必须先于 :name（react-router 精确段优先，显式排序
    // 兜底防动态段吞匹配）。
    path: '/v2/projects/:name/:spec',
    component: './v2/specDetail',
  },
  {
    path: '/v2/projects/:name',
    component: './v2/projectDetail',
  },
  {
    path: '/v2/settings',
    component: './v2/settings',
  },
  {
    path: '/v2/help',
    component: './v2/help',
  },
  {
    path: '/v2/activities',
    component: './v2/ops',
  },
  {
    path: '*',
    redirect: '/overview',
  },
];
