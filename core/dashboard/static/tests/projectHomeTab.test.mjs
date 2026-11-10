// 项目首页页签前端测试（add-project-home-tab 5.2）。
// 零依赖：纯函数经 node 原生 type-stripping 直测；接线与门控以源码扫描钉住
// （对齐 bundleRevGuard / knowledgeTab 等既有源码扫描先例——组件含 antd/umi
// 依赖链，node:test 无 JSX 运行时，结构契约以源码断言钉住防回归）。
// 运行：cd core/dashboard/static && node --test tests/projectHomeTab.test.mjs
//
// 覆盖：
// - 纯函数（projectHomeShared.ts）：parseHomePath 归一化 / splitHomePath /
//   homeCrumbs / formatRelativeTime 七档与回退 / formatBytes
// - 页签接线（list.tsx 源码扫描）：items 首位 home、缺省 dev 不变、
//   path 写回块（仅 tab=home、根目录不写、replace 语义并入既有块）
// - 门控与缓存（ProjectHomeTab.tsx 源码扫描）：active 门控零请求、切离丢弃、
//   进程内缓存、initialPath 直达「先目录后文件」回退
// - 渲染锚（源码扫描）：窄屏列分流（hidden: isMobile）、截断提示、二进制
//   降级、256 KB 截断提示、非 git Empty、Markdown 管线复用（禁新写路径）
// - 服务函数（services/dashboard.ts 源码扫描）：三函数在位、download 走
//   withApiBase 前缀化单点
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
  parseHomePath,
  splitHomePath,
  homeCrumbs,
  formatRelativeTime,
  formatBytes,
} from '../src/pages/projects/components/projectHomeShared.ts';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, '../src');
const read = (p) => readFileSync(join(SRC, p), 'utf8');
const listTsx = () => read('pages/projects/list.tsx');
const homeTsx = () => read('pages/projects/components/ProjectHomeTab.tsx');
const dashTs = () => read('services/dashboard.ts');

// ── 纯函数：parseHomePath ────────────────────────────────────────────

test('parseHomePath：剔除空段消化首尾与连续斜杠', () => {
  assert.equal(parseHomePath('core/dashboard'), 'core/dashboard');
  assert.equal(parseHomePath('/core/dashboard/'), 'core/dashboard');
  assert.equal(parseHomePath('core//dashboard'), 'core/dashboard');
  assert.equal(parseHomePath('///'), '');
  assert.equal(parseHomePath(''), '');
  assert.equal(parseHomePath(null), '');
  assert.equal(parseHomePath(undefined), '');
});

test('parseHomePath：URLSearchParams 已解码的中文/空格路径原样保留', () => {
  // 解码由 URLSearchParams 完成（'core/a%20b' 传入前已是 'core/a b'），
  // 纯函数不做二次 unquote（防文件名真含 %2F 的合法场景被误拆）
  assert.equal(parseHomePath('core/说 明.md'), 'core/说 明.md');
});

// ── 纯函数：splitHomePath / homeCrumbs ──────────────────────────────

test('splitHomePath：末段与父目录拆解', () => {
  assert.deepEqual(splitHomePath('core/scheduler.py'), { dir: 'core', name: 'scheduler.py' });
  assert.deepEqual(splitHomePath('a/b/c.txt'), { dir: 'a/b', name: 'c.txt' });
  assert.deepEqual(splitHomePath('README.md'), { dir: '', name: 'README.md' });
});

test('homeCrumbs：段数组不含根，根目录为空数组', () => {
  assert.deepEqual(homeCrumbs('core/dashboard'), ['core', 'dashboard']);
  assert.deepEqual(homeCrumbs('core'), ['core']);
  assert.deepEqual(homeCrumbs(''), []);
});

// ── 纯函数：formatRelativeTime ──────────────────────────────────────

test('formatRelativeTime：七档边界（秒/分/时/天/周/月/年）', () => {
  const now = Date.UTC(2026, 0, 15, 12, 0, 0); // 2026-01-15 12:00 UTC
  const ago = (s) => new Date(now - s * 1000).toISOString();
  assert.equal(formatRelativeTime(ago(30), now), '刚刚');
  assert.equal(formatRelativeTime(ago(60), now), '1 分钟前');
  assert.equal(formatRelativeTime(ago(59 * 60), now), '59 分钟前');
  assert.equal(formatRelativeTime(ago(60 * 60), now), '1 小时前');
  assert.equal(formatRelativeTime(ago(23 * 3600), now), '23 小时前');
  assert.equal(formatRelativeTime(ago(24 * 3600), now), '1 天前');
  assert.equal(formatRelativeTime(ago(6 * 86400), now), '6 天前');
  assert.equal(formatRelativeTime(ago(7 * 86400), now), '1 周前');
  assert.equal(formatRelativeTime(ago(29 * 86400), now), '4 周前');
  assert.equal(formatRelativeTime(ago(30 * 86400), now), '1 个月前');
  assert.equal(formatRelativeTime(ago(330 * 86400), now), '11 个月前');
  assert.equal(formatRelativeTime(ago(365 * 86400), now), '1 年前');
  assert.equal(formatRelativeTime(ago(800 * 86400), now), '2 年前');
});

test('formatRelativeTime：非法时间串与未来时间不炸不产生负数档', () => {
  const now = Date.UTC(2026, 0, 15, 12, 0, 0);
  assert.equal(formatRelativeTime('not-a-time', now), '—');
  // 时钟偏移 30 秒内按「刚刚」处理（不出现「-1 分钟前」）
  const future = new Date(now + 30 * 1000).toISOString();
  assert.equal(formatRelativeTime(future, now), '刚刚');
});

// ── 纯函数：formatBytes ─────────────────────────────────────────────

test('formatBytes：B/KB/MB 三档', () => {
  assert.equal(formatBytes(0), '0 B');
  assert.equal(formatBytes(1023), '1023 B');
  assert.equal(formatBytes(1024), '1.0 KB');
  assert.equal(formatBytes(262144), '256.0 KB');
  assert.equal(formatBytes(1024 * 1024), '1.00 MB');
  assert.equal(formatBytes(3.5 * 1024 * 1024), '3.50 MB');
});

// ── 页签接线（list.tsx 源码扫描）────────────────────────────────────

test('items 首位为 home 分面且透传 active 门控', () => {
  const src = listTsx();
  const itemsAt = src.indexOf("items={[");
  assert.notEqual(itemsAt, -1, 'list.tsx Tabs items 在位');
  const firstKey = src.slice(itemsAt).indexOf("key: 'home'");
  assert.ok(firstKey !== -1 && firstKey < 400, 'home 必须是 items 首位条目');
  const firstOther = src.slice(itemsAt).indexOf("key: 'dev'");
  assert.ok(firstOther > firstKey, 'dev 在 home 之后（位次保持不变）');
  assert.ok(src.includes("active={activeTab === 'home'}"), 'home 分面走 active 门控');
  assert.ok(src.includes('<ProjectHomeTab'), 'ProjectHomeTab 已接线');
});

test('缺省 tab 仍是 dev（缺省不写参语义零改动）', () => {
  const src = read('pages/projects/listFilters.ts');
  assert.ok(src.includes("'home' | 'dev'"), 'ListTab 六值含 home');
  assert.ok(src.includes("rawTab !== null && LIST_TABS.includes(rawTab) ? rawTab : 'dev'"),
    '解析缺省回退仍为 dev');
  assert.ok(listTsx().includes("if (activeTab !== 'dev') next.set('tab', activeTab);"),
    '缺省 dev 不写 tab 参的写回条件零改动');
});

test('path 参数随 tab=home 写入/移除（replace 语义并入既有写回块）', () => {
  const src = listTsx();
  assert.ok(src.includes("if (activeTab === 'home' && homePath) next.set('path', homePath);"),
    'path 仅 tab=home 且非根目录时写参');
  assert.ok(src.includes('setSearchParams(next, { replace: true });'),
    'replace 语义写回块零改动');
  // 写回块 deps 含 homePath（导航上行驱动写回）
  const depsLine = src.match(/\}, \[debouncedQ, statusList, type, archivedOnly, activeTab, homePath\]\)/);
  assert.ok(depsLine, '写回 effect deps 含 homePath');
  // 挂载读侧：仅 tab=home 时消费 path（脏参数不误读）
  assert.ok(src.includes("initialFilters.tab === 'home' ? searchParams.get('path') || '' : ''"),
    'homePath 挂载初值仅 tab=home 消费');
});

// ── 门控与缓存（ProjectHomeTab.tsx 源码扫描）────────────────────────

test('active 门控：未选中零请求、在飞结果静默丢弃', () => {
  const src = homeTsx();
  assert.ok(src.includes('if (!active) return;'), 'effect 首行 active 门控（未选中零请求）');
  assert.ok(src.includes('let cancelled = false;'), '在飞结果经 cancelled 闭包作废');
  assert.ok(src.includes('cancelled = true;'), 'cleanup 置 cancelled（切离丢弃）');
});

test('进程内缓存：列表/内容 useRef Map、组件卸载即弃', () => {
  const src = homeTsx();
  assert.ok(src.includes('useRef<Map<string, ProjectFilesListData>>(new Map())'),
    '列表缓存 useRef Map');
  assert.ok(src.includes('useRef<Map<string, ProjectFileContentData>>(new Map())'),
    '内容缓存 useRef Map');
  assert.ok(src.includes('listCacheRef.current.get(') && src.includes('listCacheRef.current.set('),
    '列表缓存命中免请求');
  assert.ok(src.includes('contentCacheRef.current.get(') && src.includes('contentCacheRef.current.set('),
    '内容缓存命中免请求');
});

test('initialPath 直达：先目录探测、404 回退父目录 + 文件命中', () => {
  const src = homeTsx();
  assert.ok(src.includes('seedRef'), 'seedRef 只解析一次');
  assert.ok(src.includes('fetchProjectFileList(project, seed)'), 'seed 先按目录探测');
  assert.ok(src.includes('splitHomePath(seed)'), '404 后拆父目录');
  assert.ok(src.includes('fetchProjectFileContent(project, seed)'), '文件命中走内容通道');
});

// ── 渲染锚（源码扫描）───────────────────────────────────────────────

test('窄屏列分流：hidden 随 isMobile（仅名称列）', () => {
  const src = homeTsx();
  assert.ok(src.includes('hidden: isMobile'), '窄屏隐藏后两列');
  assert.equal(src.split("hidden: isMobile").length - 1, 2, '恰好后两列受控');
  assert.ok(src.includes("title: '最近提交信息'") && src.includes("title: '最近提交时间'"),
    '三列定义在位');
});

test('截断/二进制/非 git 渲染锚在位', () => {
  const src = homeTsx();
  assert.ok(src.includes('仅展示前 200 项'), '目录条目截断提示');
  assert.ok(src.includes('truncated_count'), '截断计数消费');
  assert.ok(src.includes('文件过大，仅展示前 256 KB，下载查看全文'), '内容截断提示');
  assert.ok(src.includes('二进制文件，暂不支持预览'), '二进制降级文案');
  assert.ok(src.includes('该项目不是 git 仓库或暂无提交历史'), '非 git 空态文案');
  assert.ok(src.includes('<Empty'), '非 git 用 Empty 组件');
  assert.ok(src.includes('只读浏览'), '工具栏只读提示');
});

test('打开文件隐藏 README 盒、回目录恢复（atRoot 联动）', () => {
  const src = homeTsx();
  assert.ok(src.includes("dir === '' && file === null ? dirData?.readme ?? null : null"),
    'readme 门槛 = 根目录且未打开文件');
  assert.ok(src.includes('atRoot && readmeData'), 'README 盒渲染条件含 atRoot');
});

test('Markdown 管线复用（MUST NOT 新写渲染路径）', () => {
  const src = homeTsx();
  assert.ok(src.includes("import { markdownComponents } from '@/components/markdown-shared'"),
    '复用 markdownComponents 安全渲染族');
  assert.ok(src.includes('remarkGfm'), 'GFM 插件在位');
  assert.ok(src.includes('const HOME_REMARK_PLUGINS = [remarkGfm];'),
    'remarkPlugins 模块级常量（引用稳定，对齐 KnowledgeTab 先例）');
  assert.ok(!src.includes('rehype-raw'), '禁 HTML 直渲管线');
});

test('分支 Select 单值只读（不提供切换）', () => {
  const src = homeTsx();
  const sel = src.indexOf('<Select');
  assert.notEqual(sel, -1, '工具栏 Select 在位');
  const seg = src.slice(sel, sel + 600);
  assert.ok(!seg.includes('onChange'), 'Select 无 onChange（单值只读）');
  assert.ok(seg.includes('dirData?.branch'), '选项来自当前分支');
});

test('时间与行数/字节 tabular-nums（4.1 数值排版契约）', () => {
  const src = homeTsx();
  assert.ok(src.includes("fontVariantNumeric: 'tabular-nums'"), 'tabular-nums 在位');
  assert.ok(src.includes('fontVariantNumeric'), '至少一处数值排版消费');
});

// ── 服务函数（services/dashboard.ts 源码扫描）───────────────────────

test('三 API 函数在位且 download 走 withApiBase 前缀化单点', () => {
  const src = dashTs();
  assert.ok(src.includes('export async function fetchProjectFileList('), 'list 函数在位');
  assert.ok(src.includes('export async function fetchProjectFileContent('), 'content 函数在位');
  assert.ok(src.includes('export function fetchProjectFileDownloadUrl('), 'downloadUrl 函数在位');
  assert.ok(
    src.includes("return withApiBase(`/api/project-files/download${q}`);"),
    'download URL 经 embedMount 前缀化单点（不经 fetch 的旁路先例）',
  );
  assert.ok(src.includes('/api/project-files/list') && src.includes('/api/project-files/content'),
    '端点路径在位');
  assert.ok(!/fetchProjectFile\w+\([^)]*\)[\s\S]{0,80}fetch\(/.test(src.slice(src.indexOf('add-project-home-tab'))),
    '三函数不经裸 fetch（统一走 request/withApiBase）');
});

test('list.tsx 引用 ProjectHomeTab 组件且源文件真实存在', () => {
  const src = listTsx();
  assert.ok(src.includes("import ProjectHomeTab from './components/ProjectHomeTab';"),
    'import 在位');
  assert.ok(readFileSync(join(SRC, 'pages/projects/components/ProjectHomeTab.tsx'), 'utf8')
    .includes('export default function ProjectHomeTab'), '组件文件真实存在且默认导出');
});
