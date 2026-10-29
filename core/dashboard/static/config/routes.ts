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
    // 管理指挥中心（add-command-center 3.2）：layout:false 脱壳——全屏深色
    // 独立页面，无 ProLayout 侧边栏/顶栏（与拓扑大屏同款脱壳，
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
