// 处置链事件节点渲染单测（fix-timeline-chain-nodes-invisible 任务 2.1）。
// 运行：cd core/dashboard/static && node --test tests/specTimelineChainNodes.test.mjs
// 无 jsdom：经 esbuild 把 SpecTimeline（tsx 依赖链）打包为临时 ESM（react/
// react-dom/antd/dayjs/@ant-design/icons 保持 external），services/dashboard
// 以 onResolve 插件指向桩模块（SSR 不跑 effect，桩只为模块链完整）——
// 先例 specTimelineOriginRequest.test.mjs。react-dom/server SSR 渲染断言：
// kind="chain" 节点渲染紧凑链事件卡片（此前落兜底守卫降级为裸灰点不可见），
// 六种已知 chain_kind 各自中文标签、着色、signal_type 副标签、summary 正文。
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
const outdir = join(ROOT, 'node_modules', '.tmp-chain-nodes-test');
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
export const getRunPrompt = async () => ({ run_id: '', prompt: null, recorded_at: null, project: '' });
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

// 构建期生成的 css（claude-msg/index.ts 的 './tailwind.gen.css'）以空模块顶替
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

// 后端 get_spec_timeline 链节点形态（core/dashboard/data/timeline.py：time/kind/
// chain_kind/chain_id/signature/signal_type/summary，summary 截断 200）
function chainNode(overrides = {}) {
  return {
    kind: 'chain',
    time: '2026-11-08T10:00:00',
    chain_kind: 'chain-handoff',
    chain_id: 'ec-20261108-001',
    signature: 'sig-inconclusive-loop',
    signal_type: 'inconclusive_loop',
    summary: 'Admin 转单 Arbiter：无定论循环升级（handoff_reason 摘要）',
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

// 六种已知 chain_kind → {中文标签, Tag 着色 class, 圆点着色}（设计 D2 映射表）
const KNOWN_CHAIN_KINDS = [
  ['chain-dispatch', '链派发', 'ant-tag-blue'],
  ['chain-handoff', '转单 Arbiter', 'ant-tag-gold'],
  ['chain-closed', '链闭环', 'ant-tag-green'],
  ['chain-escalated', '链终点上升', 'ant-tag-orange'],
  ['chain-recurrence', '复现', 'ant-tag-orange'],
  ['chain-choice-failed', 'choice 执行失败', 'ant-tag-red'],
];

test('六种已知 chain_kind 各自渲染中文标签 / 着色 / signal_type 副标签 / summary 正文', async () => {
  for (const [chainKind, label, tagClass] of KNOWN_CHAIN_KINDS) {
    const html = await renderTimelineHtml([
      chainNode({ chain_kind: chainKind, signal_type: 'inconclusive_loop' }),
    ]);
    assert.ok(html.includes(label), `${chainKind} 标签「${label}」必须渲染`);
    assert.ok(html.includes(tagClass), `${chainKind} Tag 着色 ${tagClass} 必须渲染`);
    assert.ok(
      html.includes('inconclusive_loop'),
      `${chainKind} signal_type 副标签必须渲染`,
    );
    assert.ok(
      html.includes('Admin 转单 Arbiter：无定论循环升级'),
      `${chainKind} summary 正文必须渲染`,
    );
    assert.ok(
      html.includes('border-radius:12px'),
      `${chainKind} 卡片复用 Bento 磁贴（12px 圆角）`,
    );
  }
});

test('裸灰点形态退役：chain 节点 listitem 含卡片内容结构（时间 + Tag + 正文）', async () => {
  const html = await renderTimelineHtml([chainNode()]);
  // 兜底守卫路径只返回 { color: 'gray' }（无 children 卡片体）——卡片体
  // 存在性以时间行 + 链标签 + 正文三要素共同证明
  assert.ok(html.includes('2026-11-08 10:00:00'), '标题行含格式化时间');
  assert.ok(html.includes('ant-tag-gold'), 'listitem 含链标签 Tag');
  assert.ok(html.includes('Admin 转单 Arbiter'), 'listitem 含 summary 正文');
  // 预设色圆点走 class（blue/green）；自定义色圆点走 CSS 变量——圆点着色与
  // 标签着色同源（设计 D2）。gold 走 item-icon-dot-color 内联变量。
  assert.ok(
    html.includes('item-icon-dot-color:gold') || html.includes('ant-timeline-item-color-gold'),
    '圆点着色与标签着色同源（gold）',
  );
});

// ── 任务 2.2：未知 chain_kind 中性兜底 ──
test('未知 chain_kind：中性「处置链」灰标签 + summary 照常 + SSR 不抛错', async () => {
  // 台账未来新增而前端未跟的形态（spec.md 未知链形态安全兜底场景）
  const html = await renderTimelineHtml([
    chainNode({ chain_kind: 'chain-future-kind', summary: '未知形态的链事件摘要' }),
  ]);
  assert.ok(html.includes('处置链'), '未知形态渲染中性「处置链」标签');
  assert.ok(html.includes('未知形态的链事件摘要'), 'summary 照常展示');
  // 中性灰标签：不落任何预设色 class（ant-tag-<color> 语义着色缺席）
  assert.ok(
    !/ant-tag-(blue|gold|green|orange|red)/.test(html),
    '中性兜底不得携带语义着色',
  );
  // 圆点归一 gray（'default' 非 Timeline dot 合法色，圆点侧同源归一）
  assert.ok(html.includes('ant-timeline-item-color-gray'), '圆点归一 gray 兜底');
});

test('畸形 chain_kind（原型链继承键）：hasOwnProperty 防御不报错', async () => {
  // 口径同 AdminNode 的 SEV_LABEL 防御（code-review item 5f9331c7ecae）：
  // 'constructor' 普通对象查找命中原型链继承键，不得渲染函数体或抛错
  const html = await renderTimelineHtml([chainNode({ chain_kind: 'constructor' })]);
  assert.ok(html.includes('处置链'), '畸形形态走中性兜底');
  assert.ok(!html.includes('native code'), '不渲染原型链继承键命中值');
});

// ── 任务 2.3：无链节点零回归 ──
test('仅 state/admin/verify/run 节点：渲染输出不含链卡片结构', async () => {
  const html = await renderTimelineHtml([
    {
      kind: 'state',
      time: '2026-11-08T09:00:00',
      from: 'drafted',
      to: 'ready',
      backward: false,
    },
    {
      kind: 'admin',
      time: '2026-11-08T09:05:00',
      record_kind: 'disposition',
      severity: 'minor',
      description: '复位告警并重派',
      result: 'resolved',
    },
    {
      kind: 'verify',
      time: '2026-11-08T09:10:00',
      total: 2,
      passed: 2,
    },
    {
      kind: 'run',
      time: '2026-11-08T09:15:00',
      run_id: 'impl-1',
      agent_type: 'impl',
      status: 'success',
    },
  ]);
  // 四类节点照常渲染（改动前路径零回归）
  assert.ok(html.includes('状态转移'), 'state 节点照常渲染');
  assert.ok(html.includes('运维处置'), 'admin 节点照常渲染');
  assert.ok(html.includes('验证执行'), 'verify 节点照常渲染');
  assert.ok(html.includes('复位告警并重派'), 'admin 正文照常渲染');
  // 链卡片结构零出现：六种标签、中性标签、语义着色 Tag、dot 同源变量全部缺席
  for (const [, label] of KNOWN_CHAIN_KINDS) {
    assert.ok(!html.includes(label), `无链节点时不得出现链标签「${label}」`);
  }
  assert.ok(!html.includes('>处置链<'), '无链节点时不得出现中性链标签');
  // 灰圆点与 state 非回退分支共享属既有形态，不在此列；只断言链专属着色形态缺席
  assert.ok(
    !html.includes('item-icon-dot-color:gold') && !html.includes('ant-timeline-item-color-gold'),
    '无链节点时不得出现链节点圆点着色形态',
  );
});

test('state 节点 item.chain 折叠状态序列渲染不受链分支影响（命名防混淆红线）', async () => {
  // state 的 chain 是折叠状态序列字段（非链事件）——全链展开渲染零变化
  const html = await renderTimelineHtml([
    {
      kind: 'state',
      time: '2026-11-08T09:20:00',
      from: 'implemented',
      to: 'pushed',
      chain: ['implemented', 'testing', 'verified', 'done', 'pushed'],
      backward: false,
    },
  ]);
  assert.ok(html.includes('状态转移'), '折叠节点仍是状态转移卡片');
  for (const s of ['implemented', 'testing', 'verified', 'done', 'pushed']) {
    assert.ok(html.includes(`>${s}</span>`), `折叠序列中间态 ${s} 全链展开渲染`);
  }
  assert.ok(!html.includes('>处置链<'), 'state 的 chain 字段不得误触发链节点渲染');
});
