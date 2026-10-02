// add-regression-issues-rerun 5.3：RegressionTab 定向子集按钮与子集快照标识单测。
// 运行：cd core/dashboard/static && node --test tests/regressionTab.test.mjs
// 无 jsdom：经 esbuild 把 RegressionTab（tsx 依赖链）打包为临时 ESM（react/
// react-dom/antd/dayjs 保持 external），services/dashboard 以 onResolve 插件
// 指向桩模块（SSR 不跑 effect，桩只为模块链完整）；react-dom/server SSR 渲染
// 断言控件形态，事件接线以元素树断言（renderToStaticMarkup 丢 props，故
// 遍历 React 元素树取 onClick）。
// 覆盖（任务 5.3 口径）：
// - 按钮渲染位置（自动修复 → 定向子集 → 全量）与 primary 形态；
// - 全绿时禁用 + 有异常行（failures/long_tests）时可用；timeout 整体超时
//   伪行不计入可用性；Tooltip 可用态/禁用态文案切换；
// - 点击接线（onClick → onTriggerIssues）；受理后等待启动过渡态与 running
//   同口径禁用（受理流转由验证引擎 web 场景实测，hooksPanel 先例）；
// - run_scope=="issues" 快照渲染「定向子集」Tag 与口径说明纯函数。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const esbuild = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { ConfigProvider } = require('antd');

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');

// services/dashboard 桩（组件 import 链完整即可；SSR 不触发数据加载）
const outdir = join(ROOT, 'node_modules', '.tmp-regression-tab-test');
const stubPath = join(outdir, 'services-stub.mjs');
const stubSource = `
export class ApiError extends Error {
  constructor(message, code, status) { super(message); this.code = code; this.status = status; }
}
export const fixRegression = async () => ({ ok: true, requested_at: '' });
export const getRegressionFixResult = async () => ({ status: 'none' });
export const getRegressionResult = async () => ({ status: 'never_run' });
export const isTriggerResultForRequest = () => false;
export const triggerRegression = async () => ({ ok: true, requested_at: '' });
export const triggerRegressionIssues = async () => ({ ok: true, requested_at: '' });
`;

const servicesStubPlugin = {
  name: 'stub-services-dashboard',
  setup(build) {
    build.onResolve({ filter: /services[\\/]dashboard$/ }, () => ({ path: stubPath }));
  },
};

let bundleUrl = null;
async function loadTab() {
  if (!bundleUrl) {
    rmSync(outdir, { recursive: true, force: true });
    mkdirSync(outdir, { recursive: true });
    writeFileSync(stubPath, stubSource, 'utf-8');
    const outfile = join(outdir, 'tab.mjs');
    await esbuild.build({
      entryPoints: [join(ROOT, 'src/pages/projects/components/RegressionTab.tsx')],
      outfile,
      bundle: true,
      format: 'esm',
      jsx: 'automatic',
      platform: 'node',
      external: ['react', 'react-dom', 'antd', 'dayjs', '@ant-design/icons'],
      alias: { '@': join(ROOT, 'src'), '@@': join(ROOT, 'src/.umi') },
      plugins: [servicesStubPlugin],
      logLevel: 'silent',
    });
    bundleUrl = pathToFileURL(outfile).href;
  }
  return import(bundleUrl);
}

function renderNode(node) {
  return renderToStaticMarkup(React.createElement(ConfigProvider, null, node));
}

/**
 * 遍历 React 元素树收集按钮与 Tooltip title（SSR 丢 props，接线断言走树）。
 * 不按 el.type 身份比对（bundle external 的 antd 与测试 require('antd') 可能
 * 非同实例），改按 props 形态识别：按钮 = 显式 disabled + 字符串 children，
 * Tooltip = 字符串 title。
 */
function collect(tree) {
  const buttons = [];
  const tooltipTitles = [];
  (function walk(el) {
    if (!el || typeof el !== 'object' || !el.props) return;
    const p = el.props;
    if ('disabled' in p && typeof p.children === 'string') buttons.push(el);
    if (typeof p.title === 'string') tooltipTitles.push(p.title);
    const kids = p.children;
    (Array.isArray(kids) ? kids : [kids]).forEach(walk);
  })(tree);
  return { buttons, tooltipTitles };
}

const ALL_GREEN = {
  status: 'passed', total: 5, passed: 5, failed: 0, errors: 0, skipped: 0,
  failures: [], long_tests: [],
};
const WITH_ISSUES = {
  status: 'failed', total: 3, passed: 1, failed: 1, errors: 0, skipped: 0,
  failures: [
    { name: 'test_a', file: 'tests/test_x.py', line: 1, time: 0.1,
      kind: 'failure', message: 'boom', classname: 'tests.test_x' },
  ],
  long_tests: [],
};

function baseOpts(overrides = {}) {
  return {
    snapshot: WITH_ISSUES,
    running: false,
    awaitingStart: false,
    triggering: false,
    issuesTriggering: false,
    fixPending: false,
    onFix: () => {},
    onTriggerIssues: () => {},
    onTrigger: () => {},
    ...overrides,
  };
}

async function renderActions(overrides = {}) {
  const mod = await loadTab();
  // overviewActions 为无 hooks 纯渲染函数：直接调用取回 JSX 元素树，
  // createElement 只得组件元素（walk 不展开渲染产物）
  const tree = mod.overviewActions(baseOpts(overrides));
  return { mod, html: renderNode(tree), ...collect(tree) };
}

// ── 渲染位置与 primary 形态 ──────────────────────────────────────────

test('按钮行顺序：自动修复 → 定向子集 → 全量（定向子集位于全量左侧）', async () => {
  const { mod, html } = await renderActions();
  const iFix = html.indexOf('自动修复回归问题');
  const iIssues = html.indexOf(mod.ISSUES_BTN_TEXT);
  const iFull = html.indexOf('立即执行全量回归');
  assert.ok(iFix >= 0, '自动修复按钮在场');
  assert.ok(iIssues > iFix, '定向子集按钮位于自动修复右侧');
  assert.ok(iFull > iIssues, '定向子集按钮位于全量按钮左侧');
});

test('定向子集按钮 primary 形态（蓝底白字）', async () => {
  const { buttons } = await renderActions();
  const issues = buttons.find((b) => b.props.children === '立即执行错误/长耗时回归');
  assert.ok(issues, '定向子集按钮在场');
  assert.equal(issues.props.type, 'primary');
});

// ── 可用性机械判定与 Tooltip 文案 ────────────────────────────────────

test('全绿快照：定向子集按钮禁用，Tooltip 为「无异常用例可重跑」', async () => {
  const { mod, buttons, tooltipTitles } = await renderActions({
    snapshot: ALL_GREEN,
  });
  const issues = buttons.find((b) => b.props.children === mod.ISSUES_BTN_TEXT);
  assert.equal(issues.props.disabled, true);
  // Tooltip 弹层为悬停 portal，静态 SSR 不落 HTML；断言元素树上的 title
  assert.ok(tooltipTitles.includes(mod.ISSUES_BTN_DISABLED_TOOLTIP));
});

test('有失败行：按钮可用，Tooltip 为回退行为预告', async () => {
  const { mod, buttons, tooltipTitles } = await renderActions();
  const issues = buttons.find((b) => b.props.children === mod.ISSUES_BTN_TEXT);
  assert.notEqual(issues.props.disabled, true);
  assert.ok(tooltipTitles.includes(mod.ISSUES_BTN_TOOLTIP));
});

test('仅长耗时行（全量通过）：按钮可用', async () => {
  const { mod, buttons } = await renderActions({
    snapshot: {
      ...ALL_GREEN,
      long_tests: [
        { name: 'test_slow', file: 'tests/test_x.py', line: 9, time: 30,
          classname: 'tests.test_x' },
      ],
    },
  });
  const issues = buttons.find((b) => b.props.children === mod.ISSUES_BTN_TEXT);
  assert.notEqual(issues.props.disabled, true, 'long_tests 非空即可用');
});

test('整体超时伪行不计入可用性（failures/long_tests 均空 → 禁用）', async () => {
  const { mod, buttons } = await renderActions({
    snapshot: { ...ALL_GREEN, status: 'timeout', duration_seconds: 120 },
  });
  const issues = buttons.find((b) => b.props.children === mod.ISSUES_BTN_TEXT);
  assert.equal(issues.props.disabled, true, '超时无可重跑的具体用例');
});

test('issuesAvailable 纯函数：机械判定口径（不含 timeout 分支）', async () => {
  const { issuesAvailable } = await loadTab();
  assert.equal(issuesAvailable(ALL_GREEN), false);
  assert.equal(issuesAvailable(WITH_ISSUES), true);
  assert.equal(issuesAvailable(null), false);
  assert.equal(
    issuesAvailable({ status: 'timeout', failures: [], long_tests: [] }),
    false,
    '整体超时伪行非用例、不计入',
  );
});

// ── 点击接线与运行态/等待启动禁用 ────────────────────────────────────

test('点击接线：onClick 即传入的 onTriggerIssues 回调', async () => {
  const { buttons } = await renderActions({
    onTriggerIssues: () => {
      throw new Error('marker');
    },
  });
  const issues = buttons.find((b) => b.props.children === '立即执行错误/长耗时回归');
  assert.throws(() => issues.props.onClick(), /marker/, 'onClick 绑定 onTriggerIssues');
});

test('受理后等待启动过渡态与 running：定向子集与全量按钮同口径禁用', async () => {
  const { mod, buttons } = await renderActions({ awaitingStart: true });
  const issues = buttons.find((b) => b.props.children === mod.ISSUES_BTN_TEXT);
  const full = buttons.find((b) => b.props.children === '等待启动…');
  assert.equal(issues.props.disabled, true, '等待启动期间禁用');
  assert.ok(full, '全量按钮进入等待启动文案');
  const { buttons: runningButtons } = await renderActions({ running: true });
  const issuesRunning = runningButtons.find(
    (b) => b.props.children === mod.ISSUES_BTN_TEXT,
  );
  assert.equal(issuesRunning.props.disabled, true, '运行期间禁用');
});

// ── 子集快照标识 ────────────────────────────────────────────────────

test('run_scope=="issues" 快照渲染「定向子集」Tag；全量快照不渲染', async () => {
  const mod = await loadTab();
  const subsetHtml = renderNode(
    mod.statusTagRow({ ...ALL_GREEN, run_scope: 'issues' }),
  );
  assert.ok(subsetHtml.includes(mod.SUBSET_TAG_TEXT), '子集快照展示「定向子集」Tag');
  const fullHtml = renderNode(mod.statusTagRow(ALL_GREEN));
  assert.ok(!fullHtml.includes(mod.SUBSET_TAG_TEXT), '全量快照不渲染该 Tag');
});

test('isSubsetSnapshot / subsetScopeNote 纯函数口径', async () => {
  const mod = await loadTab();
  assert.equal(mod.isSubsetSnapshot({ run_scope: 'issues' }), true);
  assert.equal(mod.isSubsetSnapshot(ALL_GREEN), false, '无 run_scope 即全量口径');
  assert.equal(mod.isSubsetSnapshot(null), false);
  const note = mod.subsetScopeNote({ run_scope: 'issues' });
  assert.ok(note.includes('子集口径'), '说明含子集口径提示');
  assert.ok(note.includes('全量'), '说明含恢复指引（再跑全量即恢复）');
  assert.equal(mod.subsetScopeNote(ALL_GREEN), '', '全量快照无说明（空串不渲染）');
});

// ── 真组件模块链完整性（services 桩下 guide 态 SSR 不抛异常）─────────

test('真组件 SSR（guide 态）：新 services import 链完整、渲染不抛异常', async () => {
  const mod = await loadTab();
  const { App } = require('antd');
  const html = renderToStaticMarkup(
    React.createElement(
      ConfigProvider,
      null,
      React.createElement(
        App,
        null,
        React.createElement(mod.default, { project: 'p', active: true }),
      ),
    ),
  );
  assert.ok(html.includes('尚未执行过全量回归'), '无快照走引导态');
});
