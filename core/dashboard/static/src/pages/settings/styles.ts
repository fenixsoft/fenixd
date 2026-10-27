import type { CSSProperties } from 'react';

// 页签底部操作行的统一布局：右对齐，「同步用户级设置」紧邻「保存」左侧。
// 各面板的保存按钮行引用此样式，保持视觉一致。
// 无依赖共享模块（code-review item 6df16f377728）：旧定义在
// SyncFromUserButton.tsx 并被八个面板回导，强化 index → panels → button →
// index 的模块循环。
export const SETTINGS_ACTIONS_ROW_STYLE: CSSProperties = {
  display: 'flex',
  justifyContent: 'flex-end',
  alignItems: 'center',
  gap: 8,
  marginTop: 24,
};
