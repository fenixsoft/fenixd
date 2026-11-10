// add-agent-model-quick-assign 6.2：QuickAssignModal 单测。
// 运行：cd core/dashboard/static && node --test tests/quickAssign.test.mjs
// 沿用 hooksPanel.test.mjs 的 esbuild 打包 + react-dom/server SSR 范式
// （react/react-dom/antd external，产物落 node_modules/.tmp-*，无 jsdom）。
// antd Modal 走 Portal、静态 SSR 不落弹层内容（「Portal only work in client
// side」警告；Tooltip 弹层同款先例），故控件断言直接渲染组件导出的
// QuickAssignModalBody / QuickAssignModalFooter 纯展示组件——与 Modal 内实际
// 渲染同源（default export 仅持状态并组装）：
// - 模板行控件/本作用域与指定项目选项/应用取消按钮在场；
// - 缺省态（无有效 provider 行）应用按钮禁用（spec「无有效 provider 行禁止应用」）；
// - 项目级作用域标签与多项目 options 渲染；
// - 源码无新增 CSS 动画/过渡（DESIGN.md 静态渲染约束）。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, rmSync } from 'node:fs';
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

const outdir = join(ROOT, 'node_modules', '.tmp-quick-assign-test');
let bundleUrl = null;
async function loadModal() {
  if (!bundleUrl) {
    mkdirSync(outdir, { recursive: true });
    const outfile = join(outdir, 'modal.mjs');
    await esbuild.build({
      entryPoints: [join(ROOT, 'src/pages/settings/components/QuickAssignModal.tsx')],
      outfile,
      bundle: true,
      format: 'esm',
      jsx: 'automatic',
      platform: 'node',
      external: ['react', 'react-dom', 'antd', 'dayjs'],
      alias: { '@': join(ROOT, 'src'), '@@': join(ROOT, 'src/.umi') },
      banner: {
        js: "import { createRequire as __cr } from 'node:module'; const require = __cr(import.meta.url);",
      },
      logLevel: 'silent',
    });
    bundleUrl = pathToFileURL(outfile).href;
  }
  return import(bundleUrl);
}

function renderElement(Element, props) {
  return renderToStaticMarkup(
    React.createElement(ConfigProvider, null, React.createElement(App, null, React.createElement(Element, props))),
  );
}

const PROVIDERS = [
  { name: 'volc-engine', baseurl: 'https://x', apikey: 'k' },
  { name: 'bigmodel.cn', baseurl: 'https://y', apikey: 'k' },
];

const initialBodyProps = {
  projects: ['proj-a', 'proj-b'],
  providers: PROVIDERS,
  roleModel: '',
  rows: [{ provider: '', model: '' }],
  includeCurrent: true,
  includeProjects: false,
  selectedProjects: [],
  result: null,
  saving: false,
  onRoleModelChange: () => {},
  onRowChange: () => {},
  onAddRow: () => {},
  onRemoveRow: () => {},
  onIncludeCurrentChange: () => {},
  onIncludeProjectsChange: () => {},
  onSelectedProjectsChange: () => {},
};

test('模板行控件与作用域选项在场：角色默认模型输入、Provider 下拉、新增行、本作用域/指定项目', async () => {
  const mod = await loadModal();
  const html = renderElement(mod.QuickAssignModalBody, {
    ...initialBodyProps,
    project: undefined,
  });
  assert.ok(html.includes('data-testid="quick-assign-role-model"'), '角色默认模型输入框在场');
  assert.ok(html.includes('角色默认模型'), '角色默认模型 placeholder 在场');
  assert.ok(html.includes('data-testid="quick-assign-row-provider-0"'), '候选行 Provider 下拉在场');
  assert.ok(html.includes('data-testid="quick-assign-add-row"'), '新增候选行按钮在场');
  assert.ok(html.includes('data-testid="quick-assign-include-current"'), '本作用域 Checkbox 在场');
  assert.ok(html.includes('本作用域（用户级）'), '用户级作用域标签在场');
  assert.ok(html.includes('data-testid="quick-assign-projects-toggle"'), '指定项目 Checkbox 在场');
  assert.ok(html.includes('指定项目'), '指定项目标签在场');
  // includeProjects=false：多选不渲染（联动展开）
  assert.ok(!html.includes('data-testid="quick-assign-projects-select"'), '未勾选指定项目时不渲染多选');
});

test('页脚按钮在场；缺省态（无有效 provider 行）应用禁用，有效行时可用', async () => {
  const mod = await loadModal();
  // 缺省 canApply=false（初始行 provider 为空 → 无有效行）
  const disabled = renderElement(mod.QuickAssignModalFooter, {
    canApply: false,
    saving: false,
    onCancel: () => {},
    onApply: () => {},
  });
  assert.ok(disabled.includes('data-testid="quick-assign-cancel"'), '取消按钮在场');
  assert.ok(disabled.includes('data-testid="quick-assign-apply"'), '应用按钮在场');
  const i = disabled.indexOf('data-testid="quick-assign-apply"');
  assert.ok(i >= 0, '应用按钮带 testid');
  // disabled 属性落在开标签内 testid 之后（窗口向后取）
  assert.ok(/\sdisabled[=>]/.test(disabled.slice(i, i + 400)), '缺省态应用按钮 disabled');
  // 有有效 provider 行 + 非空目标 → canApply=true → 可点击
  const enabled = renderElement(mod.QuickAssignModalFooter, {
    canApply: true,
    saving: false,
    onCancel: () => {},
    onApply: () => {},
  });
  const j = enabled.indexOf('data-testid="quick-assign-apply"');
  assert.ok(!/\sdisabled[=>]/.test(enabled.slice(j, j + 400)), '有效模板+目标时应用按钮可用');
  // canApply 门控单源（组件内 validRows/targets 双条件）
  const src = readFileSync(join(ROOT, 'src/pages/settings/components/QuickAssignModal.tsx'), 'utf-8');
  assert.ok(
    src.includes('validRows.length > 0 && targets.length > 0'),
    'canApply 应同时门控「有效 provider 行」与「非空目标」',
  );
});

test('项目级作用域标签显示项目名；勾选指定项目后多选与项目 options 渲染', async () => {
  const mod = await loadModal();
  const html = renderElement(mod.QuickAssignModalBody, {
    ...initialBodyProps,
    project: 'proj-a',
    includeProjects: true,
    selectedProjects: ['proj-b'],
  });
  assert.ok(html.includes('本作用域（项目 proj-a）'), '项目级作用域标签应显示项目名');
  assert.ok(html.includes('data-testid="quick-assign-projects-select"'), '勾选后渲染项目多选');
  assert.ok(html.includes('proj-a'), '项目 options 含已注册项目');
  assert.ok(html.includes('proj-b'), '项目 options 含已注册项目');
});

test('saving 态：应用按钮 loading/disabled、取消禁用（spec「重复提交防护」）', async () => {
  const mod = await loadModal();
  const html = renderElement(mod.QuickAssignModalFooter, {
    canApply: false,
    saving: true,
    onCancel: () => {},
    onApply: () => {},
  });
  assert.ok(/ant-btn-loading/.test(html), 'saving 态应用按钮 loading 态类在场');
  const i = html.indexOf('data-testid="quick-assign-cancel"');
  assert.ok(/\sdisabled[=>]/.test(html.slice(i, i + 400)), 'saving 态取消按钮 disabled');
});

test('移动端形态（task 6.4）：弹窗宽度收窄、body 限高滚动、footer 常驻可达、行控件不溢出 390', () => {
  const src = readFileSync(join(ROOT, 'src/pages/settings/components/QuickAssignModal.tsx'), 'utf-8');
  // 宽度：移动端 calc(100vw - 32px)（390px 视口无横向溢出），PC 固定 560
  assert.ok(src.includes("isMobile ? 'calc(100vw - 32px)' : 560"), '移动端弹窗宽度应为 calc(100vw - 32px)');
  // body 限高滚动：maxHeight + overflowY auto（长内容可完整滚动）
  assert.ok(/maxHeight:\s*'calc\(100vh - 220px\)'/.test(src), 'body 应限高');
  assert.ok(/overflowY:\s*'auto'/.test(src), 'body 应可滚动');
  // 应用/取消在 Modal footer（native footer 不随 body 滚动，恒可达）
  assert.ok(/footer={\s*<QuickAssignModalFooter/.test(src), '应用/取消按钮应在 footer 常驻');
  // 行控件移动端宽度分支（130+120+删除按钮 ≈ 300px < 390 可用宽度）
  assert.ok(src.includes('isMobile ? 130 : 180'), 'Provider 下拉应有移动端收窄分支');
  assert.ok(src.includes('isMobile ? 120 : 200'), '模型输入框应有移动端收窄分支');
});

test('DESIGN.md 静态渲染：源码无新增 CSS 动画/过渡', async () => {
  const src = readFileSync(join(ROOT, 'src/pages/settings/components/QuickAssignModal.tsx'), 'utf-8');
  assert.ok(!/animation\s*:/.test(src), '不得声明 CSS animation');
  assert.ok(!/transition\s*:/.test(src), '不得声明 CSS transition');
});

// 产物清理（进程退出钩子；esbuild 产物落 node_modules/.tmp-quick-assign-test）
process.on('exit', () => {
  try {
    rmSync(outdir, { recursive: true, force: true });
  } catch {
    /* 忽略清理失败 */
  }
});
