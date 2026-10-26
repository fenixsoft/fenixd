import { App as AntdApp, Breadcrumb, Space, theme } from 'antd';
import {
  ControlOutlined,
  DashboardOutlined,
  HistoryOutlined,
  ProjectOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import type { RunTimeLayoutConfig } from '@umijs/max';
import { Link, useLocation } from '@umijs/max';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import type { ReactNode } from 'react';
import dayjs from 'dayjs';
import customParseFormat from 'dayjs/plugin/customParseFormat';
import 'dayjs/locale/zh-cn';
import logoUrl from './assets/logo-64.png';
import defaultSettings from '../config/defaultSettings';
import { getOverview } from './services/dashboard';
import { isEmbedMode } from './utils/embedMount';

// 自省/演进面板的 TimePicker 以 dayjs(str, 'HH:mm') 回填配置字符串，
// 该双参解析必须注册 customParseFormat 插件才生效（缺省解析得 Invalid Date，
// TimePicker 空显且保存产出 'Invalid Date' 被后端 400）。统一在此全局注册。
dayjs.extend(customParseFormat);
dayjs.locale('zh-cn');

/**
 * 全局初始数据：拉取项目列表供侧边栏「项目」二级菜单使用
 */
// [fenix-ignore:a16233978ed2] 界面内无创建/接入项目入口（注册经页面外 /fenix-dashboard 完成），且概览页已在加载/30s 心跳时用 setInitialState 校准菜单项目全集，访问概览即同步，无需整页刷新。
export async function getInitialState(): Promise<{ projects: string[] }> {
  try {
    const d = await getOverview();
    return { projects: (d.projects || []).map((p) => p.name) };
  } catch (e) {
    // 降级返回空列表，但记录失败原因，便于区分「确实没有项目」与「接口故障」
    console.warn('Failed to load projects:', e);
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

/**
 * 顶栏右侧全局面包屑：根据 pathname 推导当前位置，
 * 祖先节点可点击、当前节点纯文本（与原各页面 header.extra 面包屑行为一致）。
 * 用独立组件持有 useLocation，避免闭包拿到过期 location。
 */
// 解码 URL 段；非法编码（如裸 '%'）会抛 URIError，回退用原始段值渲染避免整页崩溃。
function safeDecode(seg: string) {
  try {
    return decodeURIComponent(seg);
  } catch {
    return seg;
  }
}

function crumbItems(pathname: string) {
  const seg = pathname.split('/').filter(Boolean).map(safeDecode);
  const home = { title: '概览', href: '#/overview' };
  if (seg[0] === 'projects') {
    if (seg[2]) {
      return [
        home,
        { title: seg[1], href: `#/projects/${encodeURIComponent(seg[1])}` },
        { title: seg[2] },
      ];
    }
    if (seg[1]) return [home, { title: seg[1] }];
    return [home, { title: '项目' }];
  }
  const map: Record<string, string> = {
    overview: '概览',
    settings: '设置',
    activities: '运维',
    help: '帮助',
    'command-center': '指挥中心',
  };
  return [{ title: map[seg[0]] || '概览' }];
}

function HeaderCrumb() {
  const { pathname } = useLocation();
  return <Breadcrumb items={crumbItems(pathname)} style={{ marginInlineEnd: 0 }} className="global-header-crumb" />;
}

// 顶栏标题：logo + Fenix 粗体 + Harness 细体灰字。
// 灰字走 antd token colorTextTertiary（浅色主题默认即 rgba(0,0,0,0.45)），适配未来暗色主题。
// useToken 须在组件内调用，故单独成组件（同 HeaderCrumb 模式）。
function HeaderTitle() {
  const { token } = theme.useToken();
  return (
    <Space size={8} align="center">
      <img src={logoUrl} alt="logo" style={{ width: 22, height: 22, display: 'block' }} />
      <span style={{ fontSize: 16, fontWeight: 700, letterSpacing: 0.3 }}>
        Fenix
        <span style={{ fontWeight: 400, marginLeft: 6, color: token.colorTextTertiary }}>Harness</span>
      </span>
    </Space>
  );
}

// ProLayout 支持的 api https://procomponents.ant.design/components/layout
export const layout: RunTimeLayoutConfig = ({ initialState }) => {
  return {
    ...defaultSettings,
    // 左上角标题对齐 v1 brand；headerTitleRender 会整体覆盖 ProLayout 默认「logo+title」组合。
    // 不把节点放进 title——umi 插件会用 title 拼 document.title，节点会变成 "[object Object]"。
    headerTitleRender: () => <HeaderTitle />,
    logo: logoUrl,
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
      { path: '/activities', name: '运维', icon: <HistoryOutlined /> },
      // 管理指挥中心（add-command-center 3.2）：管理演示大屏入口
      { path: '/command-center', name: '指挥中心', icon: <ControlOutlined /> },
      { path: '/help', name: '帮助', icon: <QuestionCircleOutlined /> },
    ],
    // 「项目」二级菜单默认展开：defaultOpenAll + ignoreFlatMenu 组合下 BaseMenu
    // 会在路由变化时重设为全展开；openKeys:false 使 pathname effect 不覆盖该行为，
    // 用户点击标题仍可临时收起。不能用受控 openKeys（会被 pathname effect 覆盖）。
    openKeys: false,
    menu: { defaultOpenAll: true, ignoreFlatMenu: true },
    // 顶栏右侧：全局面包屑，统一指示当前位置
    actionsRender: () => [<HeaderCrumb key="crumb" />],
    // embed=1（dsh 面板桥 iframe 挂载，add-dashboard-embed-mode 2.1）：隐藏
    // ProLayout 全局侧栏与全局顶栏（D4 标准关闭属性），导航由 dsh 侧栏承担，
    // 页面自身内容头（PageContainer 面包屑/标题）保留。非 embed 分支不增键，
    // 布局配置与现状逐字节一致。
    ...(isEmbedMode() ? { menuRender: false, headerRender: false } : {}),
  };
};
