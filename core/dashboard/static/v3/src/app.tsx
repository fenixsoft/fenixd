import { HistoryOutlined } from '@ant-design/icons';
import type { RunTimeLayoutConfig } from '@umijs/max';
import { Link } from '@umijs/max';
import { ConfigProvider, App as AntdApp, Tag } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import type { ReactNode } from 'react';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import defaultSettings from '../config/defaultSettings';

dayjs.locale('zh-cn');

/**
 * 全局 antd 中文 locale（未启用 umi i18n 插件，直接挂 ConfigProvider）
 */
export function rootContainer(container: ReactNode) {
  return (
    <ConfigProvider locale={zhCN}>
      <AntdApp>{container}</AntdApp>
    </ConfigProvider>
  );
}

// ProLayout 支持的 api https://procomponents.ant.design/components/layout
export const layout: RunTimeLayoutConfig = () => {
  return {
    ...defaultSettings,
    title: 'Fenix Dashboard',
    logo: false,
    menuHeaderRender: undefined,
    menuItemRender: (item, dom) =>
      item.path ? <Link to={item.path}>{dom}</Link> : dom,
    // 顶栏右侧：daemon 心跳指示（SSE 连接即 daemon 在线）
    actionsRender: () => [<SseIndicator key="sse" />],
  };
};

function SseIndicator() {
  return (
    <Tag icon={<HistoryOutlined />} color="default" style={{ marginInlineEnd: 0 }}>
      v3
    </Tag>
  );
}
