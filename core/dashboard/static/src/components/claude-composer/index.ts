// claude-composer 输入控件集 —— 迁移自 claudecodeui（siteboon/claudecodeui）
// chat-composer 输入链（add-session-composer）。裁剪与适配说明见各文件头注释。
// 桶文件只导出实际被外部消费的导出（claude-msg/index.ts 同款先例）；
// ComposerMenuPrimitives / useComposerMenuAnchor 属 P2 菜单链预留，不在桶内。
// tailwind 产物仍由 prebuild 的 tailwindcss CLI 统一生成到 claude-msg/
// （tailwind.config.js content 已扩入本目录，类名会进同一份 gen.css），此处
// 引该产物即可，不再为 composer 单独生成一份。
import '../claude-msg/tailwind.gen.css';
export { default as SessionComposer } from './SessionComposer';
export type { SessionComposerProps } from './SessionComposer';
