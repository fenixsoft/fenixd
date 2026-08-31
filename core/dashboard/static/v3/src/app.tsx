import { App as AntdApp, Tag } from 'antd';
import {
  DashboardOutlined,
  HistoryOutlined,
  ProjectOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import type { RunTimeLayoutConfig } from '@umijs/max';
import { Link } from '@umijs/max';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import type { ReactNode } from 'react';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import defaultSettings from '../config/defaultSettings';
import { getOverview } from './services/dashboard';

dayjs.locale('zh-cn');

/**
 * 全局初始数据：拉取项目列表供侧边栏「项目」二级菜单使用
 */
export async function getInitialState(): Promise<{ projects: string[] }> {
  try {
    const d = await getOverview();
    return { projects: (d.projects || []).map((p) => p.name) };
  } catch {
    return { projects: [] };
  }
}

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
export const layout: RunTimeLayoutConfig = ({ initialState }) => {
  return {
    ...defaultSettings,
    title: 'Fenix Dashboard',
    logo: false,
    menuHeaderRender: undefined,
    menuItemRender: (item, dom) =>
      item.path ? <Link to={item.path}>{dom}</Link> : dom,
    // 菜单数据：基础四项 + 「项目」下动态二级菜单（各项目名）
    menuDataRender: () => [
      { path: '/overview', name: '概览', icon: <DashboardOutlined /> },
      {
        path: '/projects',
        name: '项目',
        icon: <ProjectOutlined />,
        children: (initialState?.projects || []).map((n) => ({
          path: `/projects/${encodeURIComponent(n)}`,
          name: n,
        })),
      },
      { path: '/settings', name: '设置', icon: <SettingOutlined /> },
      { path: '/activities', name: '运维记录', icon: <HistoryOutlined /> },
    ],
    // 「项目」二级菜单默认展开：defaultOpenAll + ignoreFlatMenu 组合下 BaseMenu
    // 会在路由变化时重设为全展开；openKeys:false 使 pathname effect 不覆盖该行为，
    // 用户点击标题仍可临时收起。不能用受控 openKeys（会被 pathname effect 覆盖）。
    openKeys: false,
    menu: { defaultOpenAll: true, ignoreFlatMenu: true },
    // 顶栏右侧：v3 标识
    actionsRender: () => [
      <Tag key="v3" color="default" style={{ marginInlineEnd: 0 }}>
        v3
      </Tag>,
    ],
  };
};
