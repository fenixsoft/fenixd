// projectHomeShared.ts — 项目首页页签纯函数（add-project-home-tab）
// 文案经 useIntl（i18n 修复轮 batch-P：本文件静态中文文案迁 i18n 目录）。
//
// 零依赖、无 JSX（node --test 直测形态，对齐 listFilters.ts 先例）：
// URL `path` 参数解析、路径拆解、面包屑段、相对时间与字节量展示文案、
// 文件类型分类（markdown/图片/代码/纯文本）与 Prism 语言映射
// （project-home-tab 增强 2026-11-10）。
// 合法性（containment）不在纯函数层负责——由后端 400/404 兜底。
//
// i18n 注记（batch-P）：本模块保持零 import，formatRelativeTime 只返回
// { id, values? } 描述符（intl 目录键 + ICU 占位值），展示文案由消费方
// （ProjectHomeTab.tsx）经 useIntl().formatMessage 解析。

/** URL `path` 参数归一化：按 '/' 拆段并剔除空段后重组——消化首尾斜杠与
 *  连续斜杠（'/core//dashboard/' → 'core/dashboard'）；null/空串回根目录
 *  空串。不触浏览器 URL（解码已由 URLSearchParams 完成）。 */
export function parseHomePath(raw: string | null | undefined): string {
  return (raw || '').split('/').filter(Boolean).join('/');
}

/** 路径拆解：末段与其父目录（'core/scheduler.py' → {dir:'core',
 *  name:'scheduler.py'}；无斜杠 → {dir:'', name:<原串>}）。入参须已经
 *  parseHomePath 归一化。 */
export function splitHomePath(p: string): { dir: string; name: string } {
  const i = p.lastIndexOf('/');
  return i >= 0 ? { dir: p.slice(0, i), name: p.slice(i + 1) } : { dir: '', name: p };
}

/** 面包屑段数组（不含根节点）：'core/dashboard' → ['core','dashboard']；
 *  根目录为空数组。 */
export function homeCrumbs(p: string): string[] {
  return p ? p.split('/').filter(Boolean) : [];
}

/** 相对时间描述符：intl 目录键 + ICU 占位值（batch-P）。展示文案由消费方
 *  useIntl().formatMessage(desc) 解析。 */
export interface RelativeTimeDescriptor {
  id: string;
  values?: Record<string, number>;
}

/** 相对时间描述符（spec「如『2 小时前』」；秒/分/时/天/周/月/年七档，原型
 *  出现过「N 周前」档）。非法时间串与未来时间（时钟偏移）回退「刚刚」/
 *  「—」档。数值部分由调用方以 tabular-nums 展示。 */
export function formatRelativeTime(iso: string, now: number = Date.now()): RelativeTimeDescriptor {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return { id: 'projects.homeShared.time.invalid' };
  const s = Math.max(0, Math.floor((now - t) / 1000));
  if (s < 60) return { id: 'projects.homeShared.time.justNow' };
  const m = Math.floor(s / 60);
  if (m < 60) return { id: 'projects.homeShared.time.minutesAgo', values: { n: m } };
  const h = Math.floor(m / 60);
  if (h < 24) return { id: 'projects.homeShared.time.hoursAgo', values: { n: h } };
  const d = Math.floor(h / 24);
  if (d < 7) return { id: 'projects.homeShared.time.daysAgo', values: { n: d } };
  if (d < 30) return { id: 'projects.homeShared.time.weeksAgo', values: { n: Math.floor(d / 7) } };
  const mo = Math.floor(d / 30);
  if (mo < 12) return { id: 'projects.homeShared.time.monthsAgo', values: { n: mo } };
  return { id: 'projects.homeShared.time.yearsAgo', values: { n: Math.max(1, Math.floor(d / 365)) } };
}

/** 字节量展示文案（自动档位）：<1024 原样 B；KB 档一位小数；MB 档
 *  两位小数；GB 档两位小数（2026-11-10 增强批次补 GB 档，供列表大小列）。
 *  数值一律按 1024 进制（即 KiB/MiB/GiB 口径）计算，标签沿用 KB/MB/GB——
 *  1024 进制配十进制标签是业界惯用展示，非严格 SI 十进制口径，勿据此
 *  「修正」；输出由 tests/projectHomeTab.test.mjs 逐字钉住。 */
export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(2)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/** 等宽字体栈（ProjectHomeTab 与 ProjectCodeBlock 共用；项目首页内容
 *  区与代码高亮块字体一致）。 */
export const MONO_FONT = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';

// ── 文件类型分类与 Prism 语言映射（project-home-tab 增强 2026-11-10）────
//
// 内容盒按文件类型分四路渲染：markdown → react-markdown 安全管线；
// 图片 → raw 通道 <img> 直显；代码 → PrismLight 高亮 + 行号；其余 →
// 纯文本 pre（原形态，5 点增强的兜底分支）。

/** 图片直显扩展集（不带点，不分大小写）。与后端
 *  ``core/dashboard/data/project_files.py`` 的 ``IMAGE_INLINE_TYPES``
 *  白名单镜像——raw 通道仅服务该集合；node 测试钉住两侧一致。 */
const IMAGE_EXTENSIONS = new Set([
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'ico', 'avif', 'svg',
]);

/** Markdown 扩展集（*.md / *.markdown 经安全管线渲染，而非纯文本）。 */
const MARKDOWN_EXTENSIONS = new Set(['md', 'markdown']);

/** 特定文件名（小写全名）→ Prism 语言：无扩展名/特殊命名的常见构建文件。 */
const NAME_TO_LANGUAGE: Record<string, string> = {
  makefile: 'makefile',
  dockerfile: 'docker',
  'cmakelists.txt': 'cmake',
};

/** 扩展名（小写，不带点）→ Prism 语言 id。仅收录 ProjectCodeBlock.tsx
 *  显式注册的语言集（PrismLight 不引全量 refractor，两侧由 node 测试
 *  钉住一致）；映射为 null 的扩展名走纯文本分支。 */
const EXT_TO_LANGUAGE: Record<string, string> = {
  // Web 前端（.vue 无独立 Prism 语法，映射 markup：单文件组件主体是模板）
  html: 'markup', htm: 'markup', xml: 'markup', svg: 'markup', vue: 'markup',
  js: 'javascript', mjs: 'javascript', cjs: 'javascript', jsx: 'jsx',
  ts: 'typescript', mts: 'typescript', cts: 'typescript', tsx: 'tsx',
  css: 'css', less: 'less', scss: 'scss', sass: 'sass',
  json: 'json', jsonc: 'json', json5: 'json',
  // 脚本与 Shell
  sh: 'bash', bash: 'bash', zsh: 'bash',
  ps1: 'powershell', psm1: 'powershell',
  bat: 'batch', cmd: 'batch',
  // 后端语言
  py: 'python', pyi: 'python', go: 'go', rs: 'rust', java: 'java',
  c: 'c', h: 'c', cpp: 'cpp', cc: 'cpp', cxx: 'cpp', hpp: 'cpp', hh: 'cpp',
  cs: 'csharp', php: 'php', rb: 'ruby', kt: 'kotlin', kts: 'kotlin',
  swift: 'swift', dart: 'dart', lua: 'lua', r: 'r', pl: 'perl', pm: 'perl',
  // 数据与配置
  yml: 'yaml', yaml: 'yaml', toml: 'toml',
  ini: 'ini', cfg: 'ini', conf: 'ini', properties: 'ini', env: 'ini',
  sql: 'sql', graphql: 'graphql', gql: 'graphql', proto: 'protobuf',
  // 构建与补丁
  mk: 'makefile', cmake: 'cmake', diff: 'diff', patch: 'diff',
};

/** 取文件名末段扩展名（小写，不带点）。点开头的隐藏文件（.env、
 *  .editorconfig 等）剥掉前导点后按剩余部分参与映射（无第二点时剩余
 *  整段即扩展名，'.env' → 'env' → ini）；'.gitignore' 这类无语义扩展名
 *  的点文件不在映射表，归纯文本。本就无点的普通文件名（'py'、
 *  'LICENSE'）返回空串——无扩展名，避免恰好与已知扩展名同名的文件被
 *  误判出扩展名（fileKind 误入 code/image 通道）。导出供 ProjectFileIcon
 *  复用（纯函数）。 */
export function extOf(name: string): string {
  const lower = name.toLowerCase();
  const isDotFile = lower.startsWith('.');
  const stripped = isDotFile ? lower.slice(1) : lower;
  const i = stripped.lastIndexOf('.');
  if (i >= 0) return stripped.slice(i + 1);
  return isDotFile ? stripped : '';
}

/** 文件是否属图片直显集合（后端 raw 通道白名单的镜像；两侧一致由测试钉）。
 *  先归一化取 basename 再解析扩展名（同 fileKind/prismLanguageFor 口径），
 *  避免带点目录 + 无扩展名文件（如 'my.dir/README'）把目录段误当扩展名。 */
export function isImageFile(name: string): boolean {
  const basename = name.slice(name.lastIndexOf('/') + 1);
  return IMAGE_EXTENSIONS.has(extOf(basename));
}

/** 文件名 → Prism 语言 id；无映射返回 null（调用方按无语言渲染，不猜）。
 *  两处查表均用 hasOwnProperty 自有键防御（code-review item c0594477c6c6，
 *  口径同 SpecTimeline chainKindMeta / codeFixGuidance.isKnownReason）：对象
 *  字面量继承 Object.prototype，文件名/扩展名恰为 constructor/toString 等
 *  时普通查找命中继承键拿到函数（truthy），会把原型链函数当语言 id 透传给
 *  高亮器并把文件误分类为 code。 */
export function prismLanguageFor(name: string): string | null {
  const basename = name.slice(name.lastIndexOf('/') + 1).toLowerCase();
  const byName = Object.prototype.hasOwnProperty.call(NAME_TO_LANGUAGE, basename)
    ? NAME_TO_LANGUAGE[basename]
    : null;
  if (byName) return byName;
  const ext = extOf(basename);
  return ext && Object.prototype.hasOwnProperty.call(EXT_TO_LANGUAGE, ext)
    ? EXT_TO_LANGUAGE[ext]
    : null;
}

/** 内容盒渲染分类：markdown → 安全管线渲染；image → raw 通道直显；
 *  code → 高亮 + 行号；text → 纯文本兜底（非代码/非图片/非 markdown）。 */
export type ProjectFileKind = 'markdown' | 'image' | 'code' | 'text';

export function fileKind(name: string): ProjectFileKind {
  const ext = extOf(name.slice(name.lastIndexOf('/') + 1));
  if (MARKDOWN_EXTENSIONS.has(ext)) return 'markdown';
  if (isImageFile(name)) return 'image';
  if (prismLanguageFor(name) !== null) return 'code';
  return 'text';
}
