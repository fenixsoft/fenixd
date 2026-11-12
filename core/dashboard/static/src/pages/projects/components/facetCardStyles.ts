// facetCardStyles.ts — 项目页分面顶层卡体桌面内边距 8px 档共享助手
//
// 背景（2026-11-12 用户指令）：项目页「测试回归/架构蓝图/项目知识」三分面
// 顶层卡此前吃 antd 缺省 24px，与「功能开发」（list.tsx DevTab 卡挂
// .projects-page → global.less 8px 档，2026-11-04 收紧口径）并排切换观感
// 差异明显；参照 2026-11-11「代码审查」QualityTab 先例同款缩小。五分面
// （dev/quality/regression/architecture/knowledge）顶层卡体内边距自此单源。
//
// 移动端 MUST 保持 antd 缺省 24px 不动：facetWrap（list.tsx）的 -20px 负边距
// 抵消口径按 24px 卡体调校（抵后 4 + 容器 12 = 每侧 16px），改 8 会把两侧
// 压穿到负值。extraBody 供分面在 8px 档上追加/覆盖单边内边距（如
// KnowledgeTab 总目录视图保留 paddingTop: 0 顶贴分面导航），移动端同样生效。
import type { CSSProperties } from 'react';
import type { CardProps } from 'antd';

export function facetCardStyles(
  isMobile: boolean,
  extraBody?: CSSProperties,
): CardProps['styles'] {
  if (isMobile) {
    return extraBody ? { body: extraBody } : undefined;
  }
  // 内边距按单边键展开而非 `padding: 8` 缩写：实测 antd v6 css-var 模式下
  // Card 对 `styles.body` 的纯数字缩写会做样式合并/改写（仅传 padding 缩写时
  // padding-top 被默认 24px 顶回，见 2026-11-12 实拍 knowledge page-view），
  // 单边键则原样落地。extraBody 同名键按展开序覆盖（如 paddingTop: 0）。
  return {
    body: {
      paddingTop: 8,
      paddingRight: 8,
      paddingBottom: 8,
      paddingLeft: 8,
      ...extraBody,
    },
  };
}
