// SPEC 列表页右上角「配置」按钮 + 标题栏按钮图标态测试
// （2026-11-16 用户需求：新增配置按钮进入配置页且作用域自动设定为该工程；
// 配置 / 新会话两按钮都只显示图标不显示文字）。
// 零依赖 node:test（同 specInfoIcon.test.mjs 习语：源码扫描钉 JSX 接线；
// 渲染行为由 npm run build 与浏览器场景覆盖）。
//
// 覆盖：
// - 列表页双钮接线：embed 条件新会话钮 + 恒渲染配置钮，配置钮恒居最右；
// - 配置深链：/settings?project=<encodeURIComponent(name)>（hash 路由 query）；
// - 图标态无文字：DshNewSessionButton 不再含「新会话」文字 span、经
//   DshIconButton 壳承载、图标渲染 16px；
// - 壳规格：38×38 方形 / 0.5px 描边 / radius 12 / 白底 / title 与 aria-label
//   同源（图标钮无可见文字，无障碍名全靠 title）；
// - 配置页首屏作用域预选：initialScopeFromUrl 读 hash query ?project=
//   非空即 {scope:'project', project}，惰性初始化单次取值；
// - hover/focus 伪类随壳迁移：global.less 选择器 .dsh-icon-button
//   （hover !important 压内联白底），旧 .dsh-new-session-button 选择器退役。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const STATIC_ROOT = join(import.meta.dirname, '..');
const readSrc = (rel) => readFileSync(join(STATIC_ROOT, rel), 'utf-8');

const listSrc = readSrc('src/pages/projects/list.tsx');
const newSessionSrc = readSrc('src/components/DshNewSessionButton.tsx');
const iconButtonSrc = readSrc('src/components/DshIconButton.tsx');
const settingsSrc = readSrc('src/pages/settings/index.tsx');
const globalLessSrc = readSrc('src/global.less');

// ── 列表页双钮接线 ──────────────────────────────────────────────────

test('列表页 filters 槽：embed 条件新会话钮 + 恒渲染配置钮', () => {
  const f0 = listSrc.indexOf('filters={');
  // 块收尾以「换行 + 8 空格 + }」锚定（裸 8 空格串会误匹配内层缩进的 }} 行）
  const f1 = listSrc.indexOf('\n        }', f0);
  const filters = listSrc.slice(f0, f1);
  assert.ok(filters.includes('isEmbedMode() ?'), '新会话钮应保持仅 embed 态渲染（standalone 无宿主）');
  assert.ok(filters.includes('<DshNewSessionButton'), 'filters 槽应接线 DshNewSessionButton');
  assert.ok(filters.includes('<DshIconButton'), 'filters 槽应接线 DshIconButton 配置钮');
  // 配置钮恒渲染：不在任何条件分支内（embed/standalone 两态都在右上角）
  assert.ok(!filters.includes('isEmbedMode() ? (\n              <DshIconButton'), '配置钮不应被 embed 条件包裹（两态恒渲染）');
});

test('配置钮深链：/settings?project=<encodeURIComponent(name)>，SettingOutlined 16px', () => {
  assert.ok(
    listSrc.includes('history.push(`/settings?project=${encodeURIComponent(name)}`)'),
    '配置钮应深链 /settings?project=<name>（hash 路由 query 随 hash 传递）',
  );
  const b0 = listSrc.indexOf('<DshIconButton');
  const b1 = listSrc.indexOf('</DshIconButton>', b0);
  const btn = listSrc.slice(b0, b1);
  assert.ok(btn.includes("title={t('projects.list.configTitle')}"), '配置钮原生 tooltip 应钉 intl id projects.list.configTitle（zh 目录=「配置」）');
  assert.ok(btn.includes('<SettingOutlined'), '配置钮图标应接线 SettingOutlined');
  assert.ok(btn.includes('fontSize: 16'), '配置钮图标应渲染 16px（同新会话钮图标态口径）');
});

test('配置钮恒居最右：standalone 独占右上角、embed 落新会话钮右侧', () => {
  const f0 = listSrc.indexOf('filters={');
  const f1 = listSrc.indexOf('</>', f0);
  const filters = listSrc.slice(f0, f1);
  const sessionAt = filters.indexOf('<DshNewSessionButton');
  const configAt = filters.indexOf('<DshIconButton');
  assert.ok(sessionAt > 0 && configAt > sessionAt, 'filters 槽内配置钮应排在新会话钮之后（恒居最右）');
});

// ── 图标态：只显示图标，不显示文字 ──────────────────────────────────

test('新会话钮图标态：去文字 span，经 DshIconButton 壳承载', () => {
  assert.ok(!newSessionSrc.includes('<span'), '「新会话」文字 span 应移除（只显示图标）');
  assert.ok(!newSessionSrc.includes('新会话</span>'), '不应残留文字节点');
  assert.ok(newSessionSrc.includes('<DshIconButton'), '新会话钮应改经 DshIconButton 壳承载外观');
  assert.ok(newSessionSrc.includes("title={intl.formatMessage({ id: 'components.dshNewSession.title' })}"), '图标态语义全靠 title（原生 tooltip + aria-label 同源，batch-G 起钉 intl id components.dshNewSession.title）');
  assert.ok(
    newSessionSrc.includes('viewBox="0 0 16 16"') && newSessionSrc.includes('strokeWidth={1.3}'),
    'new-chat-outline 图标规格应保持（16 视窗 / medium 1.3 描边）',
  );
});

test('图标渲染 16px：由 14px 升档与壳 38×38 比例平衡', () => {
  assert.ok(newSessionSrc.includes('width={16}') && newSessionSrc.includes('height={16}'), 'new-chat 图标应渲染 16px');
});

// ── DshIconButton 壳规格（两钮共用单源） ────────────────────────────

test('壳规格：38×38 方形 / 0.5px 描边 / radius 12 / 白底 / dsh-icon-button', () => {
  assert.ok(iconButtonSrc.includes('width: 38') && iconButtonSrc.includes('height: 38'), '壳应 38×38（与旧 wide 档同高）');
  assert.ok(iconButtonSrc.includes('padding: 0'), '图标态应 padding 0（dsh 窄档同构读法）');
  // dashboard-dark-theme 4.2：配色改经 useDshPalette 按档取值（浅档=原常量逐字节）
  assert.ok(iconButtonSrc.includes('border: `0.5px solid ${pal.borderL3}`'), '描边应取 DSH_BORDER_L3 档（配色单源红线）');
  assert.ok(iconButtonSrc.includes('borderRadius: 12'), '圆角应 radius 12（dsw radius-md）');
  assert.ok(iconButtonSrc.includes('background: pal.bgElevated'), '底色应取 DSH_BG_ELEVATED 档（配色单源红线）');
  assert.ok(iconButtonSrc.includes('className="dsh-icon-button"'), '壳应挂 dsh-icon-button 类（global.less 伪类挂点）');
});

test('壳语义：title 必填且与 aria-label 同源（图标钮无可见文字）', () => {
  assert.ok(
    iconButtonSrc.includes('title,') && iconButtonSrc.includes('aria-label={title}'),
    'aria-label 应与 title 同源',
  );
  assert.ok(iconButtonSrc.includes('title: string'), 'title 应必填（无缺省）——图标钮无障碍名全靠它');
});

// ── 配置页首屏作用域预选 ────────────────────────────────────────────

test('配置页读参：initialScopeFromUrl 读 hash query ?project=（唯一读侧）', () => {
  assert.ok(settingsSrc.includes('function initialScopeFromUrl()'), '应存在 initialScopeFromUrl 读侧单点');
  assert.ok(
    settingsSrc.includes("new URLSearchParams(window.location.hash.split('?')[1] || '').get('project')"),
    '应从 location.hash 的 ? 后读 query（hash 路由先例，同 activities 页 initialTab）',
  );
});

test('作用域预选：?project= 非空即 {scope:project, project}，state 惰性初始化单次取值', () => {
  assert.ok(
    settingsSrc.includes("return project ? { scope: 'project', project } : { scope: 'user', project: undefined };"),
    '深链参数应映射为项目级作用域预选（空值回落用户级）',
  );
  assert.ok(
    settingsSrc.includes('const [initialScope] = useState(initialScopeFromUrl);'),
    'state 应惰性初始化单次取值（首屏预选，URL 不回写、不参与后续流转）',
  );
  assert.ok(
    settingsSrc.includes("useState<'user' | 'project'>(initialScope.scope)") &&
      settingsSrc.includes('useState<string | undefined>(initialScope.project);'),
    'scope / project 两 state 应由同一 initialScope 初始化（避免重复读 URL）',
  );
});

// ── 伪类样式随壳迁移（global.less） ─────────────────────────────────

test('global.less：.dsh-icon-button hover/focus 伪类接线，旧选择器退役', () => {
  assert.ok(globalLessSrc.includes('.dsh-icon-button:hover'), 'hover 伪类应挂 .dsh-icon-button');
  assert.ok(globalLessSrc.includes('.dsh-icon-button:focus-visible'), 'focus-visible 伪类应挂 .dsh-icon-button');
  assert.ok(
    globalLessSrc.includes('background: var(--fenix-icon-btn-hover) !important;'),
    'hover 底色须 !important（压组件内联白底红线，见 dsh-new-session-button 知识页）',
  );
  assert.ok(globalLessSrc.includes('outline: 2px solid var(--fenix-link);'), '焦点环规格应保留');
  // 旧选择器以「选择器 + 伪类/空格」的规则形态钉退役（注释中的迁移溯源
  // 提及不算活规则）
  assert.ok(!globalLessSrc.includes('.dsh-new-session-button:'), '旧 .dsh-new-session-button 伪类规则应退役');
  assert.ok(!globalLessSrc.includes('.dsh-new-session-button {'), '旧 .dsh-new-session-button 规则块应退役');
});
