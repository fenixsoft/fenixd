// 弹窗最大化共享逻辑：标题栏最大化/还原按钮 + 几何参数切换。
// 最大化 = 占满视口（100% × calc(100dvh - 80px)、top 0）；还原 = 各弹窗默认宽高。
// 移动端（<768px）默认即全屏——还原态的 80% 宽高在窄屏可用面积太小，且与最大化
// 态重合后切换按钮无意义，一并隐藏；桌面端行为不变。
import { Button } from 'antd';
import { FullscreenExitOutlined, FullscreenOutlined } from '@ant-design/icons';
import { useCallback, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { useIsMobile } from '@/hooks/useIsMobile';

// 最大化态共享几何（供 RunRecordModal 等「打开即最大化」弹窗复用，避免与 hook 内双写漂移）。
// 宽用 100%（相对 fixed 弹层容器 content box）而非 100vw——100vw 含竖向滚动条宽度，经典滚动条
// 环境下最大化弹窗会横向溢出一条滚动条；高用 dvh（同 SessionPanel/ArchitectureTab 先例）避免
// 移动端地址栏收展时 100vh 大于实际可视高度、footer 被裁切。CSSProperties 同键双写会被覆盖，
// 无法表达 CSS 声明级回退，故与先例一致直接用 dvh 不留 vh 回退。
export const MAXIMIZED_WIDTH = '100%';
export const MAXIMIZED_MODAL_STYLE: CSSProperties = { top: 0, maxWidth: '100%', paddingBottom: 0 };
// 80px = 标题栏 + 留白；带 footer 的弹窗再扣掉操作区，否则整窗超出视口
export const maximizedBodyHeight = (footerHeight = 0): string => `calc(100dvh - ${80 + footerHeight}px)`;

interface UseMaximizeModalOptions {
  // 还原态尺寸
  defaultWidth: string | number;
  defaultBodyHeight: string | number;
  // body 除 height 外的样式（display/flexDirection/padding 等），两种状态共用
  extraBodyStyle?: CSSProperties;
  // 还原态是否垂直居中（最大化后始终贴顶）
  centered?: boolean;
  // 弹窗自带底部操作区时的 footer 高度（默认 0 = 无 footer）。
  // 仅参与最大化态的 body 高度扣减：还原态的 defaultBodyHeight 由调用方自行算好。
  footerHeight?: number;
}

export function useMaximizeModal({
  defaultWidth,
  defaultBodyHeight,
  extraBodyStyle,
  centered,
  footerHeight = 0,
}: UseMaximizeModalOptions) {
  const [maximized, setMaximized] = useState(false);
  const isMobile = useIsMobile();
  const toggle = useCallback(() => setMaximized((v) => !v), []);
  // 全屏布局状态（最大化或移动端默认全屏）：modalProps 与 MaximizeTitle 的标题
  // 截断共用这一显式布尔，调用方直接透传，不再依赖按钮元素上的隐式标记
  const isFullscreen = maximized || isMobile;

  const modalProps = isFullscreen
    ? {
        width: MAXIMIZED_WIDTH,
        centered: false,
        style: MAXIMIZED_MODAL_STYLE,
        styles: {
          body: {
            height: maximizedBodyHeight(footerHeight),
            ...extraBodyStyle,
          },
        },
      }
    : {
        width: defaultWidth,
        centered: !!centered,
        style: undefined,
        styles: {
          body: {
            height: defaultBodyHeight,
            ...extraBodyStyle,
          },
        },
      };

  // 按钮绝对定位到标题右侧：antd 关闭按钮为绝对定位（占 modal 右缘约 12~44px），
  // 按钮放其左侧；aria-label 提供显式可访问名（仅靠 title 属性对部分屏幕阅读器
  // /键盘场景不可靠）。全屏布局信号由返回值 isFullscreen 显式传递，MaximizeTitle
  // 据此把标题切成单行截断（header 不得突破 80px 预算）；还原态仍允许断词换行。
  // 移动端默认与最大化态重合，按钮不渲染（isFullscreen 已含 isMobile 分支）
  const maximizeButton: ReactNode = isMobile ? null : (
    <Button
      type="text"
      size="small"
      title={maximized ? '还原' : '最大化'}
      aria-label={maximized ? '还原' : '最大化'}
      icon={maximized ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
      onClick={toggle}
      style={{ position: 'absolute', right: 24, top: -4 }}
    />
  );

  return { maximized, toggle, modalProps, maximizeButton, isFullscreen };
}

// 标题容器标准包装：relative 定位承载最大化按钮，文本右留白防重叠；
// button 为 null（移动端）时仅保留关闭按钮需要的最小留白。
// 全屏态（最大化或移动端，即 maximizedBodyHeight 按 80px 标题栏预算扣减视口的状态）
// 标题必须单行截断：允许断词换行会让 header 实高超出 80px 预算，footer 被裁切；
// span 转 block 后 auto 宽度天然受限于容器（不依赖 box-sizing），ellipsis 截在按钮
// 留白之前，悬停 title 属性保留全文可读。还原态无此预算，维持断词换行。
export function MaximizeTitle({
  text,
  extra,
  button,
  isFullscreen,
}: {
  text: ReactNode;
  extra?: ReactNode;
  button: ReactNode;
  // 全屏态显式信号：由调用方从 useMaximizeModal 返回值透传（不再从按钮元素 props 反推）
  isFullscreen: boolean;
}) {
  return (
    <div style={{ position: 'relative' }}>
      <span
        title={isFullscreen && typeof text === 'string' ? text : undefined}
        style={{
          ...(isFullscreen
            ? { display: 'block', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }
            : { display: 'inline-block', wordBreak: 'break-all' }),
          paddingRight: button ? 56 : 12,
        }}
      >
        {text}
        {extra}
      </span>
      {button}
    </div>
  );
}
