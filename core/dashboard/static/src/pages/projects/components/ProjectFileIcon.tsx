/**
 * 项目首页文件类型图标（2026-11-10 第三批增强）。
 *
 * 三级映射：
 * 1. 常用扩展名/知名文件名 → simple-icons 品牌图标（具名导入，构建期仅打包被选
 *    图标的路径数据；按品牌色渲染，如 TS/Vue/Python 各自识别色）；
 * 2. 其余可识别扩展名 → @ant-design/icons 文件型图标（蓝色 antd blue-6，与
 *    文件夹图标同源，替代原次级灰）；
 * 3. 未知类型 → FileOutlined 兜底（同蓝色）。
 *
 * muted 形态（2026-11-11）：git 忽略项（hidden）行整体灰显——品牌色与蓝
 * 统一降为 ICON_MUTED（与表格 hidden 文案灰同源）。
 *
 * fileIconKind 是纯函数，供 node --test 直测与源码扫描钉覆盖。
 */
import type { ComponentType, CSSProperties } from 'react';
import {
  AudioOutlined,
  CodeOutlined,
  DatabaseOutlined,
  FileExcelOutlined,
  FileImageOutlined,
  FileMarkdownOutlined,
  FileOutlined,
  FilePdfOutlined,
  FilePptOutlined,
  FileTextOutlined,
  FileWordOutlined,
  FileZipOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons';
import {
  siC,
  siCplusplus,
  siCss,
  siDart,
  siDocker,
  siGit,
  siGnubash,
  siGo,
  siGraphql,
  siHtml5,
  siJavascript,
  siJson,
  siKotlin,
  siLess,
  siLua,
  siNpm,
  siPhp,
  siPnpm,
  siPython,
  siR,
  siReact,
  siRuby,
  siRust,
  siSass,
  siShell,
  siSwift,
  siToml,
  siTypescript,
  siVuedotjs,
  siWebassembly,
  siYaml,
} from 'simple-icons';
import { extOf } from './projectHomeShared';
import { DSH_TEXT_TERTIARY } from '@/theme';

/** 类型图标蓝（antd blue-6，与文件夹图标同源；文件夹/文件图标统一蓝色系） */
export const ICON_BLUE = '#1677ff';

/** 图标灰（git 忽略项 hidden 行，2026-11-11）：与主题次级文本同源 */
export const ICON_MUTED = DSH_TEXT_TERTIARY;

/** simple-icons 具名子集（slug → { path, hex, title }；仅打包被选项） */
const SI: Record<string, { path: string; hex: string; title: string }> = {
  c: siC,
  cplusplus: siCplusplus,
  css: siCss,
  dart: siDart,
  docker: siDocker,
  git: siGit,
  gnubash: siGnubash,
  go: siGo,
  graphql: siGraphql,
  html5: siHtml5,
  javascript: siJavascript,
  json: siJson,
  kotlin: siKotlin,
  less: siLess,
  lua: siLua,
  npm: siNpm,
  php: siPhp,
  pnpm: siPnpm,
  python: siPython,
  r: siR,
  react: siReact,
  ruby: siRuby,
  rust: siRust,
  sass: siSass,
  shell: siShell,
  swift: siSwift,
  toml: siToml,
  typescript: siTypescript,
  vuedotjs: siVuedotjs,
  webassembly: siWebassembly,
  yaml: siYaml,
};

/** 扩展名 → simple-icons slug（key 均小写，消费前统一 toLowerCase） */
const EXT_TO_SI: Record<string, string> = {
  ts: 'typescript',
  tsx: 'typescript',
  mts: 'typescript',
  cts: 'typescript',
  js: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  py: 'python',
  jsx: 'react',
  vue: 'vuedotjs',
  rs: 'rust',
  go: 'go',
  html: 'html5',
  htm: 'html5',
  css: 'css',
  sass: 'sass',
  scss: 'sass',
  less: 'less',
  c: 'c',
  h: 'c',
  cpp: 'cplusplus',
  cc: 'cplusplus',
  cxx: 'cplusplus',
  hpp: 'cplusplus',
  kt: 'kotlin',
  kts: 'kotlin',
  swift: 'swift',
  rb: 'ruby',
  php: 'php',
  lua: 'lua',
  r: 'r',
  graphql: 'graphql',
  gql: 'graphql',
  yml: 'yaml',
  yaml: 'yaml',
  json: 'json',
  sh: 'gnubash',
  bash: 'gnubash',
  zsh: 'shell',
  dart: 'dart',
  toml: 'toml',
  wasm: 'webassembly',
};

/** 知名文件名（全小写匹配）→ simple-icons slug */
const NAME_TO_SI: Record<string, string> = {
  'dockerfile': 'docker',
  'package.json': 'npm',
  'package-lock.json': 'npm',
  'pnpm-lock.yaml': 'pnpm',
  'pnpm-workspace.yaml': 'pnpm',
  '.gitignore': 'git',
  '.gitattributes': 'git',
  '.gitmodules': 'git',
};

/** 其余可识别扩展名 → @ant-design/icons 文件型图标（蓝色） */
const EXT_TO_ANTD: Record<string, string> = {
  md: 'FileMarkdownOutlined',
  markdown: 'FileMarkdownOutlined',
  png: 'FileImageOutlined',
  jpg: 'FileImageOutlined',
  jpeg: 'FileImageOutlined',
  gif: 'FileImageOutlined',
  webp: 'FileImageOutlined',
  bmp: 'FileImageOutlined',
  ico: 'FileImageOutlined',
  avif: 'FileImageOutlined',
  svg: 'FileImageOutlined',
  zip: 'FileZipOutlined',
  gz: 'FileZipOutlined',
  tar: 'FileZipOutlined',
  rar: 'FileZipOutlined',
  '7z': 'FileZipOutlined',
  xz: 'FileZipOutlined',
  bz2: 'FileZipOutlined',
  pdf: 'FilePdfOutlined',
  xls: 'FileExcelOutlined',
  xlsx: 'FileExcelOutlined',
  csv: 'FileExcelOutlined',
  tsv: 'FileExcelOutlined',
  doc: 'FileWordOutlined',
  docx: 'FileWordOutlined',
  ppt: 'FilePptOutlined',
  pptx: 'FilePptOutlined',
  mp3: 'AudioOutlined',
  wav: 'AudioOutlined',
  flac: 'AudioOutlined',
  ogg: 'AudioOutlined',
  m4a: 'AudioOutlined',
  aac: 'AudioOutlined',
  mp4: 'VideoCameraOutlined',
  mov: 'VideoCameraOutlined',
  avi: 'VideoCameraOutlined',
  mkv: 'VideoCameraOutlined',
  webm: 'VideoCameraOutlined',
  sql: 'DatabaseOutlined',
  txt: 'FileTextOutlined',
  log: 'FileTextOutlined',
  cs: 'CodeOutlined',
  ps1: 'CodeOutlined',
  proto: 'CodeOutlined',
  java: 'CodeOutlined',
  scala: 'CodeOutlined',
  ini: 'FileTextOutlined',
  conf: 'FileTextOutlined',
  cfg: 'FileTextOutlined',
  env: 'FileTextOutlined',
};

/** 图标名 → 组件（文件型子集；兜底 FileOutlined） */
const ANTIC: Record<string, ComponentType<{ style?: CSSProperties }>> = {
  FileMarkdownOutlined,
  FileImageOutlined,
  FileZipOutlined,
  FilePdfOutlined,
  FileExcelOutlined,
  FileWordOutlined,
  FilePptOutlined,
  FileTextOutlined,
  AudioOutlined,
  VideoCameraOutlined,
  DatabaseOutlined,
  CodeOutlined,
};

export type FileIconKind =
  | { type: 'si'; slug: string }
  | { type: 'antd'; icon: string }
  | { type: 'generic' };

/** 纯函数：文件名 → 图标类别（si 品牌 / antd 蓝色文件图标 / 通用兜底） */
export function fileIconKind(name: string): FileIconKind {
  const byName = NAME_TO_SI[name.toLowerCase()];
  if (byName) return { type: 'si', slug: byName };
  const ext = extOf(name).toLowerCase();
  const byExt = EXT_TO_SI[ext];
  if (byExt && SI[byExt]) return { type: 'si', slug: byExt };
  const antd = EXT_TO_ANTD[ext];
  if (antd && ANTIC[antd]) return { type: 'antd', icon: antd };
  return { type: 'generic' };
}

export function ProjectFileIcon({
  name,
  style,
  muted,
}: {
  name: string;
  style?: CSSProperties;
  /** 灰显形态（git 忽略项行）：品牌色/蓝统一降为次级灰。 */
  muted?: boolean;
}) {
  const kind = fileIconKind(name);
  if (kind.type === 'si') {
    const g = SI[kind.slug];
    return (
      <svg
        viewBox="0 0 24 24"
        width="14"
        height="14"
        role="img"
        aria-label={g.title}
        style={{ flex: 'none', ...style }}
      >
        <path d={g.path} fill={muted ? ICON_MUTED : `#${g.hex}`} />
      </svg>
    );
  }
  const Ic = kind.type === 'antd' ? ANTIC[kind.icon] ?? FileOutlined : FileOutlined;
  return <Ic style={{ color: muted ? ICON_MUTED : ICON_BLUE, flex: 'none', ...style }} />;
}
