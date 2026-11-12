/**
 * ProjectCodeBlock — 项目首页文件查看的代码高亮块（project-home-tab 增强）。
 *
 * 选型（已上网调研 + 本地验证）：react-syntax-highlighter 的 PrismLight
 * 轻量构建 + 显式注册常用语言集——vuepress v1 内置为 highlight.js、v2 为
 * shiki，均需新增依赖；本库已在依赖树（claude-msg 视觉基线同源 oneLight），
 * 且 PrismLight 只打包显式注册的语言，避免全量 Prism 把 refractor 全部语法
 * 拖进 list.tsx 首屏 chunk（claude-msg 链路在异步 chunk，前例不可照搬）。
 * 未知语言经 refractor 分支安全回退纯文本，不崩。
 */
import { theme } from 'antd';

import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';

import { prismLanguageFor } from './projectHomeShared';

// 显式注册常用语言集（各语法模块自带依赖链，注册顺序无约束）。
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash';
import batch from 'react-syntax-highlighter/dist/esm/languages/prism/batch';
import c from 'react-syntax-highlighter/dist/esm/languages/prism/c';
import cmake from 'react-syntax-highlighter/dist/esm/languages/prism/cmake';
import cpp from 'react-syntax-highlighter/dist/esm/languages/prism/cpp';
import csharp from 'react-syntax-highlighter/dist/esm/languages/prism/csharp';
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css';
import dart from 'react-syntax-highlighter/dist/esm/languages/prism/dart';
import diff from 'react-syntax-highlighter/dist/esm/languages/prism/diff';
import docker from 'react-syntax-highlighter/dist/esm/languages/prism/docker';
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go';
import graphql from 'react-syntax-highlighter/dist/esm/languages/prism/graphql';
import ini from 'react-syntax-highlighter/dist/esm/languages/prism/ini';
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java';
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript';
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json';
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx';
import kotlin from 'react-syntax-highlighter/dist/esm/languages/prism/kotlin';
import less from 'react-syntax-highlighter/dist/esm/languages/prism/less';
import lua from 'react-syntax-highlighter/dist/esm/languages/prism/lua';
import makefile from 'react-syntax-highlighter/dist/esm/languages/prism/makefile';
import markup from 'react-syntax-highlighter/dist/esm/languages/prism/markup';
import perl from 'react-syntax-highlighter/dist/esm/languages/prism/perl';
import php from 'react-syntax-highlighter/dist/esm/languages/prism/php';
import powershell from 'react-syntax-highlighter/dist/esm/languages/prism/powershell';
import protobuf from 'react-syntax-highlighter/dist/esm/languages/prism/protobuf';
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python';
import r from 'react-syntax-highlighter/dist/esm/languages/prism/r';
import ruby from 'react-syntax-highlighter/dist/esm/languages/prism/ruby';
import rust from 'react-syntax-highlighter/dist/esm/languages/prism/rust';
import sass from 'react-syntax-highlighter/dist/esm/languages/prism/sass';
import scss from 'react-syntax-highlighter/dist/esm/languages/prism/scss';
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql';
import swift from 'react-syntax-highlighter/dist/esm/languages/prism/swift';
import toml from 'react-syntax-highlighter/dist/esm/languages/prism/toml';
import tsx from 'react-syntax-highlighter/dist/esm/languages/prism/tsx';
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript';
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml';

const REGISTERED: Array<[string, unknown]> = [
  ['bash', bash],
  ['batch', batch],
  ['c', c],
  ['cmake', cmake],
  ['cpp', cpp],
  ['csharp', csharp],
  ['css', css],
  ['dart', dart],
  ['diff', diff],
  ['docker', docker],
  ['go', go],
  ['graphql', graphql],
  ['ini', ini],
  ['java', java],
  ['javascript', javascript],
  ['json', json],
  ['jsx', jsx],
  ['kotlin', kotlin],
  ['less', less],
  ['lua', lua],
  ['makefile', makefile],
  ['markup', markup],
  ['perl', perl],
  ['php', php],
  ['powershell', powershell],
  ['protobuf', protobuf],
  ['python', python],
  ['r', r],
  ['ruby', ruby],
  ['rust', rust],
  ['sass', sass],
  ['scss', scss],
  ['sql', sql],
  ['swift', swift],
  ['toml', toml],
  ['tsx', tsx],
  ['typescript', typescript],
  ['yaml', yaml],
];

for (const [name, grammar] of REGISTERED) {
  SyntaxHighlighter.registerLanguage(name, grammar);
}

interface ProjectCodeBlockProps {
  path: string;
  content: string;
}

export function ProjectCodeBlock({ path, content }: ProjectCodeBlockProps) {
  // 颜色经 theme token 引用（project-home-tab 界面形态规则；SpecTimeline/
  // detail 同款 useToken 用法，只能在组件内调用）。
  const { token } = theme.useToken();
  return (
    <SyntaxHighlighter
      // ?? 'text'：PrismLight 的 language 类型不接受 null；'text' 非注册语言
      // 时 refractor 分支安全短路纯文本（ProjectHomeTab 仅在 code 分支挂载，
      // 实际不会命中，类型层兜底）。
      language={prismLanguageFor(path) ?? 'text'}
      style={oneLight}
      showLineNumbers
      wrapLongLines={false}
      customStyle={{
        margin: 0,
        borderRadius: 0,
        background: token.colorBgContainer,
        fontSize: 13,
        lineHeight: 1.6,
      }}
      codeTagProps={{
        style: { fontFamily: 'inherit', background: 'transparent' },
      }}
    >
      {content}
    </SyntaxHighlighter>
  );
}
