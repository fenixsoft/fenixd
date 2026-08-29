# Dashboard AMIS V2 重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 AMIS 6.13.0 JSON DSL 在 `/v2/` 前缀下重建 dashboard 全部功能,老 app.js 并存,Playwright 验收通过后替换。

**Architecture:** AMIS SDK embed 模式 + app 组件多页壳(hash 路由);一个 App 壳级 SSE 桥 custom 组件把 `/api/stream` 事件转 broadcast,各视图 JSON 用 `onEvent → reload` 消费;run 实时流弹窗为独立 custom 组件;API 响应经 adapters.js 纯函数适配。后端零改动。

**Tech Stack:** AMIS 6.13.0 SDK(vendor 静态文件)、原生 JS(无构建链)、node:test(adapters 单测)、Playwright(验收)、Python 标准库 dashboard 服务(现有,不改)。

**Spec:**
- 设计:`docs/superpowers/specs/2026-08-29-amis-dashboard-v2-design.md`
- 行为规格(实施者的 API 字段与行为唯一权威):`docs/superpowers/specs/2026-08-29-amis-dashboard-v2-behavior.md`(下称 behavior.md,引用格式 `behavior.md §3`)

## Global Constraints

- 后端零改动:不修改 `core/dashboard/server.py`、`data.py`、`watcher.py`、`registry.py` 及任何 API 响应。
- 老版不动:`core/dashboard/static/app.js`、`style.css`、`vendor/` 禁止修改;新增文件全部在 `core/dashboard/static/v2/` 与 `tests/v2/` 下。
- AMIS 版本固定 6.13.0(npm tarball `/tmp/amis-6.13.0.tgz` 已验证可下载;若过期重下 `npm pack amis@6.13.0`)。
- custom JS 收敛为 4 个文件:`v2/app.js`(路由+embed)、`v2/bridge.js`(SSE 桥)、`v2/run-stream.js`(run 流 custom)、`v2/adapters.js`(数据适配)。不得新增第 5 个 JS 文件;页面全部是 `v2/pages/*.json`。
- 主题:仅 dark(embed 参数 `theme: 'dark'`,引 sdk.css + dark.css)。
- Toast 时序:成功 5s / 错误 6s 自动消失(behavior.md §9)——Playwright 断言窗口以此为限,不得缩短等待。
- config 页编辑中豁免 SSE 重绘(behavior.md §0/§9);SSE state 帧对 overview 视图重拉、500ms 前缘节流(behavior.md §0)。
- commit 信息用中文一行,格式 `<task主题>: <做了什么>`;每任务至少一个 commit。
- 浏览器验证统一走 Playwright(dashboard 地址 `http://127.0.0.1:8787`)。

## componentId 全局约定(桥接刷新的跨任务契约)

| componentId | 所属任务 | 挂载组件 | 响应的广播事件 |
|---|---|---|---|
| `ov-stats` | Task 5 | service(拉 /api/overview) | `sse:state`、`sse:refresh` |
| `ov-projects` | Task 5 | service(拉 /api/projects) | `sse:state`、`sse:refresh` |
| `spec-crud` | Task 6 | crud(拉 /api/specs) | `sse:state` |
| `spec-detail` | Task 7 | service(拉 /api/specs/:spec) | `sse:detail`、`sse:state` |
| `alert-banner` | Task 11 | 壳级 service(拉 /api/alerts) | `sse:alerts` |
| `act-timeline` | Task 11 | 页内 service(拉 /api/admin-activities) | `sse:admin_activities` |

config 页不挂广播刷新(编辑豁免,见 Task 10)。

## adapters.js 导出签名(Task 4 定义,后续任务消费)

```js
window.Adapters = {
  SPEC_LIFECYCLE: [...],            // 状态生命周期顺序数组(behavior.md §2)
  adaptSpecs(rawList) -> rows,      // 字段映射+生命周期排序+fix 树(带 children)
  adaptOverview(raw) -> statsObj,   // 5 统计块字段映射(数字化,防 "0" 字符串)
  adaptProjects(rawList) -> rows,   // 项目卡片字段映射
  adaptSpecDetail(raw) -> obj,      // 详情页字段映射(verdict 计数数字化)
  adaptAlerts(rawList) -> rows,
  adaptActivities(rawList) -> rows,
  adaptConfig(raw) -> formObj,      // llm 空对象兜底(behavior.md §6)
  buildConfigPayload(formObj, loadedSnapshot) -> payload,  // 三级回退合并(behavior.md §6)
  validateChain(chainValue, providers) -> true | string,   // Agent 链完整性校验(behavior.md §6)
};
```

## run-stream.js custom 协议(Task 8 定义,Task 9 消费)

```js
// 注册为 AMIS custom 组件工厂(behavior.md §3/§4 为行为权威):
window.RunStream = {
  register(amisLib) { /* amisLib.custom 或 Renderer 注册 */ },
  // 组件 props 约定:
  //   mode: 'run' | 'admin'
  //   mode==='run':   runId: string            → GET /api/runs/<runId>?tail=300 + watch
  //   mode==='admin': project, spec, events    → 状态机:POST /api/spec-admin-invoke
  //                                          → 409 则 toast 并终止
  //                                          → 轮询 GET /api/specs/<spec> 每 5s 解析 admin_run_id
  //                                          → 拿到后切换 run 模式
  //   onDispose: 关闭时 DELETE /api/runs/<id>/watch?cid=<cid>
};
```

---

### Task 1: SDK vendor 到 static/v2/

**Files:**
- Create: `core/dashboard/static/v2/sdk.js`, `sdk.css`, `dark.css`, `iconfont.css`, `helper.css`

**Interfaces:**
- Produces: 后续所有任务引用的静态资源路径 `/v2/sdk.js`、`/v2/sdk.css`、`/v2/dark.css`、`/v2/iconfont.css`、`/v2/helper.css`

- [ ] **Step 1: 解压提取 5 个文件**

```bash
mkdir -p /tmp/amis-pkg core/dashboard/static/v2
tar xzf /tmp/amis-6.13.0.tgz -C /tmp/amis-pkg \
  package/sdk/sdk.js package/sdk/sdk.css package/sdk/dark.css \
  package/sdk/iconfont.css package/sdk/helper.css
cp /tmp/amis-pkg/package/sdk/{sdk.js,sdk.css,dark.css,iconfont.css,helper.css} core/dashboard/static/v2/
```

若 `/tmp/amis-6.13.0.tgz` 不存在,先 `cd /tmp && npm pack amis@6.13.0`。

- [ ] **Step 2: 验证文件完整**

```bash
ls -la core/dashboard/static/v2/ && head -c 100 core/dashboard/static/v2/sdk.js
```

Expected: 5 个文件,sdk.js 数 MB 级,头部为合法 JS(非 HTML 错误页)。

- [ ] **Step 3: 验证现有服务能 serve /v2/ 静态文件**

启动 dashboard(如已在跑则跳过):`python3 bin/fenix_dashboard.py --serve`。然后 `curl -sI http://127.0.0.1:8787/v2/sdk.js | head -1`。
Expected: `HTTP/1.1 200 OK`(server.py:231 fallback 自动生效,后端无需改动)。

- [ ] **Step 4: Commit**

```bash
git add core/dashboard/static/v2/
git commit -m "v2-sdk: vendor AMIS 6.13.0 SDK 静态产物"
```

---

### Task 2: v2 骨架 — index.html + hash 路由 embed + Playwright 基建

**Files:**
- Create: `core/dashboard/static/v2/index.html`
- Create: `core/dashboard/static/v2/app.js`
- Create: `core/dashboard/static/v2/pages/app.json`(临时壳,Task 5 起逐页充实)
- Create: `tests/v2/package.json`, `tests/v2/smoke.spec.js`, `tests/v2/playwright.config.js`

**Interfaces:**
- Consumes: `/v2/sdk.js` 等(Task 1)
- Produces: `window.V2 = { route: () => ({page, params, query}) }` 路由解析;`amisScoped`(embed 实例);hash 路由模式 `#/overview`、`#/project/:name`、`#/spec/:project/:name`、`#/config/:project?tab=`、`#/activities/:project`(behavior.md §8;project 可省略时用 `/config`、`/activities`);pages/app.json 的 app schema 骨架(pages 数组带 url 参数路由,页面 schema 先为空 page)

- [ ] **Step 1: 写 Playwright 基建**

`tests/v2/package.json`:

```json
{ "name": "fenix-v2-tests", "private": true, "type": "module",
  "dependencies": { "@playwright/test": "^1.49.0" } }
```

`tests/v2/playwright.config.js`:

```js
import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: '.',
  timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:8787' },
});
```

```bash
cd tests/v2 && npm install && npx playwright install chromium
```

`tests/v2/smoke.spec.js`(先写,此时必失败):

```js
import { test, expect } from '@playwright/test';
test('v2 壳加载并渲染 AMIS 壳级标题', async ({ page }) => {
  await page.goto('/v2/index.html#/overview');
  await expect(page.locator('#root')).not.toBeEmpty();
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd tests/v2 && npx playwright test smoke.spec.js`
Expected: FAIL(index.html 不存在)

- [ ] **Step 3: 写 index.html 与 app.js(hash 路由 embed)**

`core/dashboard/static/v2/index.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fenix Dashboard V2</title>
<link rel="stylesheet" href="/v2/sdk.css">
<link rel="stylesheet" href="/v2/dark.css">
<link rel="stylesheet" href="/v2/iconfont.css">
<link rel="stylesheet" href="/v2/helper.css">
</head>
<body class="theme-dark">
<div id="root"></div>
<script src="/v2/sdk.js"></script>
<script src="/v2/adapters.js"></script>
<script src="/v2/bridge.js"></script>
<script src="/v2/run-stream.js"></script>
<script src="/v2/app.js"></script>
</body>
</html>
```

注:adapters.js/bridge.js/run-stream.js 此刻尚不存在,Task 3/4/8 建立时按序生效;本任务先创建空占位文件(`window.Adapters={};` / `window.Bridge={};` / `window.RunStream={};`),避免 404 噪音,后续任务替换实现。

`core/dashboard/static/v2/app.js` — SDK 模式 hash 路由(移植官方 examples/app/index.jsx 思路):

```js
(function () {
  const amisLib = amisRequire('amis/embed');

  // ── hash 路由解析 ─────────────────────────────
  // 路由表(behavior.md §8):
  //   #/overview
  //   #/project/:name
  //   #/spec/:project/:name
  //   #/config/:project?tab=   (project 可省:#/config)
  //   #/activities/:project    (可省:#/activities)
  const ROUTES = [
    { page: 'overview',   re: /^\/overview$/ },
    { page: 'project',    re: /^\/project\/([^/?]+)/ },
    { page: 'spec-detail', re: /^\/spec\/([^/?]+)\/([^/?]+)/ },
    { page: 'config',     re: /^\/config(?:\/([^/?]+))?/ },
    { page: 'activities', re: /^\/activities(?:\/([^/?]+))?/ },
  ];

  function parseHash() {
    const raw = location.hash.replace(/^#/, '') || '/overview';
    const [path, qs] = raw.split('?');
    const query = Object.fromEntries(new URLSearchParams(qs || ''));
    for (const r of ROUTES) {
      const m = path.match(r.re);
      if (m) return { page: r.page, params: m.slice(1), query, path };
    }
    return { page: 'overview', params: [], query, path: '/overview' };
  }
  window.V2 = { route: parseHash };

  fetch('/v2/pages/app.json').then(r => r.json()).then(appSchema => {
    const amisScoped = amisLib.embed('#root', appSchema, {
      // 数据域默认值:各页面 schema 里可用 ${params[0]} 等
    }, {
      theme: 'dark',
      location: parseHash(),
      jumpTo: (to, action) => { location.hash = to.startsWith('#') ? to : '#' + to; },
      updateLocation: (location, action) => {
        if (action?.actionType === 'url') { location.href = location; return; }
        location.hash = typeof location === 'string' ? location : '#' + (location.pathname || '') + (location.search || '');
      },
      isCurrentUrl: (location) => {
        const cur = parseHash();
        return '#' + cur.path === (location.hash || '');
      },
      // 响应适配全局兜底:非 {status:0} 结构的 /api 响应原样透传,
      // 页面级适配用 adapters.js 处理(见各页面任务的 api.adaptor)
      responseAdaptor: (api, payload) => payload,
    });
    window.amisScoped = amisScoped;
  });

  window.addEventListener('hashchange', () => {
    window.amisScoped && window.amisScoped.updateProps({ location: parseHash() });
  });
})();
```

`core/dashboard/static/v2/pages/app.json`(壳级骨架;alert-banner 与 SSE 桥 Task 3/11 加入):

```json
{
  "type": "app",
  "brandName": "Fenix",
  "header": {
    "type": "tpl",
    "wrapperComponent": "div",
    "className": "v2-bridge-slot"
  },
  "asideBefore": [],
  "pages": [
    { "label": "概览", "icon": "fa fa-home", "url": "/", "redirect": "/overview" },
    { "label": "概览", "url": "/overview", "schema": { "type": "page", "body": [] } },
    { "label": "项目", "url": "/project/:name", "schema": { "type": "page", "body": [] } },
    { "label": "SPEC 详情", "url": "/spec/:project/:name", "schema": { "type": "page", "body": [] } },
    { "label": "配置", "url": "/config", "schema": { "type": "page", "body": [] } },
    { "label": "配置", "url": "/config/:project", "schema": { "type": "page", "body": [] } },
    { "label": "运维记录", "url": "/activities", "schema": { "type": "page", "body": [] } },
    { "label": "运维记录", "url": "/activities/:project", "schema": { "type": "page", "body": [] } }
  ]
}
```

注:app.json 由 app.js fetch 加载,注意浏览器缓存——`fetch('/v2/pages/app.json?t=' + Date.now())` 防开发期缓存,验收前保留。

- [ ] **Step 4: 运行确认通过**

Run: `cd tests/v2 && npx playwright test smoke.spec.js`
Expected: PASS(#root 被渲染出 AMIS 壳;侧边栏出现"概览"菜单)

- [ ] **Step 5: 手动浏览器检查路由切换**

用 Playwright 驱动:`page.goto('/v2/index.html#/project/demo')` 断言 URL hash 保留且页面不崩(此时 body 空白属正常)。三种参数路由 `/spec/p/s`、`/config?tab=llm`、`/activities` 逐一访问无 JS console 错误:

```js
const errors = [];
page.on('pageerror', e => errors.push(e));
// 依次 goto 后 expect(errors).toEqual([])
```

- [ ] **Step 6: Commit**

```bash
git add core/dashboard/static/v2/ tests/v2/
git commit -m "v2-skeleton: AMIS 壳 + hash 路由 embed + Playwright 冒烟"
```

---

### Task 3: bridge.js — SSE 桥(App 壳级 custom + broadcast)

**Files:**
- Modify: `core/dashboard/static/v2/bridge.js`(替换占位)
- Modify: `core/dashboard/static/v2/pages/app.json`(header 挂桥组件)
- Test: `tests/v2/bridge.spec.js`

**Interfaces:**
- Consumes: Task 2 的 app.json 壳
- Produces: 广播事件 `sse:state`、`sse:detail`、`sse:refresh`、`sse:alerts`、`sse:admin_activities`、`sse:run_meta`(data=原始 SSE 帧 JSON);全局 `window.BridgeTest = { lastEvent }` 供测试断言

- [ ] **Step 1: 写失败测试**

`tests/v2/bridge.spec.js`:

```js
import { test, expect } from '@playwright/test';
test('SSE 桥收到 hello 帧并广播(桥组件注册于壳级)', async ({ page }) => {
  await page.goto('/v2/index.html#/overview');
  // 行为规格 §0:hello 帧 {type:'hello', cid} 到达即广播 sse:hello
  await page.waitForFunction(() => window.BridgeTest?.lastEvent?.type === 'hello', null, { timeout: 10000 });
  const evt = await page.evaluate(() => window.BridgeTest.lastEvent);
  expect(evt.cid).toBeTruthy();
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd tests/v2 && npx playwright test bridge.spec.js`
Expected: FAIL(BridgeTest 未定义)

- [ ] **Step 3: 实现 bridge.js**

`core/dashboard/static/v2/bridge.js`:

```js
(function () {
  // SSE 桥:App 壳级 custom 组件(不随路由销毁,设计 §3)
  // 行为规格 §0:state 帧触发 overview 重拉 + 500ms 前缘节流;config 视图编辑豁免由 config 页自身处理
  window.BridgeTest = { lastEvent: null };

  const THROTTLE_MS = 500;
  const lastFired = {}; // eventName -> ts,前缘节流

  function shouldFire(name) {
    const now = Date.now();
    if (lastFired[name] && now - lastFired[name] < THROTTLE_MS) return false;
    lastFired[name] = now;
    return true;
  }

  window.Bridge = {
    attach(props) {
      const es = new EventSource('/api/stream');
      es.onmessage = (e) => {
        if (!e.data) return; // 25s 心跳是注释帧,不进 onmessage;保险跳过空帧
        let evt;
        try { evt = JSON.parse(e.data); } catch { return; }
        window.BridgeTest.lastEvent = evt;
        if (evt.type === 'hello') window.Bridge.cid = evt.cid;  // Task 8 watch 订阅依赖
        const name = 'sse:' + evt.type;
        // hello 只广播一次;refresh/state 走 500ms 前缘节流(behavior.md §0)
        if ((evt.type === 'refresh' || evt.type === 'state') && !shouldFire(name)) return;
        props.onAction(null, {
          actionType: 'broadcast',
          args: { eventName: name },
          data: evt,
        }, {});
      };
      es.onerror = () => console.error('[v2-bridge] SSE 连接异常,实时刷新已中断', new Date().toISOString());
      window.Bridge._es = es;
      return es;
    },
  };
})();
```

在 `pages/app.json` 的 `header` 中替换为桥组件(壳级,不随页面切换销毁):

```json
"header": {
  "type": "custom",
  "name": "sse-bridge",
  "onMount": "(dom, data, onChange, props) => { window.Bridge.attach(props); }",
  "onUnmount": "() => { window.Bridge._es && window.Bridge._es.close(); }"
}
```

注:app.json 中 `onMount` 必须是字符串形式的函数体(AMIS schema 约定,SDK 模式下由 `fetch` 加载后 `eval` 语义执行)。若字符串函数在 6.13.0 不生效,备选方案:把 onMount 移入 app.js 在 embed 前通过 `window.amisLib` 全局注册 custom 渲染器(`amisRequire('amis').Renderer`),实现等价。

- [ ] **Step 4: 运行确认通过**

Run: `cd tests/v2 && npx playwright test bridge.spec.js`
Expected: PASS(hello 帧到达且 BridgeTest.lastEvent.cid 非空)

- [ ] **Step 5: 验证广播能触达页面组件(临时冒烟)**

`tests/v2/bridge-broadcast.spec.js`:

```js
import { test, expect } from '@playwright/test';
test('页面组件能监听 sse 广播(渲染一个 toast 作为探针)', async ({ page }) => {
  await page.goto('/v2/index.html#/overview');
  // 本任务先在 overview 空 page body 里临时放一个监听组件验证链路,Task 5 移除:
  // { "type": "service", "id": "probe", "onEvent": { "sse:refresh":
  //   { "actions": [{ "actionType": "toast", "args": { "msgType":"info", "msg":"broadcast-ok" } }] } } }
  // watcher.py 1s 扫描会自然产生 refresh 帧(behavior.md §0),15s 内必到
  await page.getByText('broadcast-ok').waitFor({ timeout: 15000 });
});
```

实现:在 `pages/app.json` overview 页 body 临时加探针 service(注释标注 `<!-- Task 5 移除 -->`)。运行确认 PASS 后,此探针保留至 Task 5 改造时删除。

- [ ] **Step 6: Commit**

```bash
git add core/dashboard/static/v2/bridge.js core/dashboard/static/v2/pages/app.json tests/v2/
git commit -m "v2-bridge: SSE 桥 custom 组件 + broadcast 广播链路"
```

---

### Task 4: adapters.js — 数据适配纯函数 + node 单测

**Files:**
- Modify: `core/dashboard/static/v2/adapters.js`(替换占位)
- Test: `tests/v2/adapters.test.mjs`
- Fixture: `tests/v2/fixtures/api-samples.json`

**Interfaces:**
- Produces: 见本计划头部「adapters.js 导出签名」;浏览器端挂 `window.Adapters`,node 测试直接 `import`

- [ ] **Step 1: 抓取真实 API 样本做 fixture**

dashboard 运行时(先手工造一个带 fix- 子 SPEC 的项目状态,或用现有项目):

```bash
mkdir -p tests/v2/fixtures
for ep in "overview" "specs?project=<有fix子spec的项目名>" "alerts" "admin-activities" "config"; do
  curl -s "http://127.0.0.1:8787/api/$ep" >> tests/v2/fixtures/api-samples.json
done
```

把每段样本整理成 `{"overview": ..., "specs": ..., "alerts": ..., "admin-activities": ..., "config": ...}` 单个 JSON 对象文件。同时从 behavior.md §1 的字段表核对字段名一字不差。

- [ ] **Step 2: 写失败测试(node:test)**

`tests/v2/adapters.test.mjs`(核心用例;字段名以 behavior.md §1/§2 为准,以下为断言意图,写测试时按 fixture 实际字段名落笔):

```js
import { test } from 'node:test';
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

// adapters.js 是 UMD 风格:node 下走 module.exports,浏览器下挂 window
const require = createRequire(import.meta.url);
const { Adapters } = require('../core/dashboard/static/v2/adapters.js');
const fx = JSON.parse(readFileSync(new URL('./fixtures/api-samples.json', import.meta.url)));

test('adaptSpecs: 生命周期排序', () => {
  const rows = Adapters.adaptSpecs(fx.specs);
  const order = rows.map(r => r.status);
  const idx = s => Adapters.SPEC_LIFECYCLE.indexOf(s);
  const seq = order.filter(s => idx(s) >= 0).map(idx);
  assert.deepEqual(seq, [...seq].sort((a, b) => a - b));
});

test('adaptSpecs: fix- 前缀构建 children 树', () => {
  const rows = Adapters.adaptSpecs(fx.specs);
  const parent = rows.find(r => (r.children || []).length > 0);
  assert.ok(parent, '存在带 children 的父行');
  // behavior.md §2:fix-<父名> 归入 <父名> 的 children;父行聚合子任务进度
  for (const c of parent.children) assert.ok(c.isFixChild);
});

test('adaptOverview: 计数字段数字化(防 "0" 字符串)', () => {
  const s = Adapters.adaptOverview(fx.overview);
  for (const k of Object.keys(s)) assert.equal(typeof s[k], 'number');
});

test('adaptConfig: llm 缺失时兜底空结构(behavior.md §6)', () => {
  const cfg = Adapters.adaptConfig({});
  assert.deepEqual(cfg.llm, { providers: [] });
});

test('buildConfigPayload: 数字三级回退(空/NaN→快照→默认,behavior.md §6)', () => {
  const payload = Adapters.buildConfigPayload(
    { max_parallel: '' },            // 表单空值
    { max_parallel: 3 },             // 已加载快照
    { max_parallel: 2 });            // 领域默认
  assert.equal(payload.max_parallel, 3);
});
```

- [ ] **Step 3: 运行确认失败**

Run: `node --test tests/v2/adapters.test.mjs`
Expected: FAIL(Adapters 方法未定义)

- [ ] **Step 4: 实现 adapters.js**

实现规则全部来自 behavior.md:§2(生命周期序、fix 树聚合、字段映射)、§1(verdict 计数数字化)、§6(llm 兜底、三级回退、链校验合并)。UMD 尾部:

```js
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = { Adapters: factory() };
  else root.Adapters = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  const SPEC_LIFECYCLE = [/* behavior.md §2 枚举顺序,逐字抄 */];
  function adaptSpecs(rawList) { /* 字段映射→过滤 fix- 前缀挂 children→SPEC_LIFECYCLE 排序;子行 isFixChild: true */ }
  function adaptOverview(raw) { /* Number() 归一,NaN→0 */ }
  function adaptProjects(rawList) { /* behavior.md §1 projects 字段 */ }
  function adaptSpecDetail(raw) { /* verdict 计数 Number() 化 */ }
  function adaptAlerts(rawList) { /* behavior.md §7 */ }
  function adaptActivities(rawList) { /* behavior.md §7 */ }
  function adaptConfig(raw) { /* raw.llm || {providers: []} 兜底 */ }
  function buildConfigPayload(form, snapshot, defaults) { /* 空/NaN→snapshot→defaults */ }
  function validateChain(chainValue, providers) { /* behavior.md §6 链完整性:必填角色齐全、模型名存在 */ }
  return { SPEC_LIFECYCLE, adaptSpecs, adaptOverview, adaptProjects, adaptSpecDetail, adaptAlerts, adaptActivities, adaptConfig, buildConfigPayload, validateChain };
});
```

(以上省略号处为按 behavior.md 落笔的纯函数体——字段名以 behavior.md §1 字段表逐字为准,不许自造。)

- [ ] **Step 5: 运行确认通过**

Run: `node --test tests/v2/adapters.test.mjs`
Expected: PASS(全部用例)

- [ ] **Step 6: Commit**

```bash
git add core/dashboard/static/v2/adapters.js tests/v2/
git commit -m "v2-adapters: 数据适配纯函数 + node 单测"
```

---

### Task 5: overview.json 概览页

**Files:**
- Create: `core/dashboard/static/v2/pages/overview.json`
- Modify: `core/dashboard/static/v2/pages/app.json`(overview 页 schema 改为 `{ "$ref": "overview" }` 式内联——SDK 无 $ref 则直接把 JSON 内容合入 app.json 对应页;采取:**app.json 保留壳,overview 页 schema 用 fetch 型 `schemaApi` 不可行(SDK 无服务端渲染),改为构建期合并:app.js 里 fetch 各 pages/*.json 后深合并进 app.json 再 embed**,相应修改 app.js)
- Test: `tests/v2/overview.spec.js`

**Interfaces:**
- Consumes: `Adapters.adaptOverview/adaptProjects`(Task 4)、`sse:state/sse:refresh` 广播(Task 3)、componentId `ov-stats`/`ov-projects`(全局契约)
- Produces: 概览页完整 JSON;启停删按钮的 http 动作模式(Task 6 的行内按钮复用同一模式)

- [ ] **Step 1: app.js 改造为页面 JSON 合并加载**

```js
// 替换原单个 fetch:
Promise.all([
  fetch('/v2/pages/app.json?t=' + Date.now()).then(r => r.json()),
  ...['overview', 'project', 'spec-detail', 'config', 'activities']
    .map(n => fetch('/v2/pages/' + n + '.json?t=' + Date.now())
      .then(r => r.json()).then(s => [n, s]).catch(() => [n, null])),
]).then(([appSchema, ...pageEntries]) => {
  for (const [name, schema] of pageEntries) {
    if (!schema) continue;
    // 按 url 前缀匹配页面:overview→/overview;project→/project/;spec-detail→/spec/;
    // config→/config;activities→/activities
    const urlMap = { overview: '/overview', project: '/project/', 'spec-detail': '/spec/',
                     config: '/config', activities: '/activities' };
    for (const p of appSchema.pages) {
      if (p.url && p.url.startsWith(urlMap[name])) p.schema = schema;
    }
  }
  // ...embed 原逻辑
});
```

- [ ] **Step 2: 写失败测试**

`tests/v2/overview.spec.js`:

```js
import { test, expect } from '@playwright/test';
test('概览页渲染统计块与项目卡片', async ({ page }) => {
  await page.goto('/v2/index.html#/overview');
  // 5 个统计块(behavior.md §1 overview 字段)——断言至少出现统计数值
  await expect(page.locator('#root').getByText(/SPEC/i).first()).toBeVisible({ timeout: 10000 });
  // 项目卡片:至少渲染出项目名(取 fixture 已知项目名替换 <PROJECT>)
  await expect(page.locator('#root').getByText('<PROJECT>')).toBeVisible({ timeout: 10000 });
});
```

(写测试时把 `<PROJECT>` 换成当前环境真实项目名。)

- [ ] **Step 3: 运行确认失败**

Run: `cd tests/v2 && npx playwright test overview.spec.js`
Expected: FAIL(页面 body 为空)

- [ ] **Step 4: 实现 overview.json**

结构(设计 §4;API 字段 behavior.md §1):

```jsonc
{
  "type": "page",
  "body": [
    { "type": "service", "id": "ov-stats", "name": "ov-stats",
      "api": { "url": "/api/overview", "adaptor": "return window.Adapters.adaptOverview(payload)" },
      "onEvent": {
        "sse:state":   { "actions": [{ "actionType": "reload", "componentId": "ov-stats" }] },
        "sse:refresh": { "actions": [{ "actionType": "reload", "componentId": "ov-stats" }] }
      },
      "body": [{ "type": "grid", "columns": [
        /* 5 个 stat 卡,字段名以 behavior.md §1 为准。示例(逐字照此模式展开 5 张): */
        { "md": 2, "body": { "type": "card", "body": [
          { "type": "tpl", "tpl": "<div class='v2-stat-num'>${runningSpecs}</div>",
            "style": { "fontSize": "1.8rem", "fontWeight": 700 } },
          { "type": "tpl", "tpl": "<div class='v2-stat-label'>运行中 SPEC</div>" }
        ] } }
        /* 其余 4 张同构:统计键与中文标签按 behavior.md §1 overview 字段表逐字落笔 */
      ] }] },
    { "type": "service", "id": "ov-projects", "name": "ov-projects",
      "api": { "url": "/api/projects", "adaptor": "return { items: window.Adapters.adaptProjects(payload) || payload }" },
      "onEvent": { "sse:state": { "actions": [{ "actionType": "reload", "componentId": "ov-projects" }] } },
      "body": [{ "type": "cards", "source": "${items}", "card": { /* 项目卡:名称、状态 badge、SPEC 计数 */ } }] }
  ]
}
```

项目卡启停删按钮(事件动作模式,Task 6 行内按钮复用):

```jsonc
{ "type": "button", "label": "启动", "level": "primary",
  "confirmText": "确认启动该项目?",
  "onEvent": {
    "click": {
      "actions": [
        { "actionType": "ajax", "args": { "api": { "method": "post", "url": "/api/projects/${name}/start" } } },
        { "actionType": "toast", "args": { "msgType": "success", "msg": "已发起启动" } },
        { "actionType": "reload", "componentId": "ov-projects" }
      ]
    }
  } }
```

停止/删除同构(删除用 confirmText + DELETE `/api/projects/${name}`);错误 toast `msgType: 'error'`。

同时移除 Task 3 的临时探针 service(`broadcast-ok`)——本任务 ov-stats 已有真实 sse:state 监听,探针使命结束。

- [ ] **Step 5: 运行确认通过 + SSE 联动验证**

Run: `cd tests/v2 && npx playwright test overview.spec.js`
Expected: PASS。

SSE 联动(实时刷新):创建 `tests/v2/overview-sse.spec.js`:

```js
import { test, expect } from '@playwright/test';
test('SSE state 帧触发统计块重拉(500ms 节流不阻断)', async ({ page }) => {
  await page.goto('/v2/index.html#/overview');
  // 触发真实数据变化:touch 一个项目 .fenix 目录下的文件(watcher.py 1s 扫描)
  // 用 page.evaluate 调一个只读探测:断言 ov-stats 在 10s 内发生 ≥2 次 reload
  const reloads = await page.evaluate(() => new Promise(res => {
    let n = 0; const iv = setInterval(() => ++n, 100);
    window.BridgeTest._countReload = () => n;   // 需在 ov-stats onEvent reload 前置钩子里计数
    setTimeout(() => { clearInterval(iv); res(n); }, 8000);
  }));
  expect(reloads).toBeGreaterThanOrEqual(2);
});
```

注:计数钩子实现——ov-stats 的 onEvent actions 里在 reload 前插入 `{"actionType": "custom", "script": "window.BridgeTest._countReload && window.BridgeTest._countReload()"}` 不干净;更简单:测试直接轮询 `page.waitForFunction` 监听 `performance` 网络计数不可靠,**采纳的方案是给 window.BridgeTest 加 `reloadCount`(bridge.js 的 broadcast 分发处对 `sse:state/sse:refresh` 事件自增)**,纯测试辅助,不影响业务。bridge.js 补一行:

```js
if (evt.type === 'state' || evt.type === 'refresh') window.BridgeTest.reloadCount = (window.BridgeTest.reloadCount || 0) + 1;
```

测试改断言 `window.BridgeTest.reloadCount >= 2`。watcher 触发:`touch <项目路径>/.fenix/<任意已有文件>`(从 /api/projects 响应的 path 字段取)。

- [ ] **Step 6: Commit**

```bash
git add core/dashboard/static/v2/ tests/v2/
git commit -m "v2-overview: 概览页(统计块+项目卡片+启停删+SSE 重拉)"
```

---

### Task 6: project.json — SPEC 列表页

**Files:**
- Create: `core/dashboard/static/v2/pages/project.json`
- Test: `tests/v2/project.spec.js`

**Interfaces:**
- Consumes: `Adapters.adaptSpecs`(Task 4)、`sse:state` 广播、componentId `spec-crud`、Task 5 的 http 动作按钮模式
- Produces: SPEC 行数据 `rows`(含 children 树行);路由跳转 `#/spec/:project/:name` 链接(Task 7 依赖)

- [ ] **Step 1: 写失败测试**

`tests/v2/project.spec.js`(以真实项目 `<PROJECT>` 落笔):

```js
import { test, expect } from '@playwright/test';
test('SPEC 列表:表头、树形分组、跳转链接', async ({ page }) => {
  await page.goto('/v2/index.html#/project/<PROJECT>');
  await expect(page.getByText('状态', { exact: true })).toBeVisible({ timeout: 10000 });
  // fix 树:若该项目有 fix- 子 SPEC,断言子行缩进渲染在父行下方(children 展开)
  // 行内下拉菜单:第一行出现"呼叫 Admin"按钮
  await expect(page.getByText('呼叫 Admin').first()).toBeVisible();
});
test('SPEC 列表:关键词过滤', async ({ page }) => {
  await page.goto('/v2/index.html#/project/<PROJECT>');
  await page.getByPlaceholder(/搜索|关键词/).fill('<已知SPEC名片段>');
  await expect(page.getByText('<已知SPEC名片段>').first()).toBeVisible();
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd tests/v2 && npx playwright test project.spec.js`
Expected: FAIL

- [ ] **Step 3: 实现 project.json**

核心结构:

```jsonc
{
  "type": "page",
  "title": "${params[0]}",
  "body": [{
    "type": "crud", "id": "spec-crud", "name": "spec-crud",
    "api": { "url": "/api/specs?project=${params[0]}",
             "adaptor": "return { items: window.Adapters.adaptSpecs(payload || []) , total: (payload || []).length }" },
    "columns": [
      /* behavior.md §2 的 8 列,逐字落笔。前两列完整示例,其余 6 列同构:
         状态列 = mapping badge(键值对取 behavior.md §2 状态枚举);
         名称列 = 链接 tpl(树行子项缩进由 children 机制自动处理,tpl 内不再加缩进) */
      { "name": "status", "label": "状态", "type": "mapping",
        "map": { "planning": "<span class='label label-info'>规划中</span>",
                 "running": "<span class='label label-primary'>运行中</span>",
                 "verifying": "<span class='label label-warning'>验证中</span>",
                 "done": "<span class='label label-success'>已完成</span>",
                 "error": "<span class='label label-danger'>失败</span>",
                 "*": "<span class='label label-default'>${status}</span>" } },
      { "name": "name", "label": "名称", "type": "tpl",
        "tpl": "<a href='#/spec/${params[0]}/${name}'>${name}</a>" }
      /* 优先级、创建时间、任务进度(progress tpl)、验证、耗时、文档链接:
         字段名与取值按 behavior.md §2 逐字补全 */
    ],
    "filter": { "title": "", "mode": "inline", "submitOnChange": true,
      "body": [ /* 关键词 inputText(name:kw) / 状态 select / 类型 select;
                   过滤行为 behavior.md §2:前端对 adaptSpecs 输出再过滤,
                   由 crud 的 filter + item 数据内联实现(在 api.adaptor 里读取表单值过滤,
                   或改用 crud 的 filter 配合 combineNum——以能跑通为准,任选实现并注释) */ ] },
    "onEvent": { "sse:state": { "actions": [{ "actionType": "reload", "componentId": "spec-crud" }] } },
    "itemActions": [],   // 行内按钮放 columns 最后一列 operations,便于树行继承
    "footable": { "expand": "all" }   // 树行 children 展开;若 6.13 经典 table 树行默认支持 expandConfig 则用之
  }]
}
```

行内 dropdown(替代右键菜单,设计 §4):

```jsonc
{ "type": "dropdown-button", "label": "操作", "buttons": [
  { "type": "button", "label": "呼叫 Admin", "onEvent": { "click": { "actions": [
      { "actionType": "ajax", "args": { "api": { "method": "post", "url": "/api/spec-admin-invoke",
          "data": { "project": "${params[0]}", "spec": "${name}" } } } },
      { "actionType": "dialog", "args": { "dialog": { /* Task 9 完成后替换为 RunStream admin 弹窗;本任务先 toast "已发起" */ } } }
  ] } } },
  { "type": "button", "label": "调优先级", "onEvent": { "click": { "actions": [
      { "actionType": "dialog", "args": { "dialog": { "title": "调整优先级", "body": {
          "type": "form", "api": { "method": "post", "url": "/api/spec-priority",
            "data": { "project": "${params[0]}", "spec": "${name}", "priority": "${priority}" } },
          "body": [{ "type": "input-number", "name": "priority", "label": "优先级", "required": true }] } } } }
  ] } } },
  { "type": "button", "label": "删除", "confirmText": "删除后该项目将停止并忽略,确认?",
    "onEvent": { "click": { "actions": [
      { "actionType": "ajax", "args": { "api": { "method": "post", "url": "/api/spec-delete",
          "data": { "project": "${params[0]}", "spec": "${name}" } } } },
      { "actionType": "reload", "componentId": "spec-crud" } ] } } }
] }
```

注:`/api/spec-priority`、`/api/spec-delete` 的请求体字段名以 behavior.md §1 为准调 `data`;优先级枚举若为 select 则换 `input-select`。409(运行中)由 AMIS ajax 默认错误 toast 呈现。

error 子行 + Why:名称列下方行展开(`expandedRowClassName` 不可用则用列模板内嵌),实现为"详情"dropdown 项打开 Dialog:lazy 加载 `/api/specs/<spec>` 的 error 与 why 字段(懒加载端点与字段名 behavior.md §5),Dialog 内"清除错误"按钮 POST `/api/spec-error-clear` 后 reload `spec-crud`。

- [ ] **Step 4: 运行确认通过**

Run: `cd tests/v2 && npx playwright test project.spec.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/dashboard/static/v2/pages/project.json tests/v2/
git commit -m "v2-project: SPEC 列表页(8 列+过滤+fix 树+行内操作)"
```

---

### Task 7: spec-detail.json — SPEC 详情页

**Files:**
- Create: `core/dashboard/static/v2/pages/spec-detail.json`
- Test: `tests/v2/spec-detail.spec.js`

**Interfaces:**
- Consumes: `Adapters.adaptSpecDetail`、`sse:detail/sse:state`、componentId `spec-detail`、路由参数 `${params[0]}/${params[1]}`
- Produces: 时间轴节点点击 → 打开运行记录弹窗(Task 8 的 RunStream run 模式 Dialog)

- [ ] **Step 1: 写失败测试**

```js
import { test, expect } from '@playwright/test';
test('详情页:验证卡 + 4 页签渲染', async ({ page }) => {
  await page.goto('/v2/index.html#/spec/<PROJECT>/<SPEC>');
  await expect(page.getByText('验证', { exact: false }).first()).toBeVisible({ timeout: 10000 });
  for (const tab of ['时间轴', '场景', 'Bug', '截图']) {
    await page.getByRole('tab', { name: new RegExp(tab) }).click();
    await expect(page.locator('[role=tabpanel] , .amis-tabs-pane').first()).toBeVisible();
  }
});
```

(页签名以实际 JSON 为准;写测试时对齐。)若有真实 run 数据,断言时间轴 `amis-timeline` 节点数 ≥1。

- [ ] **Step 2: 运行确认失败** → `npx playwright test spec-detail.spec.js` FAIL

- [ ] **Step 3: 实现 spec-detail.json**

```jsonc
{
  "type": "page",
  "body": [{
    "type": "service", "id": "spec-detail", "name": "spec-detail",
    "api": { "url": "/api/specs/${params[0]}/${params[1]}", "adaptor": "return window.Adapters.adaptSpecDetail(payload)" },
    "onEvent": {
      "sse:detail": { "actions": [
        // behavior.md §0:detail 帧带 spec 名,仅当与当前路由一致才刷新
        { "actionType": "custom", "script": "const d = event.data; if (d && d.spec === window.V2.route().params[1]) true; else false;" },
        { "actionType": "reload", "componentId": "spec-detail" } ] },
      "sse:state":  { "actions": [{ "actionType": "reload", "componentId": "spec-detail" }] }
    },
    "body": [
      { /* 验证结论卡:verdict.summary 计数(已数字化)+ 验证进度 + 任务清单 checklist tpl */ },
      { "type": "tabs", "tabs": [
        { "title": "时间轴", "body": { "type": "timeline", "source": "${timeline}",
            /* 节点点击开运行记录弹窗:
               { "type": "button", "visible": false, "onEvent": { "node-click": ... } }
               简化:节点 title 渲染为链接 tpl,href="#";onClick 动作 dialog(Task 8 填入) */ } },
        { "title": "场景", "body": { "type": "table", "source": "${scenarios}", "columns": [/* behavior.md §1 断言明细 */] } },
        { "title": "Bug",   "body": { "type": "table", "source": "${bugs}", "columns": [/* behavior.md §1 */] } },
        { "title": "截图",  "body": { "type": "grid", "source": "${screenshots}", "columns": 4,
            "columnClassName": "p-2", /* 每格 {type:'image', src:'/screenshots/${params[0]}/${params[1]}/${file}', thumbMode:'cover'} 点击放大 AMIS image preview 内建 */ } }
      ] }
    ]
  }]
}
```

时间轴节点点击弹窗的动作骨架(本任务先弹占位 Dialog,Task 8 换 RunStream):

```jsonc
{ "actionType": "dialog", "args": { "dialog": { "title": "运行记录", "size": "lg",
    "body": { "type": "tpl", "tpl": "运行记录弹窗待 Task 8 接入 run_id=${runId}" } } } }
```

- [ ] **Step 4: 运行确认通过** → `npx playwright test spec-detail.spec.js` PASS

- [ ] **Step 5: Commit**

```bash
git add core/dashboard/static/v2/pages/spec-detail.json tests/v2/
git commit -m "v2-spec-detail: 详情页(验证卡+4 页签+SSE detail 刷新)"
```

---

### Task 8: run-stream.js — 运行记录弹窗 custom 组件

**Files:**
- Modify: `core/dashboard/static/v2/run-stream.js`(替换占位)
- Modify: `core/dashboard/static/v2/pages/spec-detail.json`(时间轴节点点击接入)
- Test: `tests/v2/run-stream.spec.js`

**Interfaces:**
- Consumes: behavior.md §3(watch 协议/事件形态/粘性滚动/token 合并——**行为唯一权威**)、SSE hello cid(Task 3 的 `window.Bridge` 持有 `_es`;cid 从 hello 帧存 `window.Bridge.cid`)
- Produces: AMIS custom 组件 `window.RunStream.mount(dom, props)`,props 约定见计划头部「run-stream.js custom 协议」;Task 9 以 `mode:'admin'` 复用

- [ ] **Step 1: 写失败测试**

run 数据是动态的;测试采用"快照回放"策略不可行(SSE 端点直连后端)。测试策略:打开一个**已知有 run 记录的 spec** 的时间轴节点,断言弹窗渲染出事件流内容(事件文本以 fixture 已知内容落笔,如助手消息片段):

```js
import { test, expect } from '@playwright/test';
test('运行记录弹窗:打开即拉取尾部 300 条并渲染事件流', async ({ page }) => {
  await page.goto('/v2/index.html#/spec/<PROJECT>/<SPEC>');
  await page.getByText(/时间轴|查看运行/).first().click();
  // 断言弹窗出现且流内容非空
  const dlg = page.locator('.amis-dialog');
  await expect(dlg).toBeVisible({ timeout: 10000 });
  await expect(dlg.getByText(/.+/).first()).toBeVisible();
});
```

- [ ] **Step 2: 运行确认失败** → FAIL(弹窗内容为 Task 7 占位 tpl)

- [ ] **Step 3: 实现 run-stream.js**

行为规格 behavior.md §3 逐条落地(该节是唯一权威,以下为结构骨架):

```js
(function () {
  function mount(dom, props) {
    const { mode, runId, project, spec } = props;
    const cid = window.Bridge && window.Bridge.cid;
    let es = null, watchId = null;
    const state = { events: [], sticky: true };

    dom.innerHTML = '<div class="rs-stream" style="overflow-y:auto;max-height:60vh"></div>';
    const view = dom.querySelector('.rs-stream');

    // 粘性滚动(behavior.md §3:接近底部才吸底,用户上翻释放;阈值 40px)
    view.addEventListener('scroll', () => {
      state.sticky = view.scrollTop + view.clientHeight >= view.scrollHeight - 40;
    });

    function appendEvents(evs) { /* behavior.md §3:
      - 逐条按 type 渲染(assistant/user/tool_use/tool_result/error/result/system)
      - thinking_tokens 相邻合并规则(§3)
      - marked 渲染 assistant 文本(转义原始 HTML,§3)
      - 渲染后 state.sticky && (view.scrollTop = view.scrollHeight) */ }

    async function boot() {
      if (mode === 'admin') { /* behavior.md §4 状态机:POST /api/spec-admin-invoke(project,spec)
            → 409:toast 错误并卸载;成功:进入等待,每 5s GET /api/specs/<spec> 解析 admin_run_id
            → 拿到 runId 后切 run 模式;超时上限按 §4 */ }
      if (!runId) return;
      // 尾部快照
      const r = await fetch('/api/runs/' + runId + '?tail=300');
      const data = await r.json();   // 字段形态 behavior.md §3
      state.events = data.events || [];
      render();
      // watch 订阅
      await fetch('/api/runs/' + runId + '/watch?cid=' + cid, { method: 'POST' });
      es = new EventSource('/api/stream');
      es.onmessage = (e) => {
        const evt = JSON.parse(e.data || '{}');
        if (evt.type === 'run_events' && evt.run_id === runId) {
          if (evt.reset) { state.events = evt.events || []; render(); }
          else { state.events.push(...(evt.events || [])); render(); }
        }
      };
    }

    function dispose() {
      if (runId && cid) fetch('/api/runs/' + runId + '/watch?cid=' + cid, { method: 'DELETE' });
      es && es.close();
    }

    boot();
    props.onDispose = dispose;   // Dialog 关闭时由外层调用
    return { dispose };
  }

  window.RunStream = {
    register() { /* 用 amisLib.custom 等价物:在 app.js embed 前注册
      amisRequire('amis').Renderer({ type: 'run-stream', autoVar: true }, function () {
        return { mount: ... }   // 若 SDK custom 注册 API 受限,退路:onMount 字符串里调 window.RunStream.mount(dom, props)
      }); */ },
    mount,
  };
})();
```

**接入选型(定案,不留两案):** 不注册新渲染器;Dialog body 用原生 `type: "custom"` + 字符串 onMount 调 `window.RunStream.mount(dom, props)`,关闭清理挂 Dialog 的 `onEvent.close` → `script: "window.RunStream.active && window.RunStream.active.dispose()"`(mount 时写 `window.RunStream.active = instance`)。Task 7 的时间轴点击动作替换为:

```jsonc
{ "actionType": "dialog", "args": { "dialog": { "title": "运行记录 ${runId}", "size": "lg",
  "body": { "type": "custom",
    "onMount": "(dom, data, onChange, props) => { window.RunStream.active = window.RunStream.mount(dom, Object.assign({}, data, { mode: 'run', runId: data.runId })); }" },
  "onEvent": { "close": { "actions": [{ "actionType": "custom",
      "script": "window.RunStream.active && window.RunStream.active.dispose()" }] } } } } }
```

- [ ] **Step 4: 运行确认通过**

Run: `cd tests/v2 && npx playwright test run-stream.spec.js`
Expected: PASS;并手动(Playwright 驱动)验证:流滚动中上翻后新事件到达不跳底、回滚到底恢复吸底。

- [ ] **Step 5: Commit**

```bash
git add core/dashboard/static/v2/run-stream.js core/dashboard/static/v2/pages/spec-detail.json tests/v2/
git commit -m "v2-run-stream: 运行记录弹窗 custom(watch+增量+粘性滚动+token 合并)"
```

---

### Task 9: admin 处置弹窗 + SPEC 文档弹窗

**Files:**
- Modify: `core/dashboard/static/v2/pages/project.json`(呼叫 Admin 接 RunStream admin 模式)
- Create: `core/dashboard/static/v2/pages/` 内联文档弹窗(project.json 内,不新增文件)
- Test: `tests/v2/admin-doc.spec.js`

**Interfaces:**
- Consumes: `RunStream.mount(mode:'admin')`(Task 8)、behavior.md §4(admin 状态机)与 §1(spec-doc 端点 404 语义)
- Produces: 项目页/详情页可用的两个弹窗成品

- [ ] **Step 1: 写失败测试**

```js
import { test, expect } from '@playwright/test';
test('文档弹窗:三页签懒加载,不存在的 spec 走 404 提示分支', async ({ page }) => {
  await page.goto('/v2/index.html#/project/<PROJECT>');
  await page.getByText('文档').first().click();
  const dlg = page.locator('.amis-dialog');
  await expect(dlg).toBeVisible();
  // behavior.md §1:spec-doc 对不在 STATE.md 的 spec 返回 404 → 显示"未找到文档"
  // (用 fixture 中已知无文档的 spec 落笔;有文档 spec 断言"需求背景"页签内容非空)
});
```

admin 处置弹窗的真实流需触发 admin invoke(会真实呼叫 Admin,测试环境不雅)。测试降级:断言点击"呼叫 Admin"后弹窗出现且显示等待态文案(behavior.md §4 初始等待态),随后关闭即 DELETE watch(用 page.route 拦截断言)。

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现两弹窗**

**admin 弹窗(project.json 呼叫 Admin 按钮的 dialog 替换 Task 6 占位):**

```jsonc
{ "actionType": "dialog", "args": { "dialog": { "title": "Admin 处置", "size": "lg",
  "body": { "type": "custom",
    "onMount": "(dom, data, onChange, props) => { window.RunStream.active = window.RunStream.mount(dom, Object.assign({}, data, { mode: 'admin', project: data.project, spec: data.spec, events: data.adminEvents || [] })); }" },
  "onEvent": { "close": { "actions": [{ "actionType": "custom",
      "script": "window.RunStream.active && window.RunStream.active.dispose()" }] } } } } }
```

admin 模式状态机在 run-stream.js 的 boot() 按 behavior.md §4 实现(409 toast、5s 轮询、admin_run_id 解析、实时流切换、关闭清理)。

**文档弹窗(project.json "文档" 列 → Dialog + 3 tabs):**

```jsonc
{ "type": "dialog-button", "label": "文档", "dialog": { "title": "SPEC 文档", "size": "lg",
  "body": { "type": "tabs", "tabs": [
    { "title": "需求背景", "mountOnEnter": true, "unmountOnExit": false,
      "body": { "type": "service", "api": { "url": "/api/spec-doc?project=${params[0]}&spec=${name}&doc=proposal",
        "adaptor": "return payload && payload.found ? payload : { __failed: true }" },
        "body": { "type": "tpl", "tpl": "${content | raw}" } } },
    { "title": "设计", "mountOnEnter": true, "body": { /* 同上 doc=design */ } },
    { "title": "任务清单", "mountOnEnter": true, "body": { /* 同上 doc=tasks */ } } ] } }
```

- [ ] **Step 4: 运行确认通过** → `npx playwright test admin-doc.spec.js` PASS

- [ ] **Step 5: Commit**

```bash
git add core/dashboard/static/v2/pages/project.json core/dashboard/static/v2/run-stream.js tests/v2/
git commit -m "v2-admin-doc: Admin 处置弹窗接入 + SPEC 文档弹窗"
```

---

### Task 10: config.json — 配置页(编辑豁免 SSE)

**Files:**
- Create: `core/dashboard/static/v2/pages/config.json`
- Test: `tests/v2/config.spec.js`

**Interfaces:**
- Consumes: `Adapters.adaptConfig/buildConfigPayload`、behavior.md §6(结构/校验/回退)
- Produces: 保存成功 toast(5s 窗口,全局约束)

- [ ] **Step 1: 写失败测试**

```js
import { test, expect } from '@playwright/test';
test('配置页:加载回显 → 修改并行度 → 保存 → 回显新值', async ({ page }) => {
  await page.goto('/v2/index.html#/config');
  await expect(page.getByText('LLM Provider').first()).toBeVisible({ timeout: 10000 });
  const num = page.locator('input[type=number]').first();
  const before = await num.inputValue();
  await num.fill(String(Number(before || 2) + 1));
  await page.getByRole('button', { name: '保存' }).click();
  await expect(page.getByText(/保存成功|已保存/)).toBeVisible({ timeout: 6000 }); // 成功 toast 5s 窗口
  await page.reload();
  await page.goto('/v2/index.html#/config');
  await expect(num).toHaveValue(String(Number(before || 2) + 1));
});
```

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现 config.json**

```jsonc
{
  "type": "page",
  "body": [{
    "type": "form", "id": "config-form", "name": "config-form",
    "title": "",
    "api": { "method": "post", "url": "/api/config",
             "data": { "&": "$$" },   // 提交前经 buildConfigPayload 合并,见 onSubmit
             "adaptor": "return { status: 0 }" },
    "loadDefaultValues": true,
    "data": { "&": "$$" },
    "dataLoader": "...",   // 不用 dataLoader;初始值走 service 预载(见下)
    "body": [
      /* 编辑豁免(behavior.md §0/§9):config 页不监听任何 sse 广播刷新;
         且 form 前置一个 service 仅拉初始值,拉完即止,不自动刷新 */
      { "type": "tabs", "tabs": [
        { "title": "LLM Provider", "body": { "type": "combo", "name": "llm.providers",
            /* 字段名 behavior.md §6;可增删项,每项结构逐字照 behavior.md §6 落笔: */
            "items": [{ "type": "grid", "columns": [
              { "md": 3, "body": { "type": "input-text", "name": "name", "label": "名称" } },
              { "md": 5, "body": { "type": "input-text", "name": "base_url", "label": "Base URL" } },
              { "md": 4, "body": { "type": "input-password", "name": "api_key", "label": "API Key" } }
            ] },
            { "type": "input-text", "name": "model", "label": "默认模型" },
            { "type": "combo", "name": "env", "label": "自定义环境变量", "multiple": true, "removable": true,
              "items": [{ "type": "grid", "columns": [
                { "md": 4, "body": { "type": "input-text", "name": "key" } },
                { "md": 8, "body": { "type": "input-text", "name": "value" } } ] }] }]
          } },
        { "title": "Agent 模型", "body": { "type": "input-array", "name": "agent_chain",
            /* 链结构 behavior.md §6(可排序多行+角色级缺省);拖拽排序由 input-array 内建 sortable */
            "sortable": true, "items": { "type": "grid", "columns": [
              { "md": 4, "body": { "type": "input-select", "name": "role",
                  /* 选项枚举按 behavior.md §6 角色 */ "options": [] } },
              { "md": 8, "body": { "type": "input-text", "name": "model",
                  "placeholder": "留空用 provider 默认" } } ] },
            "validate": "/* 链完整性校验:调 behavior.md §6 规则(必填角色齐全、模型名存在于 provider),
                            实现为 window.Adapters.validateChain(value) 返回 true|错误文案,
                            并在 Task 4 adapters.js 中补导出该函数 */" } },
        { "title": "并行度", "body": { "type": "input-group",
            /* 4 个 input-number,字段名逐字 behavior.md §6 */ "body": [
              { "type": "input-number", "name": "max_parallel_1", "label": "并行度1" },
              { "type": "input-number", "name": "max_parallel_2", "label": "并行度2" },
              { "type": "input-number", "name": "max_parallel_3", "label": "并行度3" },
              { "type": "input-number", "name": "max_parallel_4", "label": "并行度4" } ] } },
        { "title": "审批", "body": { "type": "radios", "name": "approval_mode",
            /* 枚举 behavior.md §6 */ "options": [] } },
        { "title": "主题", "body": { "type": "tpl",
            "tpl": "v2 当前仅提供深色主题;浅色主题将在替换老版后按需评估。" } }
      ] }
    ],
    "onEvent": {
      "submitSucc": { "actions": [{ "actionType": "toast", "args": { "msgType": "success", "msg": "保存成功" } }] }
    }
  }]
}
```

初始值:form 上方 `{"type":"service","id":"config-loader","api":{"url":"/api/config","adaptor":"return window.Adapters.adaptConfig(payload)"}}`,form 的 `data` 绑定 service 数据域(`"data": {"&": "$$"}`),确保 llm 缺失时 `providers: []` 兜底生效。提交时用 `validate` 钩子合并快照:`api.requestAdaptor` 里 `return { data: window.Adapters.buildConfigPayload(api.data, window.__configSnapshot, window.__configDefaults) }`(service adaptor 里同时写 `window.__configSnapshot`)。

- [ ] **Step 4: 运行确认通过** → `npx playwright test config.spec.js` PASS

- [ ] **Step 5: Commit**

```bash
git add core/dashboard/static/v2/pages/config.json tests/v2/
git commit -m "v2-config: 配置页(5 页签+链编辑器+三级回退+编辑豁免)"
```

---

### Task 11: 壳级告警横幅 + activities.json 运维记录页

**Files:**
- Modify: `core/dashboard/static/v2/pages/app.json`(header 加 alert-banner service)
- Create: `core/dashboard/static/v2/pages/activities.json`
- Test: `tests/v2/activities-alerts.spec.js`

**Interfaces:**
- Consumes: `Adapters.adaptAlerts/adaptActivities`、`sse:alerts/sse:admin_activities`、componentId `alert-banner`/`act-timeline`
- Produces: 壳级横幅(所有路由可见)

- [ ] **Step 1: 写失败测试**

```js
import { test, expect } from '@playwright/test';
test('运维记录页:时间线渲染 + 跨项目页签', async ({ page }) => {
  await page.goto('/v2/index.html#/activities');
  await expect(page.locator('.amis-timeline, [class*=timeline]').first()).toBeVisible({ timeout: 10000 });
});
test('告警横幅:有未处理告警时壳级出现横幅', async ({ page }) => {
  await page.goto('/v2/index.html#/overview');
  // fixture 环境若无告警则此用例 skip;有则断言横幅可见并能打开列表 Dialog 标记单条已处理
});
```

(按 fixture 实况取舍第二条用例;无告警环境用 `test.fixme` 标注并留运行手册说明。)

- [ ] **Step 2: 运行确认失败** → FAIL

- [ ] **Step 3: 实现横幅与 activities.json**

壳级 header(保留 SSE 桥组件)追加:

```jsonc
{ "type": "service", "id": "alert-banner", "name": "alert-banner",
  "api": { "url": "/api/alerts", "adaptor": "return { rows: window.Adapters.adaptAlerts(payload || []) }" },
  "onEvent": { "sse:alerts": { "actions": [{ "actionType": "reload", "componentId": "alert-banner" }] } },
  "body": { "type": "tpl", "visibleOn": "${rows.length > 0}",
    "tpl": "⚠ ${rows.length} 条未处理告警" },
  /* 整块可点 → dialog 列表:每行"标记已处理" POST /api/alerts/<id>/handled 后 reload;"全部清空" POST /api/alerts/clear */ }
```

activities.json:页签(全部/各项目,`/api/admin-activities` 与 `?project=` 参数差异见 behavior.md §7)+ Timeline 组件,`id: "act-timeline"`,监听 `sse:admin_activities` reload。

- [ ] **Step 4: 运行确认通过** → `npx playwright test activities-alerts.spec.js` PASS

- [ ] **Step 5: Commit**

```bash
git add core/dashboard/static/v2/ tests/v2/
git commit -m "v2-shell: 壳级告警横幅 + 运维记录页"
```

---

### Task 12: 全量验收 — 深链 + 双版对比

**Files:**
- Create: `tests/v2/acceptance.spec.js`
- Create: `tests/v2/RUNBOOK.md`

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 验收全绿记录;RUNBOOK(如何起服务、如何跑测试、哪些用例依赖环境实况)

- [ ] **Step 1: 写深链与回归验收脚本**

`tests/v2/acceptance.spec.js` 覆盖(设计 §7 清单):

```js
import { test, expect } from '@playwright/test';
// 1. 深链:config?tab= 直达页签;spec/:p/:s 直达详情;刷新后路由保持
test('深链 config?tab= 直达页签', async ({ page }) => {
  await page.goto('/v2/index.html#/config?tab=1');
  await page.reload();
  await expect(page.getByText('Agent 模型').first()).toBeVisible();
});
// 2. 老版并存冒烟:对 / 跑一组只读断言(列表可见、详情可见),确保并存期未破坏老版
test('老版 / 不受影响', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#tl-root')).toBeVisible({ timeout: 10000 });
});
// 3. 双版关键断言对齐:/ 与 /v2/ 各自的 SPEC 列表行数一致(±0,同数据源)
// 4. run 弹窗三态(滚动吸底/上翻释放/token 合并)在真实 run 上抽查
// 5. admin 弹窗等待态出现后关闭,断言 DELETE watch 发出(page.route 拦截)
// 6. 全程收集 pageerror,断言零 JS 错误
```

- [ ] **Step 2: 全量跑绿**

Run: `cd tests/v2 && npx playwright test`
Expected: 全部 PASS;写 RUNBOOK.md(启动命令、fixture 依赖、fixme 用例清单)。

- [ ] **Step 3: 用户人工过一遍 /v2/**

向用户报告:请人工浏览 `/v2/` 全功能确认;此步是验收标准的一部分(设计 §7),不得跳过。

- [ ] **Step 4: Commit**

```bash
git add tests/v2/
git commit -m "v2-acceptance: 全量验收脚本 + 运行手册"
```

---

### Task 13: 替换主入口(需用户最终确认后执行)

**Files:**
- Modify: `core/dashboard/server.py:225-226`(仅此两行:`path == "/"` 改为 serve `v2/index.html`)

**Interfaces:**
- Consumes: Task 12 全绿 + 用户明确说"替换"
- Produces: `/` 即新版;老版保留在 `/legacy/`(server.py 静态目录内把 app.js 入口 html 复制为 legacy.html——不动原文件,新增一个 legacy.html 引用原 app.js/style.css)

- [ ] **Step 1: 确认用户已批准替换**

向用户复述:Task 12 全绿 + 人工浏览通过。得到明确"替换"指令才继续。

- [ ] **Step 2: 新增 legacy.html 并切换根路径**

`core/dashboard/static/legacy.html`:复制现 index.html 内容(仅换 title 注明 legacy)。server.py:225-226:

```python
if path == "/" or path == "/index.html":
    self._serve_static("v2/index.html")
elif path == "/legacy.html":
    self._serve_static("legacy.html")
```

这是全计划唯一一处后端改动(设计 §2 的"替换 = 单独小提交")。

- [ ] **Step 3: 复跑验收**

Run: `cd tests/v2 && npx playwright test`(config baseURL 已是 `http://127.0.0.1:8787`,把 smoke/overview 等用例中 `/v2/index.html` 前缀换为 `/` —— 在 RUNBOOK 记录此切换;或新增一个 `base-url.spec.js` 对 `/` 复跑核心冒烟)
Expected: PASS。

- [ ] **Step 4: Commit**

```bash
git add core/dashboard/server.py core/dashboard/static/legacy.html tests/v2/
git commit -m "v2-cutover: 主入口切换到 AMIS v2,老版保留 /legacy.html"
```
