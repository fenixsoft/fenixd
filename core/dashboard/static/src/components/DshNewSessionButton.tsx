/**
 * DshNewSessionButton —— dsh web 左侧菜单「新会话」按钮的 dashboard 同款。
 *
 * 2026-11-16 用户需求「两个按钮都改为只显示图标，不显示文字」：旧 wide 展开
 * 档（图标 14px + 「新会话」文字 span，规格见 knowledge dsh-new-session-button
 * 页溯源）退役，形态收窄为 38×38 方形图标钮。壳外观（描边 / 圆角 / 白底 /
 * hover 派生关系与 dsh 窄档同构读法）单点迁 DshIconButton，本组件只保留
 * new-chat-outline 图标 path 数据与语义（title「新会话」）。
 *
 * 图标为 dsh 图标注册表 new-chat-outline（medium 权重 stroke-width 1.3，
 * 16 视窗；旧 wide 档渲染 14px，图标态改渲染 16px 与壳 38×38 比例平衡），
 * path 数据按 dsh 注册表原值内联，避免引入宿主图标运行时。
 *
 * 仅承载外观：点击行为由调用方经 embedBridge.requestHostNewSession 决定
 * （仅 dsh web 嵌入态渲染本按钮，见各页面调用点）。
 */
import { DshIconButton } from '@/components/DshIconButton';

/** dsh new-chat-outline（medium）path 数据，viewBox 0 0 16 16，stroke-width 1.3。 */
const NEW_CHAT_PATHS = [
  // 气泡外轮廓（左下角收笔出尾巴）
  'M2.37091 11.2501C1.58745 9.89288 1.32067 8.29835 1.61969 6.76006C1.91872 5.22177 2.76342 3.8433 3.99826 2.87846C5.2331 1.91362 6.77494 1.42737 8.33988 1.50925C9.90482 1.59113 11.3875 2.23562 12.5149 3.32406C13.6425 4.41269 14.3387 5.87206 14.4754 7.4334C14.612 8.99474 14.18 10.5529 13.2587 11.8209C12.3375 13.0888 10.9891 13.9813 9.46194 14.3337C8.18691 14.628 6.85895 14.5294 5.64989 14.0605C5.1712 13.8748 4.76962 13.4932 4.26534 13.3967C3.67413 13.2835 2.95257 13.5598 2.03794 14.3337',
  // 中央竖笔
  'M8 5V11',
  // 中央横笔
  'M5 8H11',
] as const;

export function DshNewSessionButton({ onClick }: { onClick: () => void }) {
  return (
    <DshIconButton onClick={onClick} title="新会话">
      <svg width={16} height={16} viewBox="0 0 16 16" fill="none" aria-hidden="true" style={{ flex: 'none', display: 'block' }}>
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
    </DshIconButton>
  );
}
