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
    // 跨项目角色协作图谱大屏（add-collab-graph-bigscreen 3.1）：layout:false
    // 脱壳——全屏深色独立页面，无 ProLayout 侧边栏/顶栏（overview 枢纽页
    // 「协作图谱大屏」入口进入，退出大屏返回 overview）。
    path: '/overview/collab-graph',
    layout: false,
    component: './overview/collabGraph',
  },
  {
    path: '/projects',
    name: '项目',
    icon: 'project',
    component: './projects',
  },
  {
    // 管理指挥中心（add-command-center 3.2）：layout:false 脱壳——全屏深色
    // 独立页面，无 ProLayout 侧边栏/顶栏（与协作图谱/拓扑大屏同款脱壳，
    // 菜单项「指挥中心」进入）。
    path: '/command-center',
    layout: false,
    component: './command-center',
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
