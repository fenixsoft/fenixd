// add-knowledge-atlas 1.2：设置页 knowledge.enabled 开关渲染单测。
// 运行：cd core/dashboard/static && node --test tests/knowledgeSettings.test.mjs
// 无 jsdom：经 esbuild 把 MiscSettingsPanel（tsx 依赖链）打包为临时 ESM（react/
// react-dom/antd 保持 external，运行期由 node_modules 解析），再以
// react-dom/server SSR 渲染断言：
// - 开关控件存在（knowledge-enabled-switch / role=switch）；
// - 说明文案出现「知识真相源」与禁用占位语义；
// - 回填语义：缺省渲染为开启，显式 enabled:false 渲染为关闭。
//
// add-knowledge-atlas-maintenance 任务 1.2：知识真相源维护开关渲染语义单元测试
// （零依赖部分，node 原生 type-stripping 加载 .ts）。覆盖：
// - config.knowledge 段（缺失/部分/关闭/脏形状）→ 开关状态映射；
// - 开关状态 → 保存载荷 knowledge 段（与后端局部段合并语义对齐）；
// - 说明文案非空且含关键信息（车道行为 / 报告落点）。
// 2026-09-29 graphify 生成功能取消：graph_enabled 开关已下线，此处转而断言
// 渲染结果不再出现 graph 开关。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import {
  knowledgeSectionFromSwitches,
  knowledgeSwitchDesc,
  knowledgeSwitchesFromConfig,
} from '../src/pages/settings/knowledgeSettings.ts';

const require = createRequire(import.meta.url);
const esbuild = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { ConfigProvider, Form } = require('antd');

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');

// 打包一次、进程内复用（两支测试共享同一产物）。产物落 node_modules/.tmp/
// 之下：external 的 antd/react 裸说明符需从 node_modules 旁解析，/tmp 下
// 解析不到包（ERR_MODULE_NOT_FOUND）。
const outdir = join(ROOT, 'node_modules', '.tmp-knowledge-settings-test');
let bundleUrl = null;
async function loadPanel() {
  if (!bundleUrl) {
    mkdirSync(outdir, { recursive: true });
    const outfile = join(outdir, 'panel.mjs');
    await esbuild.build({
      entryPoints: [join(ROOT, 'src/pages/settings/components/MiscSettingsPanel.tsx')],
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

function renderPanel(PanelModule, config) {
  const { default: Panel } = PanelModule;
  return renderToStaticMarkup(
    React.createElement(
      ConfigProvider,
      null,
      React.createElement(Form, null),
      React.createElement(Panel, { config, onSave: async () => {} }),
    ),
  );
}

// ── 面板 SSR 渲染（add-knowledge-atlas 1.2）────────────────────────────

test('设置页渲染 knowledge.enabled 开关与说明文案（缺省开启）', async () => {
  const mod = await loadPanel();
  const html = renderPanel(mod, { archive: { auto_threshold: 50 } });
  assert.ok(html.includes('真相源'), '应渲染「真相源」节标题');
  assert.ok(html.includes('知识真相源'), '应渲染「知识真相源」开关行名称');
  assert.ok(html.includes('knowledge-enabled-switch'), '应渲染开关 testid');
  assert.ok(html.includes('knowledge.enabled'), '开关行应带参数路径（knowledge.enabled）');
  assert.ok(html.includes('知识真相源已禁用'), '说明文案应含禁用后页签占位语义');
  assert.ok(html.includes('role="switch"'), '应渲染 antd Switch（role=switch）');
  // 缺省态：默认勾选（antd Switch checked 渲染 aria-checked="true"）
  assert.ok(html.includes('aria-checked="true"'), '缺省应渲染为开启');
});

test('设置页渲染显式关闭的 knowledge.enabled', async () => {
  const mod = await loadPanel();
  const html = renderPanel(mod, {
    archive: { auto_threshold: 50 },
    knowledge: { enabled: false },
  });
  assert.ok(html.includes('aria-checked="false"'), '显式 false 应渲染为关闭');
});

test('audit 车道开关渲染参数路径，graph 开关已下线', async () => {
  const mod = await loadPanel();
  const html = renderPanel(mod, { archive: { auto_threshold: 50 } });
  assert.ok(html.includes('knowledge-audit-switch'), '应渲染体检开关 testid');
  assert.ok(html.includes('knowledge.audit_enabled'), '体检开关行应带参数路径');
  assert.ok(!html.includes('knowledge-graph-switch'), 'graph 开关已取消，不应再渲染');
  assert.ok(!html.includes('knowledge.graph_enabled'), 'graph 参数路径不应再出现');
});

// ── 段缺失/脏形状 → 缺省全开（与 core/config.py get_knowledge_lane_config 同口径） ──

test('config 无 knowledge 段时开关默认开启', () => {
  const s = knowledgeSwitchesFromConfig(undefined);
  assert.equal(s.auditEnabled, true);
});

test('非对象段（后端降级为 null/标量）不崩且默认开启', () => {
  for (const bad of [null, 3, 'x', []]) {
    const s = knowledgeSwitchesFromConfig(bad);
    assert.equal(s.auditEnabled, true);
  }
});

test('显式 false 关闭对应开关，缺键保持开启', () => {
  const s = knowledgeSwitchesFromConfig({ audit_enabled: false });
  assert.equal(s.auditEnabled, false);
  const t = knowledgeSwitchesFromConfig({});
  assert.equal(t.auditEnabled, true);
});

test('非法值（字符串/数字非 false）按开启处理（与后端回退缺省同口径）', () => {
  const s = knowledgeSwitchesFromConfig({ audit_enabled: 'yes' });
  assert.equal(s.auditEnabled, true);
});

// ── 保存载荷往返 ──────────────────────────────────────────────────────

test('开关状态 → knowledge 段保存载荷只落 audit_enabled（graph 键不再读写）', () => {
  const payload = knowledgeSectionFromSwitches({ auditEnabled: true });
  assert.deepEqual(payload, {
    knowledge: { audit_enabled: true },
  });
});

test('段映射 → 载荷往返保真', () => {
  const round = knowledgeSectionFromSwitches(
    knowledgeSwitchesFromConfig({ audit_enabled: false }),
  );
  assert.deepEqual(round, {
    knowledge: { audit_enabled: false },
  });
});

// ── 说明文案（交互契约：设置页控件必须带说明） ────────────────────────

test('audit 开关说明含体检行为与报告落点', () => {
  const desc = knowledgeSwitchDesc();
  assert.ok(desc.includes('体检'));
  assert.ok(desc.includes('knowledge_audit_report.md'));
});

test('收尾：清理临时产物目录', () => {
  rmSync(outdir, { recursive: true, force: true });
  assert.ok(true);
});
