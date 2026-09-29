// dashboard-push-restart 2.2：HooksPanel 逃生键开关单测。
// 运行：cd core/dashboard/static && node --test tests/hooksPanel.test.mjs
// 无 jsdom：经 esbuild 把 HooksPanel（tsx 依赖链）打包为临时 ESM（react/
// react-dom/antd 保持 external，运行期由 node_modules 解析），再以
// react-dom/server SSR 渲染断言控件形态；写回参数以纯函数断言（切换点击链路
// 由验证引擎 web 场景实测覆盖，此处按任务口径「前端只测控件与写回参数」）：
// - 开关渲染缺省态（push_restart_dashboard 缺省 true → 勾选）；
// - 显式 false 渲染为未勾选；
// - 说明文案与参数路径（hooks.push_restart_dashboard）在场；
// - 写回参数保留 hooks 段其余键并落 push_restart_dashboard（整体替换语义）。
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
const { App, ConfigProvider } = require('antd');

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');

// 打包一次、进程内复用。产物落 node_modules/.tmp 之下：external 的 antd/react
// 裸说明符需从 node_modules 旁解析，/tmp 下解析不到包（ERR_MODULE_NOT_FOUND）。
const outdir = join(ROOT, 'node_modules', '.tmp-hooks-panel-test');
let bundleUrl = null;
async function loadPanel() {
  if (!bundleUrl) {
    mkdirSync(outdir, { recursive: true });
    const outfile = join(outdir, 'panel.mjs');
    await esbuild.build({
      entryPoints: [join(ROOT, 'src/pages/settings/components/HooksPanel.tsx')],
      outfile,
      bundle: true,
      format: 'esm',
      jsx: 'automatic',
      platform: 'node',
      external: ['react', 'react-dom', 'antd', 'dayjs'],
      alias: { '@': join(ROOT, 'src'), '@@': join(ROOT, 'src/.umi') },
      // HookManager 依赖链拉入 @ant-design/icons 等 CJS 包（require react）：
      // ESM 外置裸说明符下动态 require 不可用，注入 createRequire 兜底
      banner: {
        js: "import { createRequire as __cr } from 'node:module'; const require = __cr(import.meta.url);",
      },
      logLevel: 'silent',
    });
    bundleUrl = pathToFileURL(outfile).href;
  }
  return import(bundleUrl);
}

function renderPanel(PanelModule, config) {
  const { default: Panel } = PanelModule;
  // HooksPanel 用 App.useApp()（message）：须包 antd App 提供 context
  return renderToStaticMarkup(
    React.createElement(
      ConfigProvider,
      null,
      React.createElement(App, null, React.createElement(Panel, { config, onSave: async () => {}, project: 'p' })),
    ),
  );
}

/** 取逃生键开关元素附近片段（antd v6 data-testid 落在 input 上，勾选态类名
 * ant-checkbox-checked 在其前方的包裹 span 上，窗口向前扩）。 */
function switchSegment(html) {
  const marker = 'data-testid="push-restart-dashboard-switch"';
  const i = html.indexOf(marker);
  assert.ok(i >= 0, '应渲染逃生键开关 testid');
  return html.slice(Math.max(0, i - 400), i + 400);
}

// ── 控件渲染 ──────────────────────────────────────────────────────────

test('开关渲染缺省态：push_restart_dashboard 缺省 true → 勾选', async () => {
  const mod = await loadPanel();
  const html = renderPanel(mod, { hooks: { global: [], specs: {} } });
  const seg = switchSegment(html);
  assert.ok(seg.includes('ant-checkbox-checked'), '缺省应渲染为勾选');
  assert.ok(html.includes('hooks.push_restart_dashboard'), '开关行应带参数路径');
  assert.ok(
    html.includes('SPEC push 后自动重启 dashboard 以加载最新代码'),
    '说明文案应含 SPEC push 后自动重启 dashboard 以加载最新代码',
  );
});

test('显式 false 渲染为未勾选', async () => {
  const mod = await loadPanel();
  const html = renderPanel(mod, {
    hooks: { push_restart_dashboard: false, global: [], specs: {} },
  });
  const seg = switchSegment(html);
  assert.ok(!seg.includes('ant-checkbox-checked'), '显式 false 不应勾选');
  assert.ok(!seg.includes('type="checkbox" checked'), 'input 不应带 checked 属性');
});

// ── 逃生键读取语义（与后端 hook_config 注入门同口径） ─────────────────

test('缺省/缺段/脏形状 → true（非法值按缺省开启）', async () => {
  const { pushRestartEnabledFromConfig } = await loadPanel();
  for (const bad of [undefined, null, {}, [], 'x', 3]) {
    assert.equal(pushRestartEnabledFromConfig(bad), true, String(bad));
  }
  assert.equal(pushRestartEnabledFromConfig({ push_restart_dashboard: 'yes' }), true);
});

test('显式 false → false', async () => {
  const { pushRestartEnabledFromConfig } = await loadPanel();
  assert.equal(pushRestartEnabledFromConfig({ push_restart_dashboard: false }), false);
});

// ── 写回参数（整体替换语义：保留 hooks 段其余键） ─────────────────────

test('切换写回参数：保留 global/specs 并落 push_restart_dashboard=false', async () => {
  const { pushRestartSavePayload } = await loadPanel();
  const hooksCfg = { global: [{ id: 'h1', events: ['done'], action: 'push' }], specs: {} };
  assert.deepEqual(pushRestartSavePayload(hooksCfg, false), {
    hooks: {
      global: [{ id: 'h1', events: ['done'], action: 'push' }],
      specs: {},
      push_restart_dashboard: false,
    },
  });
});

test('切换写回参数：重新开启落 true；hooks 段非对象（脏形状）按空段兜底', async () => {
  const { pushRestartSavePayload } = await loadPanel();
  assert.deepEqual(pushRestartSavePayload({ push_restart_dashboard: false }, true), {
    hooks: { push_restart_dashboard: true },
  });
  assert.deepEqual(pushRestartSavePayload(null, true), {
    hooks: { push_restart_dashboard: true },
  });
});

test('收尾：清理临时产物目录', () => {
  rmSync(outdir, { recursive: true, force: true });
  assert.ok(true);
});
