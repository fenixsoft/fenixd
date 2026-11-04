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
    // 处置链视图（add-escalation-chain-admin-arbiter 5.2）：Admin→Arbiter→Human
    // 自动处置链观测面（在办/队列/配额水位/上升件，只读）。
    path: '/chain',
    name: '处置链',
    icon: 'apartment',
    component: './chain',
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
    name: '设置',
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
  {
    path: '*',
    redirect: '/overview',
  },
];
