import { App as AntdApp, Space, theme } from 'antd';
import {
  ControlOutlined,
  DashboardOutlined,
  HistoryOutlined,
  ProjectOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import type { RunTimeLayoutConfig } from '@umijs/max';
import { Link } from '@umijs/max';
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
import { PageTitleBarFiltersSlot, PageTitleBarHeaderSlot } from './components/PageTitleBar';
import { dshAlignedTheme, dshLayoutToken } from './theme';

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
  // 文档级 embed 标记（unified-page-title-bar 行壳位 sticky 前置，2026-11-05）：
  // isEmbedMode() 是 JS 常量，CSS 侧无法经 :has() 探测查询参数——落
  // <html data-embed-mode> 供样式作用域取用（global.less overview 呼吸带豁免）。
  // embed 档滚动口顶须让给 sticky 标题栏：上游任何顶垫都会变成起滚位移。
  if (typeof document !== 'undefined' && isEmbedMode()) {
    document.documentElement.setAttribute('data-embed-mode', '1');
  }
  return (
    // 宿主对齐主题（theme.ts 单源）：dsh web 面板桥 iframe 嵌入时与宿主同语言，
    // 独立访问时也保持同一套黑主色 + 深寻蓝链接的视觉。
    <ConfigProvider locale={zhCN} theme={dshAlignedTheme}>
      <AntdApp>{container}</AntdApp>
    </ConfigProvider>
  );
}

/**
 * 顶栏右侧全局面包屑已随 unified-page-title-bar 全局退役（用户裁决：位置信息
 * 由顶栏页面标题表达，避免右上角拥挤）——HeaderCrumb 组件、crumbItems 映射与
 * global-header-crumb 样式锚点一并移除；actionsRender 槽位改由统一标题栏控件
 * 的过滤项插槽接管（无过滤项页右上角为空）。
 */

// 顶栏标题：logo + 自绘 SVG lockup（2026-11-07 用户指令：与 dsh web 侧栏品牌
// 同步）。主行 FENIX HARNESS：Montserrat 600/12.5px/字距 1px 大写（dsh 官方
// boot 屏 wordmark 语言），HARNESS 500 权重次级灰弱化；副标 THE AI-NATIVE
// SDLC（2026-11-10 用户指令：原 WEB DASHBOARD 改文）：
// Montserrat 500/9px/字距 2.2px，基线 y=30.5（与主行视觉空隙 ≈7.2px）。两行
// textLength 锁同宽 117.3px（lengthAdjust=spacing 均分字隙，字体回退仍等宽）。
// 颜色走 antd token（theme.ts 单源零新色：colorText/colorTextSecondary/
// colorTextTertiary=#0f1115/#61666b/#81858c，与 dsh web 别名值逐字相同）。
// Montserrat @font-face 见 global.less（woff2 取自 dsh-web-frontend 发行资产）。
// 几何与 dsh web 插件 fenix-dsh-brand-fenix 的 FenixName 逐参数一致（viewBox
// 0 0 124 38），两侧品牌像素级同源；差异仅 icon 尺寸沿用本侧 22px 惯例。
// useToken 须在组件内调用，故单独成组件（同 HeaderCrumb 模式）。
function HeaderTitle() {
  const { token } = theme.useToken();
  return (
    <Space size={10} align="center">
      <img src={logoUrl} alt="logo" style={{ width: 22, height: 22, display: 'block' }} />
      <svg
        width={124}
        height={38}
        viewBox="0 0 124 38"
        role="img"
        aria-label="Fenix Harness — The AI-Native SDLC"
        style={{ display: 'block', overflow: 'visible' }}
      >
        <text
          x={0}
          y={17}
          textLength={117.3}
          lengthAdjust="spacing"
          fontFamily="Montserrat, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
          fontSize="12.5px"
          fontWeight={600}
          letterSpacing="1px"
          fill={token.colorText}
        >
          FENIX{' '}
          <tspan fontWeight={500} fill={token.colorTextSecondary}>
            HARNESS
          </tspan>
        </text>
        <text
          x={0}
          y={30.5}
          textLength={117.3}
          lengthAdjust="spacing"
          fontFamily="Montserrat, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
          fontSize="9px"
          fontWeight={500}
          letterSpacing="2.2px"
          fill={token.colorTextTertiary}
        >
          THE AI-NATIVE SDLC
        </text>
      </svg>
    </Space>
  );
}

// ProLayout 支持的 api https://procomponents.ant.design/components/layout
export const layout: RunTimeLayoutConfig = ({ initialState }) => {
  return {
    ...defaultSettings,
    // ProLayout 布局 token（theme.ts 单源）：PageContainer 内容区左右留白 40px
    // 压缩为 15px（页头标题行同 token 自动对齐）；窄屏 12px 由 global.less 覆盖。
    token: dshLayoutToken,
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
      // 菜单名「配置」（2026-11-05 用户指令）：避免与 dsh web 既有「设置」菜单重名
      { path: '/settings', name: '配置', icon: <SettingOutlined /> },
      { path: '/activities', name: '运维', icon: <HistoryOutlined /> },
      // 管理指挥中心（add-command-center 3.2；2026-11-04 去脱壳改内容区常规页）
      { path: '/command-center', name: '指挥中心', icon: <ControlOutlined /> },
      // 处置链菜单项已并入运维页三页签（2026-11-05 用户指令），路由 /chain 保留重定向
      { path: '/help', name: '帮助', icon: <QuestionCircleOutlined /> },
    ],
    // 「项目」二级菜单默认展开：defaultOpenAll + ignoreFlatMenu 组合下 BaseMenu
    // 会在路由变化时重设为全展开；openKeys:false 使 pathname effect 不覆盖该行为，
    // 用户点击标题仍可临时收起。不能用受控 openKeys（会被 pathname effect 覆盖）。
    openKeys: false,
    menu: { defaultOpenAll: true, ignoreFlatMenu: true },
    // 品牌区之后的标题区（unified-page-title-bar 1.2）：各页经 PageTitleBar 声明
    // 的 back+title+subtitle 由注册单源桥接到本插槽渲染；无注册（豁免页/切换
    // 瞬间）渲染空。插槽是组件形态——useSyncExternalStore 须在组件内调用
    // （同 HeaderTitle 的 useToken 模式）。
    headerContentRender: () => <PageTitleBarHeaderSlot />,
    // 顶栏右侧：该页过滤项（原全局面包屑槽位；unified-page-title-bar D3 面包屑
    // 退役）。无过滤项页右上角为空。
    actionsRender: () => [<PageTitleBarFiltersSlot key="filters" />],
    // embed=1（dsh 面板桥 iframe 挂载，add-dashboard-embed-mode 2.1）：隐藏
    // ProLayout 全局侧栏与全局顶栏（D4 标准关闭属性），导航由 dsh 侧栏承担。
    // 页面标识由统一标题栏控件承担（unified-page-title-bar：PageContainer 页头
    // 全站摘除、面包屑退役后，控件在 embed/移动端自动落内容区首行 48px 行壳位）。
    // 非 embed 分支不增键，布局配置与现状逐字节一致。
    ...(isEmbedMode() ? { menuRender: false, headerRender: false } : {}),
  };
};
