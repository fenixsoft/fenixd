// mermaid 初始化配置单源（help 页 renderMermaid 消费；tests/mermaidFontSize.test.mjs 直载断言）。
// 零依赖纯常量模块：node 原生 type-stripping 可直载——theme.ts 同为纯常量（无
// react/antd 依赖）可被跟随加载；相对路径须带 .ts 后缀（node ESM 裸解析不认
// 无扩展名；tsconfig allowImportingTsExtensions 已开，umi 产物同款形态）。

import { DSH_FONT_FAMILY } from '../../theme.ts';

/**
 * 图内文字与 Markdown 正文视觉一致。两个坑，都必须双层同设（缺一即回退默认）：
 *
 * 1. 字号：mermaid 顶层 `fontSize` 默认 **16**。sequence 图渲染时 db.init() →
 *    setConf(getConfig()) 级联 `actorFontSize = noteFontSize = messageFontSize =
 *    顶层 fontSize`——`sequence: { actorFontSize: 14, ... }` 子键单独设会被覆写
 *    （无效，实测 actor 默认 14 也被打成 16；A/B 见 tests/mermaidFontSize.test.mjs），
 *    顶层默认 16 就是 sequence 全族渲染 16px 的根因。`themeVariables.fontSize`
 *    是 flowchart / stateDiagram 等 label 的直接消费源，亦须同设。
 *
 * 2. 字体族：mermaid 默认栈 `trebuchet ms, verdana, arial, sans-serif` 与正文
 *    栈在本机解析到不同字体，**同 14px 观感大一号**（页内同字符串双栈并排实拍
 *    裁决，mermaid 栈显著更宽）——用户「图和字体太大」的可见主因，仅改字号
 *    数值看不出变化。顶层 `fontFamily` 取正文同栈（DSH_FONT_FAMILY）：
 *    initialize 自动透传 themeVariables.fontFamily，sequence 侧 setConf 级联
 *    `actor/note/messageFontFamily = 顶层 fontFamily`（此级联正是我们要的）。
 */
export const MERMAID_FONT_SIZE = 14;

/**
 * 按档构建 initialize 配置（2026-11-25 深色档验收）：浅档 'neutral'（低饱和
 * 文档形态，历史字节不变——测试 mermaidFontSize.test.mjs 直载断言其字段），
 * 深档 'dark'（mermaid 内置深色语义：节点深底/浅字/亮线，透明图底直接落在
 * 页面深色基上，边框/连接线/文字不再与黑底融合）。字号/字体双层配置两档同构，
 * 原因见类头注。
 */
function buildInitConfig(theme: 'neutral' | 'dark') {
  return {
    startOnLoad: false,
    theme,
    // strict（默认级别）：帮助文档 mermaid 图无 click 交互/图内 HTML 需求，
    // 保持 HTML/事件净化，避免文档内容引入外部内容时放大为 XSS 面
    securityLevel: 'strict' as const,
    fontFamily: DSH_FONT_FAMILY,
    fontSize: MERMAID_FONT_SIZE,
    themeVariables: { fontSize: `${MERMAID_FONT_SIZE}px` },
    // sequence 子键与顶层 fontSize 同值保留：当前被顶层级联覆写（等价），若未来
    // mermaid 移除级联则退回子键缺省（actor/note 14、message 16）时不至反弹
    sequence: { actorFontSize: MERMAID_FONT_SIZE, messageFontSize: MERMAID_FONT_SIZE, noteFontSize: MERMAID_FONT_SIZE },
  };
}

export const MERMAID_INIT_CONFIG = buildInitConfig('neutral');
export const MERMAID_INIT_CONFIG_DARK = buildInitConfig('dark');
