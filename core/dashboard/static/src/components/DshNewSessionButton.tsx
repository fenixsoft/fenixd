/**
 * DshNewSessionButton —— dsh web 左侧菜单「新会话」按钮的 dashboard 同款
 * （2026-11-12 用户需求：SPEC 列表页 / 详情页右上角按钮样式、图标与 dsh web
 * 左侧菜单保持一致）。
 *
 * 样式逐项取证自 @deepseek-ai/dsh-client-ui-sidebar 的 newSession 类
 * （wide 展开态，带文字形态）与其内容 span newSessionContent：
 * 38px 高、0.5px alias-border-l3 描边、radius-md 12px 圆角、alias-button-
 * elevated-fill 白底、alias-label-primary 前景、padding 8px 12px、14px/500/
 * 22px 字排、flex 居中、内容 gap 6px，hover 换 alias-button-floating-hover。
 * hover / focus-visible 依赖 :hover 伪类，落 global.less（.dsh-new-session-button）。
 * 图标为 dsh 图标注册表 new-chat-outline（medium 权重 stroke-width 1.3，
 * 16 视窗渲染 14px），此处按同一 path 数据内联，避免引入宿主图标运行时。
 * 颜色一律取 theme.ts 常量（配色单源红线），dsw alias → 常量映射见各值注释。
 *
 * 仅承载外观：点击行为由调用方经 embedBridge.requestHostNewSession 决定
 * （仅 dsh web 嵌入态渲染本按钮，见各页面调用点）。
 */
import type { CSSProperties } from 'react';
import {
  DSH_BG_ELEVATED,
  DSH_BORDER_L3,
  DSH_TEXT,
} from '@/theme';

/** dsh new-chat-outline（medium）path 数据，viewBox 0 0 16 16，stroke-width 1.3。 */
const NEW_CHAT_PATHS = [
  // 气泡外轮廓（左下角收笔出尾巴）
  'M2.37091 11.2501C1.58745 9.89288 1.32067 8.29835 1.61969 6.76006C1.91872 5.22177 2.76342 3.8433 3.99826 2.87846C5.2331 1.91362 6.77494 1.42737 8.33988 1.50925C9.90482 1.59113 11.3875 2.23562 12.5149 3.32406C13.6425 4.41269 14.3387 5.87206 14.4754 7.4334C14.612 8.99474 14.18 10.5529 13.2587 11.8209C12.3375 13.0888 10.9891 13.9813 9.46194 14.3337C8.18691 14.628 6.85895 14.5294 5.64989 14.0605C5.1712 13.8748 4.76962 13.4932 4.26534 13.3967C3.67413 13.2835 2.95257 13.5598 2.03794 14.3337',
  // 中央竖笔
  'M8 5V11',
  // 中央横笔
  'M5 8H11',
] as const;

const buttonStyle: CSSProperties = {
  boxSizing: 'border-box',
  height: 38,
  padding: '8px 12px',
  border: `0.5px solid ${DSH_BORDER_L3}`,
  borderRadius: 12,
  background: DSH_BG_ELEVATED,
  color: DSH_TEXT,
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 6,
  fontSize: 14,
  fontWeight: 500,
  lineHeight: '22px',
  whiteSpace: 'nowrap',
  fontFamily: 'inherit',
  flex: 'none',
};

export function DshNewSessionButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" style={buttonStyle} onClick={onClick} className="dsh-new-session-button">
      <svg width={14} height={14} viewBox="0 0 16 16" fill="none" aria-hidden="true" style={{ flex: 'none', display: 'block' }}>
        {NEW_CHAT_PATHS.map((d) => (
          <path
            key={d.slice(0, 16)}
            d={d}
            stroke="currentColor"
            strokeWidth={1.3}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
      </svg>
      <span>新会话</span>
    </button>
  );
}
