// ScreenStates.tsx — 指挥中心各屏加载/错误占位（add-command-center 3.3）。
//
// 独立错误降级单点：任一屏加载失败渲染占位 + 重试按钮，不拖垮其他屏与
// 顶栏（specs「导航与默认 Tab」/「独立降级」Requirement）。独立成文件避免
// 与 index.tsx 的组件 import 成环。

import { Button, Spin } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { BG, PANEL_BORDER, TEXT_SUB } from './shared';

const boxStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 12,
  padding: 56,
  border: `1px solid ${PANEL_BORDER}`,
  borderRadius: 8,
  color: TEXT_SUB,
};

/** 首屏加载占位。 */
export function ScreenLoading({ hint }: { hint?: string }) {
  return (
    <div style={boxStyle}>
      <Spin size="large" />
      {hint ? <span style={{ fontSize: 12 }}>{hint}</span> : null}
    </div>
  );
}

/** 加载失败占位：错误原因 + 重试按钮（独立降级，不拖垮其他屏）。 */
export function ScreenErrorPlaceholder({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <div style={{ ...boxStyle, background: BG }}>
      <span>数据加载失败：{error}</span>
      <Button icon={<ReloadOutlined />} onClick={onRetry}>
        重试
      </Button>
    </div>
  );
}
