// ScreenStates.tsx — 指挥中心各屏加载/错误占位（add-command-center 3.3）。
// 文案经 useIntl（code-review 修复轮补迁：错误占位静态中文文案迁 i18n 目录，
// 重试复用既有 common.retry）。
//
// 独立错误降级单点：任一屏加载失败渲染占位 + 重试按钮，不拖垮其他屏与
// 顶栏（specs「导航与默认 Tab」/「独立降级」Requirement）。独立成文件避免
// 与 index.tsx 的组件 import 成环。
// 2026-11-04 白底改版：占位框属布局包裹域（非数据卡），按 11-04 内容区
// 平铺方向去描边/底色，只保留居中排布与副色文案。

import { Button, Spin } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useIntl } from '@umijs/max';
import { TEXT_SUB } from './shared';

const boxStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 12,
  padding: 56,
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
  const intl = useIntl(); // hook 订阅 locale 变更（useIntl 全树订阅纪律）
  return (
    <div style={boxStyle}>
      <span>{intl.formatMessage({ id: 'commandCenter.screen.loadFailed' }, { error })}</span>
      <Button icon={<ReloadOutlined />} onClick={onRetry}>
        {intl.formatMessage({ id: 'common.retry' })}
      </Button>
    </div>
  );
}
