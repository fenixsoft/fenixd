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
    name: '运维记录',
    icon: 'history',
    component: './activities',
  },
  {
    path: '*',
    redirect: '/overview',
  },
];
