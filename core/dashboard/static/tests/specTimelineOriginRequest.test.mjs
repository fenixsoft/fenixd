// 立项原话引用块渲染单测（add-timeline-origin-request 任务 3.3）。
// 运行：cd core/dashboard/static && node --test tests/specTimelineOriginRequest.test.mjs
// 无 jsdom：经 esbuild 把 SpecTimeline（tsx 依赖链）打包为临时 ESM（react/
// react-dom/antd/dayjs/@ant-design/icons 保持 external），services/dashboard
// 以 onResolve 插件指向桩模块（SSR 不跑 effect，桩只为模块链完整）；
// react-dom/server SSR 渲染断言：state 节点携带非空 origin_request 时渲染
// 原话引用块（.spec-origin-request-quote，pre-wrap 保留换行 + 次级引用边框），
// 字段缺失/空字符串/其余节点不携带时不渲染任何引用块结构。
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

// services/dashboard 桩（组件 import 链完整即可；SSR 不触发数据加载）。
// 具名导出 = 打包链上被作值消费的名字（类型 import 由 esbuild 擦除）。
const outdir = join(ROOT, 'node_modules', '.tmp-origin-request-test');
const stubPath = join(outdir, 'services-stub.mjs');
const stubSource = `
export class ApiError extends Error {
  constructor(message, code, status) { super(message); this.code = code; this.status = status; }
}
export const request = async () => ({});
export const STREAM_URL = '/api/stream';
export const statusMeta = (status) => ({ label: status || '未知', tone: 'muted' });
export const getSpecDoc = async () => ({ content: '', missing: true });
export const getRunTail = async () => ({ events: [], total: 0 });
export const registerRunWatch = () => () => {};
export const fixRegression = async () => ({ ok: true });
export const getRegressionFixResult = async () => ({ status: 'none' });
export const getRegressionResult = async () => ({ status: 'never_run' });
`;

const servicesStubPlugin = {
  name: 'stub-services-dashboard',
  setup(build) {
    build.onResolve({ filter: /services[\\/]dashboard$/ }, () => ({ path: stubPath }));
  },
};

// 构建期生成的 css（claude-msg/index.ts 的 './tailwind.gen.css'，umi 流水线
// 产物、磁盘上不存在）以空模块顶替——SSR 断言不消费样式表内容
const generatedCssStubPlugin = {
  name: 'stub-generated-css',
  setup(build) {
    build.onResolve({ filter: /\.gen\.css$/ }, (args) => ({ path: args.path, namespace: 'css-stub' }));
    build.onLoad({ filter: /.*/, namespace: 'css-stub' }, () => ({ contents: '', loader: 'css' }));
  },
};

let bundleUrl = null;
async function loadTimeline() {
  if (!bundleUrl) {
    rmSync(outdir, { recursive: true, force: true });
    mkdirSync(outdir, { recursive: true });
    writeFileSync(stubPath, stubSource, 'utf-8');
    const outfile = join(outdir, 'timeline.mjs');
    await esbuild.build({
      entryPoints: [join(ROOT, 'src/pages/projects/components/SpecTimeline.tsx')],
      outfile,
      bundle: true,
      format: 'esm',
      // ESM 外置裸说明符下动态 require 不可用，注入 createRequire 兜底
      // （先例 hooksPanel.test.mjs：markdown 链 react-syntax-highlighter 的 CJS require）
      banner: {
        js: "import { createRequire as __cr } from 'node:module'; const require = __cr(import.meta.url);",
      },
      jsx: 'automatic',
      platform: 'node',
      external: ['react', 'react-dom', 'antd', 'dayjs', '@ant-design/icons', 'react-markdown', 'remark-gfm'],
      alias: { '@': join(ROOT, 'src'), '@@': join(ROOT, 'src/.umi') },
      plugins: [servicesStubPlugin, generatedCssStubPlugin],
      logLevel: 'silent',
    });
    bundleUrl = pathToFileURL(outfile).href;
  }
  return import(bundleUrl);
}

const QUOTE = 'spec-origin-request-quote';
const ORIGIN_TEXT = '给时间轴加上立项原话展示，让 SPEC 能回看当初随口说的那句话\n第二行保持换行\n';

function stateNode(overrides = {}) {
  return {
    kind: 'state',
    time: '2026-09-08T12:00:00.000000Z',
    from: 'drafted',
    to: 'ready',
    reason: '',
    backward: false,
    ...overrides,
  };
}

async function renderTimelineHtml(items) {
  const mod = await loadTimeline();
  return renderToStaticMarkup(
    React.createElement(
      ConfigProvider,
      null,
      React.createElement(mod.default, {
        timeline: items,
        isMobile: false,
        name: 'demo',
        cancelNotices: {},
        onCancelRun: () => {},
        onViewRecord: () => {},
        onOpenVerificationReport: () => {},
      }),
    ),
  );
}

test('state 节点携带非空 origin_request：渲染引用块（pre-wrap + 引用边框 + 原文全文）', async () => {
  const html = await renderTimelineHtml([stateNode({ origin_request: ORIGIN_TEXT })]);
  assert.ok(html.includes(QUOTE), '引用块容器（spec-origin-request-quote）必须渲染');
  assert.ok(html.includes('给时间轴加上立项原话展示'), '引用块含原话首行');
  assert.ok(html.includes('第二行保持换行'), '引用块含原话次行');
  assert.ok(html.includes('\n'), 'SSR 输出保留原文换行');
  assert.ok(html.includes('white-space:pre-wrap'), '多行原文以 pre-wrap 保留换行');
  assert.ok(html.includes('border-left:3px solid'), '次级引用边框（与回退 reason 行视觉分层）');
});

test('字段缺失：不渲染任何引用块结构', async () => {
  const html = await renderTimelineHtml([stateNode()]);
  assert.ok(!html.includes(QUOTE), '缺失 origin_request 不得出现引用块容器');
});

test('字段为空字符串：不渲染任何引用块结构', async () => {
  const html = await renderTimelineHtml([stateNode({ origin_request: '' })]);
  assert.ok(!html.includes(QUOTE), '空字符串 origin_request 不得出现引用块容器');
});

test('仅携带字段的首个 state 节点渲染引用块；其余 state 节点不渲染', async () => {
  // 第二个 state 节点（回退打断后）不携带字段 → 全文档恰一个引用块
  const html = await renderTimelineHtml([
    stateNode({ origin_request: ORIGIN_TEXT }),
    stateNode({
      time: '2026-09-08T12:03:00.000000Z',
      from: 'testing',
      to: 'implementing',
      reason: '验证发现 bug，退回修复',
      backward: true,
    }),
  ]);
  const first = html.indexOf(QUOTE);
  const second = html.indexOf(QUOTE, first + 1);
  assert.ok(first >= 0, '首个 state 节点渲染引用块');
  assert.equal(second, -1, '未携带字段的第二个 state 节点不渲染引用块');
});

test('折叠链节点携带 origin_request：同样渲染引用块（链上首个转移即原话展示位）', async () => {
  const html = await renderTimelineHtml([
    stateNode({
      from: 'implemented',
      to: 'pushed',
      chain: ['implemented', 'testing', 'verified', 'done', 'pushed'],
      origin_request: ORIGIN_TEXT,
    }),
  ]);
  assert.ok(html.includes(QUOTE), '折叠链节点渲染引用块');
  assert.ok(html.includes('给时间轴加上立项原话展示'));
});

test('run 节点不受影响：不渲染引用块', async () => {
  const html = await renderTimelineHtml([
    {
      kind: 'run',
      time: '2026-09-08T12:05:00+00:00',
      run_id: 'impl-1757313600',
      agent_type: 'impl',
      status: 'success',
    },
  ]);
  assert.ok(!html.includes(QUOTE), 'run 节点不渲染引用块');
});
