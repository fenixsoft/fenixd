// 弹窗最大化共享逻辑：标题栏最大化/还原按钮 + 几何参数切换。
// 最大化 = 占满视口（100vw × calc(100vh - 80px)、top 0）；还原 = 各弹窗默认宽高。
import { Button } from 'antd';
import { FullscreenExitOutlined, FullscreenOutlined } from '@ant-design/icons';
import { useCallback, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';

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
  const toggle = useCallback(() => setMaximized((v) => !v), []);

  const modalProps = maximized
    ? {
        width: '100vw' as string | number,
        centered: false,
        style: { top: 0, maxWidth: '100vw', paddingBottom: 0 } as CSSProperties | undefined,
        styles: {
          body: {
            // 80px = 标题栏 + 留白；带 footer 的弹窗再扣掉操作区，否则整窗超出视口
            height: `calc(100vh - ${80 + footerHeight}px)`,
            ...extraBodyStyle,
          },
        },
      }
    : {
        width: defaultWidth,
        centered: !!centered,
        style: undefined as CSSProperties | undefined,
        styles: {
          body: {
            height: defaultBodyHeight,
            ...extraBodyStyle,
          },
        },
      };

  // 按钮绝对定位到标题右侧：antd 关闭按钮为绝对定位（占 modal 右缘约 12~44px），
  // 按钮放其左侧；标题文本需预留右侧空间并允许断词换行，避免移动端重叠
  const maximizeButton: ReactNode = (
    <Button
      type="text"
      size="small"
      title={maximized ? '还原' : '最大化'}
      icon={maximized ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
      onClick={toggle}
      style={{ position: 'absolute', right: 24, top: -4 }}
    />
  );

  return { maximized, toggle, modalProps, maximizeButton };
}

// 标题容器标准包装：relative 定位承载最大化按钮，文本右留白防重叠
export function MaximizeTitle({ text, extra, button }: { text: ReactNode; extra?: ReactNode; button: ReactNode }) {
  return (
    <div style={{ position: 'relative' }}>
      <span style={{ display: 'inline-block', paddingRight: 56, wordBreak: 'break-all' }}>
        {text}
        {extra}
      </span>
      {button}
    </div>
  );
}
