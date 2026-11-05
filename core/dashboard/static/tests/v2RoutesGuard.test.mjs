// v2 路由族隔离守卫（redesign-dashboard-v2-ui 1.2）。
//
// 钉死两件事：
// 1. config/routes.ts 既有条目逐字不变——v2 域新增只允许追加 /v2/* 分支，
//    既有 path/name/icon/component/redirect/layout 任一漂移即失败；
// 2. 现产菜单零污染——v2 路由条目不写 name/icon，app.tsx menuDataRender
//    白名单（现产菜单单源，手写数组、不消费路由表）零 v2 条目。
//
// 零依赖 node:test 源码扫描（同 pageChrome.test.mjs 习语）；渲染行为由
// `npm run build` 与浏览器冒烟覆盖。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import routes from '../config/routes.ts';

const STATIC_ROOT = join(import.meta.dirname, '..');

// 既有条目快照（redesign-dashboard-v2-ui 落地前 config/routes.ts 全量逐字
// 快照；既有路由零改动 Scenario 的对照基准）。v2 分支只允许追加在其后。
const LEGACY_ROUTES = [
  { path: '/', redirect: '/overview' },
  { path: '/overview', name: '概览', icon: 'dashboard', component: './overview' },
  { path: '/projects', name: '项目', icon: 'project', component: './projects' },
  {
    path: '/command-center',
    name: '指挥中心',
    icon: 'control',
    component: './command-center',
  },
  { path: '/chain', redirect: '/activities?tab=chain' },
  { path: '/projects/:name/:spec', component: './projects/detail' },
  { path: '/projects/:name/:spec/topology', layout: false, component: './projects/topology' },
  { path: '/projects/:name', component: './projects/list' },
  { path: '/settings', name: '配置', icon: 'setting', component: './settings' },
  { path: '/activities', name: '运维', icon: 'history', component: './activities' },
  { path: '/help', name: '帮助', icon: 'question', component: './help' },
];

test('既有路由条目逐字不变（快照守卫）', () => {
  assert.ok(
    routes.length > LEGACY_ROUTES.length,
    '路由表应含既有条目 + v2 追加分支',
  );
  const head = routes.slice(0, LEGACY_ROUTES.length);
  assert.deepEqual(
    head,
    LEGACY_ROUTES,
    'config/routes.ts 既有条目发生漂移——v2 域只允许追加 /v2/* 分支',
  );
});

test('未匹配路径兜底仍存在且收尾（/v2/* 未匹配回退既有兜底）', () => {
  const last = routes[routes.length - 1];
  assert.deepEqual(last, { path: '*', redirect: '/overview' });
});

test('v2 路由族六条齐备且不写 name/icon（菜单/页头零污染前置）', () => {
  const expected = [
    { path: '/v2/overview', component: './v2/overview' },
    { path: '/v2/projects/:name/:spec', component: './v2/specDetail' },
    { path: '/v2/projects/:name', component: './v2/projectDetail' },
    { path: '/v2/settings', component: './v2/settings' },
    { path: '/v2/help', component: './v2/help' },
    { path: '/v2/activities', component: './v2/ops' },
  ];
  for (const exp of expected) {
    const hit = routes.find((r) => r.path === exp.path);
    assert.ok(hit, `缺少 v2 路由 ${exp.path}`);
    assert.equal(hit.component, exp.component, `${exp.path} component 漂移`);
    assert.equal(hit.name, undefined, `${exp.path} 不得写 name（现产菜单/页头零污染）`);
    assert.equal(hit.icon, undefined, `${exp.path} 不得写 icon`);
    assert.equal(hit.redirect, undefined, `${exp.path} 应为实体页面路由`);
  }
  // 动态段声明序：:name/:spec 必须先于 :name（防动态段吞匹配）
  const specIdx = routes.findIndex((r) => r.path === '/v2/projects/:name/:spec');
  const projIdx = routes.findIndex((r) => r.path === '/v2/projects/:name');
  assert.ok(specIdx >= 0 && projIdx > specIdx, '/v2/projects/:name/:spec 须先于 /v2/projects/:name');
});

test('app.tsx menuDataRender 白名单零 v2 条目（现产菜单单源逐字不变）', () => {
  const text = readFileSync(join(STATIC_ROOT, 'src', 'app.tsx'), 'utf8');
  const block = text.slice(text.indexOf('menuDataRender'));
  assert.ok(block.includes("path: '/overview'"), 'menuDataRender 基准菜单缺失（扫描锚失效）');
  assert.ok(!block.includes('/v2'), 'menuDataRender 白名单出现 v2 条目——现产菜单被污染');
});
