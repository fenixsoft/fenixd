/**
 * DshIconButton —— dsh 侧栏「新会话」按钮的图标态壳（2026-11-16 用户需求：
 * SPEC 列表页右上角按钮对「只显示图标，不显示文字」）。
 *
 * 基准形态取证自 @deepseek-ai/dsh-client-ui-sidebar 的 newSession 类：
 * wide 展开态提供描边 / 圆角 / 底色 / 高度基线（38px 高、0.5px alias-border-l3
 * 描边、radius-md 12px 圆角、alias-button-elevated-fill 白底、flex 居中）；
 * 图标态收为 38×38 方形居中——dsh 侧栏窄档图标态（background:0 0;
 * border-color:#0000;width:36px;height:36px;padding:0）的同构读法，保留
 * 描边与白底以在 dashboard 白底标题栏上可见，尺寸取 38 与 wide 档同高。
 * 图标尺寸由调用方传入（new-chat 16 视窗渲染 16px、antd 图标 fontSize 16），
 * 壳不感知图标体系。hover / focus-visible 依赖 :hover 伪类，落 global.less
 * （.dsh-icon-button，!important 压内联白底——压内联红线见 knowledge
 * dsh-new-session-button 页）。
 * 配色一律取 theme.ts 常量（配色单源红线），dsw alias → 常量映射同
 * DshNewSessionButton 旧 wide 档口径。
 * dashboard-dark-theme 4.2：配色改经 useDshPalette 按档取值——浅档值与改造
 * 前逐字节一致；深档底=bg-layer-1 #232324、描边白 alpha 反相（theme.ts 深档），
 * hover 底随 global.less --fenix-icon-btn-hover 双档变量切换。
 *
 * 仅承载外观：语义（原生 tooltip + aria-label 同源的 title 必填）与点击行为
 * 均由调用方声明；图标按钮无可见文字，无障碍名全靠 title，故必填不带缺省。
 */
import type { CSSProperties, ReactNode } from 'react';
import { useDshPalette } from '@/utils/themeHooks';

export function DshIconButton({
  onClick,
  title,
  children,
}: {
  onClick: () => void;
  /** 原生 tooltip 与 aria-label 同源（图标按钮无可见文字，语义全靠本字段）。 */
  title: string;
  children: ReactNode;
}) {
  const pal = useDshPalette();
  const buttonStyle: CSSProperties = {
    boxSizing: 'border-box',
    width: 38,
    height: 38,
    padding: 0,
    border: `0.5px solid ${pal.borderL3}`,
    borderRadius: 12,
    background: pal.bgElevated,
    color: pal.text,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: 'inherit',
    flex: 'none',
  };
  return (
    <button
      type="button"
      style={buttonStyle}
      onClick={onClick}
      className="dsh-icon-button"
      title={title}
      aria-label={title}
    >
      {children}
    </button>
  );
}
