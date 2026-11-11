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
//
// 增强（2026-11-10 五点增强批次）：
// - 纯函数：fileKind 四分类 / prismLanguageFor 映射（注册集一致性：映射值
//   ⊆ ProjectCodeBlock REGISTERED ⊆ 实际语言模块文件 ⊆ @types 声明）
// - 镜像钉：前端 IMAGE_EXTENSIONS ⊆ 后端 IMAGE_INLINE_TYPES（project_files.py）
// - 渲染锚：Bento 磁贴帧（#eef2f7 / 12px / 软阴影）、*.md 经 MarkdownBody、
//   图片 raw 通道 <img>（不经 content 通道）、代码块 PrismLight+行号、
//   纯文本兜底、raw 服务函数
//
// 增强（2026-11-10 第二批）：
// - 工具栏标头取消，分支 Select 移入最近提交条右侧（减面积）
// - 大小列（文件 bytes → formatBytes B/KB/MB/GB 自动档位；目录「目录」）
// - 文件夹图标蓝色（antd blue-6；单源常量 ICON_BLUE 迁至 ProjectFileIcon）
//
// 增强（2026-11-10 第三批）：
// - 文件图标蓝色 + simple-icons 常用扩展名品牌图标（ProjectFileIcon 三级映射）
// - 面包屑根目录整条隐藏，进入目录后才显示
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { createRequire } from 'node:module';
import {
  parseHomePath,
  splitHomePath,
  homeCrumbs,
  formatRelativeTime,
  formatBytes,
  fileKind,
  prismLanguageFor,
} from '../src/pages/projects/components/projectHomeShared.ts';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, '../src');
const read = (p) => readFileSync(join(SRC, p), 'utf8');
const listTsx = () => read('pages/projects/list.tsx');
const homeTsx = () => read('pages/projects/components/ProjectHomeTab.tsx');
const iconTsx = () => read('pages/projects/components/ProjectFileIcon.tsx');
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

test('formatBytes：B/KB/MB/GB 四档', () => {
  assert.equal(formatBytes(0), '0 B');
  assert.equal(formatBytes(1023), '1023 B');
  assert.equal(formatBytes(1024), '1.0 KB');
  assert.equal(formatBytes(262144), '256.0 KB');
  assert.equal(formatBytes(1024 * 1024), '1.00 MB');
  assert.equal(formatBytes(3.5 * 1024 * 1024), '3.50 MB');
  assert.equal(formatBytes(512 * 1024 * 1024), '512.00 MB');
  assert.equal(formatBytes(1024 * 1024 * 1024), '1.00 GB');
  assert.equal(formatBytes(2.75 * 1024 * 1024 * 1024), '2.75 GB');
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
  assert.ok(src.includes('hidden: isMobile'), '窄屏隐藏后三列');
  assert.equal(src.split("hidden: isMobile").length - 1, 3, '恰好后三列受控');
  assert.ok(src.includes("title: '大小'") && src.includes("title: '最近提交信息'") && src.includes("title: '最近提交时间'"),
    '四列定义在位');
});

test('大小列：文件 bytes 格式化、目录显示「目录」（2026-11-10 增强；2026-11-11 左对齐修正）', () => {
  const src = homeTsx();
  assert.ok(src.includes("dataIndex: 'bytes'"), '大小列消费后端 bytes 字段');
  assert.ok(src.includes("r.dir ? '目录' : v !== null && v !== undefined ? formatBytes(v) : '—'"),
    '目录/文件/空值三态文案');
  assert.ok(iconTsx().includes("export const ICON_BLUE = '#1677ff'"), '图标蓝色常量（antd blue-6，单源在 ProjectFileIcon）');
  assert.ok(homeTsx().includes('<FolderOutlined'), '文件夹图标在位');
  assert.ok(homeTsx().includes('r.hidden ? DSH_TEXT_TERTIARY : ICON_BLUE'), '可见文件夹蓝色、hidden 文件夹灰色');
  assert.ok(homeTsx().includes("<ProjectFileIcon name={r.name} muted={r.hidden === true} />"), '表格文件行消费类型图标组件（hidden 行灰显）');
  const sizeSeg = src.slice(src.indexOf("dataIndex: 'bytes'"), src.indexOf("dataIndex: 'bytes'") + 700);
  assert.ok(sizeSeg.includes("textAlign: 'left'"), '大小列左对齐（2026-11-11 用户修正）');
  assert.ok(!sizeSeg.includes("textAlign: 'right'"), '大小列不再右对齐');
});

test('隐藏文件（2026-11-11）：hidden 条目灰显与接口钉', () => {
  const src = homeTsx();
  assert.ok(src.includes('r.hidden ? DSH_TEXT_TERTIARY : ICON_BLUE'), 'hidden 目录图标灰显');
  assert.ok(src.includes("color: r.hidden ? DSH_TEXT_TERTIARY : undefined"), 'hidden 名称文案灰显');
  assert.ok(src.includes('r.dir || r.hidden ? DSH_TEXT_TERTIARY : DSH_TEXT_SECONDARY'), 'hidden 大小列灰显');
  assert.ok(iconTsx().includes('muted?: boolean'), 'ProjectFileIcon 支持灰显形态');
  assert.ok(iconTsx().includes('export const ICON_MUTED = DSH_TEXT_TERTIARY'), '图标灰与主题次级文本同源');
  assert.ok(iconTsx().includes('fill={muted ? ICON_MUTED : `#${g.hex}`}'), 'si 品牌图标灰显降级');
  const seg = dashTs().slice(dashTs().indexOf('export interface ProjectFileEntry'));
  assert.ok(seg.slice(0, 400).includes('hidden?: boolean'), 'ProjectFileEntry 声明 hidden');
});

test('列表接口附 bytes 字段（services/dashboard.ts 接口钉）', () => {
  const src = dashTs();
  const seg = src.slice(src.indexOf('export interface ProjectFileEntry'));
  assert.ok(seg.slice(0, 320).includes('bytes: number | null'),
    'ProjectFileEntry 声明 bytes（目录 null）');
});

test('工具栏标头已取消、分支 Select 移入最近提交条右侧（2026-11-10 增强）', () => {
  const src = homeTsx();
  assert.ok(!src.includes('project-home-toolbar'), '工具栏 testid 不再存在');
  assert.ok(!src.includes('只读浏览'), '工具栏只读提示一并移除');
  // Select 位于 latest-commit 条标记之后（同条内渲染，提交信息右侧）
  const bar = src.indexOf('data-testid="project-home-latest-commit"');
  const sel = src.indexOf('<Select');
  assert.ok(bar !== -1 && sel > bar, 'Select 在最近提交条内');
  const seg = src.slice(sel, sel + 600);
  assert.ok(!seg.includes('onChange'), 'Select 无 onChange（单值只读）');
  assert.ok(seg.includes('dirData.branch'), '选项来自当前分支（条内已被 dirData?.branch 门控）');
});

// ── 2026-11-10 第三批增强：扩展名图标库 + 面包屑按目录显示 ──────────

test('文件图标：simple-icons 具名子集与安装包一致（镜像钉）', () => {
  const src = iconTsx();
  assert.ok(src.includes("from 'simple-icons'"), '引入 simple-icons 图标库');
  const refs = [...new Set([...src.matchAll(/\bsi[A-Z][A-Za-z0-9]*\b/g)].map((m) => m[0]))];
  const si = createRequire(import.meta.url)('simple-icons');
  for (const name of refs) assert.ok(!!si[name], `simple-icons 导出 ${name}`);
  assert.ok(refs.length >= 25, `常用扩展名图标集规模（${refs.length}）`);
});

test('文件图标映射：扩展名/文件名两级钉（源码扫描）', () => {
  const src = iconTsx();
  for (const pin of [
    "ts: 'typescript'",
    "py: 'python'",
    "vue: 'vuedotjs'",
    "rs: 'rust'",
    "go: 'go'",
    "yml: 'yaml'",
    "'dockerfile': 'docker'",
    "'package.json': 'npm'",
    "'.gitignore': 'git'",
  ]) {
    assert.ok(src.includes(pin), `EXT_TO_SI/NAME_TO_SI 钉：${pin}`);
  }
  for (const pin of [
    "md: 'FileMarkdownOutlined'",
    "png: 'FileImageOutlined'",
    "zip: 'FileZipOutlined'",
    "pdf: 'FilePdfOutlined'",
    "csv: 'FileExcelOutlined'",
    "sql: 'DatabaseOutlined'",
  ]) {
    assert.ok(src.includes(pin), `EXT_TO_ANTD 钉：${pin}`);
  }
  assert.ok(src.includes('export function fileIconKind'), '纯函数 fileIconKind 导出');
  assert.ok(src.includes('return <Ic style={{ color: muted ? ICON_MUTED : ICON_BLUE'), 'antd 分支蓝色渲染（muted 灰显）');
  assert.ok(src.includes("import { extOf } from './projectHomeShared'"), '复用 extOf 纯函数');
});

test('面包屑：根目录整条隐藏，进入目录才显示（2026-11-10 增强）', () => {
  const src = homeTsx();
  assert.ok(src.includes("{dir !== '' && ("), '面包屑被 dir 非空门控包裹');
  const i = src.indexOf('data-testid="project-home-breadcrumb"');
  assert.ok(i !== -1, '面包屑 testid 在位');
  assert.ok(src.slice(Math.max(0, i - 160), i).includes("dir !== ''"), 'testid 处于 dir 门控内');
});

test('截断/二进制/非 git 渲染锚在位', () => {
  const src = homeTsx();
  assert.ok(src.includes('仅展示前 200 项'), '目录条目截断提示');
  assert.ok(src.includes('truncated_count'), '截断计数消费');
  assert.ok(src.includes('文件过大，仅展示前 256 KB，下载查看全文'), '内容截断提示');
  assert.ok(src.includes('二进制文件，暂不支持预览'), '二进制降级文案');
  assert.ok(src.includes('该项目不是 git 仓库或暂无提交历史'), '非 git 空态文案');
  assert.ok(src.includes('<Empty'), '非 git 用 Empty 组件');
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

// ── 增强：fileKind 四分类（纯函数直测）──────────────────────────────

test('fileKind：markdown/图片/代码/纯文本四分类', () => {
  assert.equal(fileKind('README.md'), 'markdown');
  assert.equal(fileKind('docs/guide.markdown'), 'markdown');
  assert.equal(fileKind('assets/logo.png'), 'image');
  assert.equal(fileKind('photo.JPG'), 'image'); // 大小写不敏感
  assert.equal(fileKind('icon.svg'), 'image');
  assert.equal(fileKind('src/app.py'), 'code');
  assert.equal(fileKind('main.tsx'), 'code');
  assert.equal(fileKind('Makefile'), 'code');
  assert.equal(fileKind('Dockerfile'), 'code');
  assert.equal(fileKind('.env'), 'code'); // 点文件按扩展名参与映射（env→ini）
  assert.equal(fileKind('LICENSE'), 'text');
  assert.equal(fileKind('.gitignore'), 'text');
  assert.equal(fileKind('notes.txt'), 'text');
  assert.equal(fileKind('data.csv'), 'text');
});

test('prismLanguageFor：特定文件名优先、扩展名映射、无映射 null', () => {
  assert.equal(prismLanguageFor('Makefile'), 'makefile');
  assert.equal(prismLanguageFor('docker/Dockerfile'), 'docker'); // 取 basename
  assert.equal(prismLanguageFor('CMakeLists.txt'), 'cmake');
  assert.equal(prismLanguageFor('src/index.ts'), 'typescript');
  assert.equal(prismLanguageFor('src/app.vue'), 'markup'); // .vue 无独立语法映射模板
  assert.equal(prismLanguageFor('README.md'), null); // markdown 走管线，不需要语言
  assert.equal(prismLanguageFor('unknown.xyz'), null);
});

test('语言映射一致性：EXT/NAME 映射值 ⊆ ProjectCodeBlock 注册集 ⊆ 实际模块文件', () => {
  const shared = read('pages/projects/components/projectHomeShared.ts');
  const codeBlock = read('pages/projects/components/ProjectCodeBlock.tsx');
  // 注册集（REGISTERED 数组 ['name', xxx] 形态）
  const registered = [...codeBlock.matchAll(/\['([a-z]+)',\s*\w+\]/g)].map((m) => m[1]);
  assert.ok(registered.length >= 30, `显式注册语言集在位（当前 ${registered.length} 个）`);
  assert.ok(codeBlock.includes('PrismLight as SyntaxHighlighter'),
    'PrismLight 轻量构建（非全量 Prism，避免首屏 chunk 膨胀）');
  // 映射值 ⊆ 注册集（fileKind=code 保证有语言可高亮）
  const mapValues = new Set();
  for (const m of shared.matchAll(/: '([a-z]+)'/g)) mapValues.add(m[1]);
  for (const v of mapValues) {
    assert.ok(registered.includes(v), `映射值 '${v}' 必须在 ProjectCodeBlock 注册集内`);
  }
  // 注册集 ⊆ 实际存在的语言模块文件（防 typo 引入不存在的模块）
  const langDir = join(SRC, '..', 'node_modules/react-syntax-highlighter/dist/esm/languages/prism');
  for (const name of registered) {
    assert.ok(existsSync(join(langDir, `${name}.js`)), `语言模块 ${name}.js 实际存在`);
  }
});

test('镜像钉：前端 IMAGE_EXTENSIONS ⊆ 后端 IMAGE_INLINE_TYPES（project_files.py）', () => {
  const shared = read('pages/projects/components/projectHomeShared.ts');
  const feSegStart = shared.indexOf('const IMAGE_EXTENSIONS');
  assert.notEqual(feSegStart, -1, '前端图片扩展集在位');
  const feSeg = shared.slice(feSegStart, shared.indexOf(']);', feSegStart));
  const feExts = [...feSeg.matchAll(/'([a-z]+)'/g)].map((m) => m[1]);
  assert.ok(feExts.length >= 9, `前端图片扩展集完整（当前 ${feExts.length} 个）`);
  const py = readFileSync(
    join(SRC, '../..', 'data/project_files.py'), 'utf8');
  const beAt = py.indexOf('IMAGE_INLINE_TYPES');
  assert.notEqual(beAt, -1, '后端 IMAGE_INLINE_TYPES 在位');
  const beSeg = py.slice(beAt, py.indexOf('}', beAt));
  for (const ext of feExts) {
    assert.ok(beSeg.includes(`".${ext}"`) || beSeg.includes(`'.${ext}'`),
      `扩展 .${ext} 后端白名单镜像在位`);
  }
});

// ── 增强：Bento 帧 + 内容盒四路渲染（源码扫描）──────────────────────

test('三卡 Bento 磁贴帧：#eef2f7 发丝边 + 12px 圆角 + 软阴影（域条款值）', () => {
  const src = homeTsx();
  assert.ok(src.includes("const TILE_BORDER = '#eef2f7';"), '发丝边色在位');
  assert.ok(src.includes('borderRadius: 12'), '12px 圆角在位');
  assert.ok(src.includes("'0 1px 3px rgba(15, 23, 42, 0.05), 0 1px 2px rgba(15, 23, 42, 0.03)'"),
    '软阴影条款值在位');
  assert.ok(src.includes('...TILE_FRAME'), '三卡统一展开 TILE_FRAME');
  const frameUses = src.split('TILE_FRAME').length - 1;
  assert.ok(frameUses >= 4, '帧常量定义 + 三处消费');
});

test('*.md 文件经 MarkdownBody 安全管线（与 README 同源）', () => {
  const src = homeTsx();
  assert.ok(src.includes("viewKind === 'markdown'"), 'markdown 分支在位');
  assert.ok(src.includes('<MarkdownBody content={fileData.content'), '*.md 走 MarkdownBody');
  assert.ok(src.includes('<MarkdownBody content={readmeData.content'), 'README 同源复用');
  assert.ok(src.includes('function MarkdownBody'), '单源组件定义');
});

test('图片直显：raw 通道 <img>（不经 content 通道）', () => {
  const src = homeTsx();
  assert.ok(src.includes("fileKind(filePath) === 'image'"), '内容 effect 图片短路');
  assert.ok(src.includes('<FileImagePreview'), '图片预览组件挂载');
  assert.ok(src.includes('fetchProjectFileRawUrl(project, path)'), '<img src 用 raw 直链');
  assert.ok(src.includes('project-home-image'), 'testid 锚（冒烟与回归定位）');
  assert.ok(src.includes('图片加载失败'), '加载失败降级提示');
  // 图片不进 content 缓存通道：seed 直达与 effect 均先判 kind
  assert.ok(src.includes("fileKind(seed) !== 'image'"), 'seed 直达跳过图片 content 请求');
});

test('代码高亮块：PrismLight + 行号 + oneLight（react-syntax-highlighter）', () => {
  const src = read('pages/projects/components/ProjectCodeBlock.tsx');
  assert.ok(src.includes('PrismLight as SyntaxHighlighter'), '轻量构建非全量 Prism');
  assert.ok(src.includes('SyntaxHighlighter.registerLanguage('), '显式注册语言集');
  assert.ok(src.includes('showLineNumbers'), '行号显示在位');
  assert.ok(src.includes("import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'"),
    'oneLight 主题与 claude-msg 视觉基线同源');
  assert.ok(src.includes('prismLanguageFor(path)'), '语言取自共享映射');
});

test('纯文本兜底：非代码/非图片/非 markdown 才走 pre（原形态保留）', () => {
  const src = homeTsx();
  assert.ok(src.includes("viewKind === 'code'"), 'code 分支在位');
  assert.ok(src.includes('<ProjectCodeBlock path={filePath}'), '代码分支挂高亮块');
  const preAt = src.indexOf('<pre');
  assert.notEqual(preAt, -1, '纯文本 pre 兜底仍在位');
  assert.ok(src.slice(preAt - 200, preAt).includes('兜底'), 'pre 标注为兜底分支');
});

test('raw 服务函数在位且与 download 同走 withApiBase 前缀化单点', () => {
  const src = dashTs();
  assert.ok(src.includes('export function fetchProjectFileRawUrl('), 'raw 函数在位');
  assert.ok(src.includes('return withApiBase(`/api/project-files/raw${q}`);'),
    'raw URL 经 withApiBase 前缀化单点');
  assert.ok(src.includes('/api/project-files/raw'), '端点路径在位');
  const home = homeTsx();
  assert.ok(home.includes('fetchProjectFileRawUrl,'), 'ProjectHomeTab 已接线 raw 函数');
});
