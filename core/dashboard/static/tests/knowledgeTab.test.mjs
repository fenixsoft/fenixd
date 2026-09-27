// add-knowledge-atlas 4.1/4.2：KnowledgeTab 纯函数与渲染单测。
// 运行：cd core/dashboard/static && node --test tests/knowledgeTab.test.mjs
// 无 jsdom：经 esbuild 把 KnowledgeTab（tsx 依赖链）打包为临时 ESM（react/
// react-dom/antd/dayjs 保持 external），react-dom/server SSR 渲染断言：
// - resolveKnowledgePath：相对链接归一化（../、./、白名单外、越出真相源根、
//   外部协议/锚点）→ 白名单路径或 null；
// - adrDisplayName：'ADR-001-x.md' → 'ADR-001 x'；
// - active=false → 不渲染任何内容（未选中零渲染，按需加载门控）；
// - active=true 初挂（SSR 不跑 effect）→ loading 占位，不发请求即无异常。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, rmSync } from 'node:fs';
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

// 产物落 node_modules/.tmp-knowledge-tab-test/：external 裸说明符需从
// node_modules 旁解析（/tmp 下 ERR_MODULE_NOT_FOUND，同 knowledgeSettings）。
const outdir = join(ROOT, 'node_modules', '.tmp-knowledge-tab-test');
let bundleUrl = null;
async function loadTab() {
  if (!bundleUrl) {
    mkdirSync(outdir, { recursive: true });
    const outfile = join(outdir, 'tab.mjs');
    await esbuild.build({
      entryPoints: [join(ROOT, 'src/pages/projects/components/KnowledgeTab.tsx')],
      outfile,
      bundle: true,
      format: 'esm',
      jsx: 'automatic',
      platform: 'node',
      external: ['react', 'react-dom', 'antd', 'dayjs'],
      alias: { '@': join(ROOT, 'src'), '@@': join(ROOT, 'src/.umi') },
      logLevel: 'silent',
    });
    bundleUrl = pathToFileURL(outfile).href;
  }
  return import(bundleUrl);
}

function renderTab(mod, props) {
  return renderToStaticMarkup(
    React.createElement(
      ConfigProvider,
      null,
      React.createElement(mod.default, props),
    ),
  );
}

test('resolveKnowledgePath：总目录基准（null）解析域内/adr 链接', async (t) => {
  const mod = await loadTab();
  const resolve = mod.resolveKnowledgePath;
  assert.equal(resolve(null, 'domains/pickup/_domain.md'), 'domains/pickup/_domain.md');
  assert.equal(resolve(null, 'adr/ADR-001-x.md'), 'adr/ADR-001-x.md');
  assert.equal(resolve(null, './domains/d/page.md'), 'domains/d/page.md');
});

test('resolveKnowledgePath：能力页基准归一化 .. 与 ./', async (t) => {
  const mod = await loadTab();
  const resolve = mod.resolveKnowledgePath;
  assert.equal(
    resolve('domains/pickup/scheduled-spec-pickup.md', 'other-page.md'),
    'domains/pickup/other-page.md',
  );
  assert.equal(
    resolve('domains/pickup/scheduled-spec-pickup.md', '../pickup2/x.md'),
    'domains/pickup2/x.md',
  );
  assert.equal(resolve('domains/pickup/x.md', '../../adr/ADR-002-y.md'), 'adr/ADR-002-y.md');
  assert.equal(resolve('domains/pickup/x.md', '#锚点'), null);
});

test('resolveKnowledgePath：越界/非法一律 null', async (t) => {
  const mod = await loadTab();
  const resolve = mod.resolveKnowledgePath;
  assert.equal(resolve(null, '../../etc/passwd'), null, '越出真相源根');
  assert.equal(resolve(null, '/abs/path.md'), null, '绝对路径');
  assert.equal(resolve(null, 'https://example.com/x.md'), null, '外部 http');
  assert.equal(resolve(null, 'mailto:a@b.c'), null, 'mailto');
  assert.equal(resolve(null, '//example.com/x'), null, '协议相对');
  assert.equal(resolve(null, ''), null, '空串');
  assert.equal(resolve(null, 'graph/graph.html'), null, '白名单外前缀');
  assert.equal(resolve(null, 'index.md'), null, '根下 index 不在白名单');
});

test('adrDisplayName：文件名转展示名', async (t) => {
  const mod = await loadTab();
  assert.equal(mod.adrDisplayName('ADR-001-spawn-injection.md'), 'ADR-001 spawn-injection');
  assert.equal(mod.adrDisplayName('index.md'), 'index');
});

test('adrListLabel：标题字段优先，编号取自文件名前缀；无标题回退文件名派生', async (t) => {
  const mod = await loadTab();
  assert.equal(mod.adrListLabel('ADR-001-zn-one.md', 'zn-adr-one-title'), 'ADR-001 zn-adr-one-title');
  assert.equal(mod.adrListLabel('ADR-001-zn-one.md', null), 'ADR-001 zn-one', '无标题回退 adrDisplayName');
  assert.equal(mod.adrListLabel('index.md', '某标题'), '某标题', '非 ADR-NNN 文件名仅回标题');
});

test('active=false 不渲染（未选中零请求零渲染）', async (t) => {
  const mod = await loadTab();
  const html = renderTab(mod, { project: 'p1', active: false });
  assert.equal(html, '');
});

test('active=true 初挂渲染 loading 占位（SSR 不执行 effect，无请求异常）', async (t) => {
  const mod = await loadTab();
  const html = renderTab(mod, { project: 'p1', active: true });
  assert.ok(html.includes('knowledge-loading'), '应渲染 loading 占位');
});

test('收尾：清理临时产物目录', () => {
  rmSync(outdir, { recursive: true, force: true });
  assert.ok(true);
});
