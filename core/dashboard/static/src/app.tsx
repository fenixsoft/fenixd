import { App as AntdApp, Badge, Space, theme } from 'antd';
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
import { getIntl, getLocale, setLocale } from '@umijs/max';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import type { ReactNode } from 'react';
import { Fragment, useEffect, useLayoutEffect, useState } from 'react';
import dayjs from 'dayjs';
import customParseFormat from 'dayjs/plugin/customParseFormat';
import 'dayjs/locale/zh-cn';
import 'dayjs/locale/en';
import logoUrl from './assets/logo-64.png';
import defaultSettings from '../config/defaultSettings';
import { getOverview } from './services/dashboard';
import { useOpsAlertBadge } from './hooks/useOpsAlertBadge';
import { isEmbedMode } from './utils/embedMount';
import { initThemePreference, getCurrentScheme } from './utils/themePreference';
import { startThemeChannel } from './utils/themeChannel';
import { startLocaleChannel } from './utils/localeChannel';
import { useThemeScheme } from './utils/themeHooks';
import {
  initLocalePreference,
  registerLocaleApplier,
  LOCALE_APPLIED_EVENT,
} from './utils/localePreference';
import { PageTitleBarFiltersSlot, PageTitleBarHeaderSlot } from './components/PageTitleBar';
import { dshLayoutTokenFor, dshThemeConfig, DSH_PRIMARY_DARK } from './theme';

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
 * 主题根组件（dashboard-dark-theme 1.4）：订阅 themePreference 状态机的
 * effective scheme，ConfigProvider 按档切换 ThemeConfig（浅档=既有
 * dshAlignedTheme 行为逐字节不变；深档=darkAlgorithm + D2 显式覆写）。启动/
 * 清理对称（layout effect 于首帧 paint 前完成偏好解析：config.ts headScripts
 * 防闪烁脚本先写 data-fenix-theme，本 effect 把 React 档位与文档根对齐）。
 * node/SSR 测试环境（无 window）退回普通 effect（PageTitleBar 同款判定）。
 */
const useIsomorphicLayoutEffect = typeof window !== 'undefined' ? useLayoutEffect : useEffect;

/** antd locale 按生效语言档选择（add-framework-i18n-zh-en 1.1 D1 退化路径
 * 单点：umi locale.antd 联动生成的 ConfigProvider 在应用最外层，本侧
 * ThemeRoot 内层 ConfigProvider 内层覆盖外层——语言联动行为由本动态选择
 * 单点确定，antd 6 兼容性不再依赖 umi 侧实现）。 */
function antdLocaleFor(locale: string) {
  return locale === 'en-US' ? enUS : zhCN;
}

function ThemeRoot({ children }: { children: ReactNode }) {
  const scheme = useThemeScheme();
  // 语言档位订阅（add-framework-i18n-zh-en 修正；2026-11-25 冷启动白屏实证）：
  // rootContainer 位处 umi locale 插件 i18nProvider 外层（renderer 合成序
  // innerProvider→…→rootContainer，插件 provider 恒在内层），本层 useIntl
  // 无 IntlProvider 祖先必抛 [React Intl] Could not find required intl
  // object 且无错误边界时整树卸载。消息面文案由内层 provider 自订阅
  // LANG_CHANGE_EVENT 更新 context 值传播（页面内 useIntl 消费点不依赖
  // 本层），本层只为 antd ConfigProvider locale / dayjs 同步翻档——经
  // localePreference 的 window 事件（LOCALE_APPLIED_EVENT）订阅档位变化。
  const [locale, setLocaleState] = useState<string>(() => getLocale());
  useEffect(() => {
    const onLocaleApplied = () => setLocaleState(getLocale());
    window.addEventListener(LOCALE_APPLIED_EVENT, onLocaleApplied);
    return () => window.removeEventListener(LOCALE_APPLIED_EVENT, onLocaleApplied);
  }, []);
  useIsomorphicLayoutEffect(() => {
    const disposeTheme = initThemePreference();
    const disposeChannel = startThemeChannel();
    const disposeLocaleChannel = startLocaleChannel();
    // 语言偏好 bootstrap（add-framework-i18n-zh-en 1.3）：umi setLocale 应用
    // 接线注册（不刷新页面）→ 读 fenix.locale 偏好按档应用生效语言。防闪烁
    // 脚本已在首帧前写 umi_locale，本调用幂等兜底（umi updater 对等值零动作）。
    registerLocaleApplier((target) => setLocale(target, false));
    initLocalePreference();
    // 首启对齐：initLocalePreference 的应用发生在本 layout effect 内，早于
    // 事件监听（useEffect）挂载——boot 期应用结果此处直接同步，运行期切换
    // 才走 LOCALE_APPLIED_EVENT 事件（防闪烁脚本已提前写 umi_locale 时本
    // 同步为零动作）。
    setLocaleState(getLocale());
    return () => {
      disposeChannel();
      disposeLocaleChannel();
      disposeTheme();
      registerLocaleApplier(null);
    };
  }, []);
  // dayjs locale 随语言档（TimePicker/DatePicker 日期格式与周首日联动；
  // 'en' 为 dayjs 英文 locale 键，与 antd en_US 对应）。
  useEffect(() => {
    dayjs.locale(locale === 'en-US' ? 'en' : 'zh-cn');
  }, [locale]);
  return (
    // 宿主对齐主题（theme.ts 单源）：dsh web 面板桥 iframe 嵌入时与宿主同语言，
    // 独立访问时也保持同一套黑主色 + 深寻蓝链接的视觉；深色档对齐 dsh web
    // 深色调色板（dashboard-dark-theme，theme.ts dshThemeConfig 按档取值）。
    // antd locale 按生效语言动态挂（add-framework-i18n-zh-en 1.1 D1 退化路径，
    // 见 antdLocaleFor 注）。
    <ConfigProvider locale={antdLocaleFor(locale)} theme={dshThemeConfig(scheme, theme.darkAlgorithm)}>
      <AntdApp>
        {/* 档位热切换全量生效键（2026-11-25 用户验收 3「切换会部分改、部分没改，
            刷新才完全改」根因修复）：umi 插件 Layout 的运行时布局配置（本文件
            layout()：navTheme/colorPrimary/token）只在 route/initialState 变化时
            重跑，toggle 翻档不触发其重渲染——ProLayout 内层 ConfigProvider scope
            停在旧档（内容区浅色组件 tokens 未换），而根 ConfigProvider 直接消费
            面已翻档 = 半明半暗混合态。按档 key 重挂 children（含插件 Layout），
            运行时布局配置以新档整跑一遍，语义等价「免刷新的完整重载」：档位
            切换瞬间的页面级状态（滚动位/表单未提交态）随重挂重置，换取全站
            一次到位。浅档启动路径 key='light' 仅静态值，行为不变。 */}
        <Fragment key={scheme}>{children}</Fragment>
      </AntdApp>
    </ConfigProvider>
  );
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
  return <ThemeRoot>{container}</ThemeRoot>;
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

/**
 * 运维菜单名（consolidate-alerts-to-ops-page 4.2）：未处理且可裁决（choices
 * 非空）的告警数以红点数字徽标挂在菜单项上——概览告警横幅退役后全局告警
 * 感知面的唯一入口提示。计数 hook 挂在本独立组件（menuDataRender 是数据
 * 回调不能调 hook，组件形态 = 合法挂载点）；embed=1（dsh 面板桥）时
 * menuRender:false 无菜单 → 本组件不挂载 → hook 不运行（零请求零 SSE 连接）。
 */
function OpsMenuName() {
  const badgeCount = useOpsAlertBadge();
  // 运维菜单名经目录（add-framework-i18n-zh-en 3.1；渲染期 getIntl 取当前档）
  const opsName = getIntl().formatMessage({ id: 'menu.ops' });
  // 徽标必须走行内流（style 内联压掉 .ant-badge-count 的 position:absolute /
  // translate(50%,-50%) 角标定位）：ProLayout 菜单项文本容器
  // ant-pro-base-menu-inline-item-text 为 overflow:hidden（文本省略号裁剪），
  // 角标 sup 悬出文本框顶缘/右缘的部分被裁剪——2026-11-13 用户实测徽标只剩
  // 一条红色小弧、数字不可读。sup 内联化后随文字参与排版，落在文本容器内部
  // 不触裁剪；count=0 时 antd 不渲染 sup，行内形态自然隐匿（零告警隐匿语义不变）。
  return (
    <Badge
      count={badgeCount}
      size="small"
      overflowCount={99}
      style={{
        position: 'static',
        transform: 'none',
        display: 'inline-block',
        marginInlineStart: 5,
        verticalAlign: 'top',
      }}
    >
      {opsName}
    </Badge>
  );
}

// 页题目录键按 pathname 映射（add-framework-i18n-zh-en 3.1：document.title
// 链路与菜单单源同键——pageTitleRender 每次渲染求值，语言切换即时生效；
// 二级详情路径（/projects/<name>[/<spec>]）回落到「项目」页题键）。
function pageTitleKeyForPath(pathname: string): string | null {
  if (pathname.startsWith('/overview')) return 'menu.overview';
  if (pathname.startsWith('/projects')) return 'menu.projects';
  if (pathname.startsWith('/settings')) return 'menu.settings';
  if (pathname.startsWith('/activities') || pathname.startsWith('/chain')) return 'menu.ops';
  if (pathname.startsWith('/command-center')) return 'menu.commandCenter';
  if (pathname.startsWith('/help')) return 'menu.help';
  return null;
}

export const layout: RunTimeLayoutConfig = ({ initialState }) => {
  // 主色族根因层（fix-dashboard-dark-theme-ui-defects 1.1）：ProLayout 外层
  // ConfigProvider 以 settings.colorPrimary 重播种内部 ConfigProvider scope
  // （pro-components ProLayout.js：theme={token:{colorPrimary}}），浅档种子
  // #0f1115 恒定不随档 → 深档下 scope 主色族（页签选中态/墨条/复选框/进度条
  // 等派生消费面）取 muddy 深色阶。深档覆写 colorPrimary=DSH_PRIMARY_DARK
  // （#f9fafb）+ navTheme='realDark'（ProConfigProvider dark 通道）；浅档不增
  // 键、路径与现状逐字节一致。布局 token 通道（theme.ts dshLayoutTokenDark
  // top-level colorPrimary/colorLink）为双保险兜底；保险层组件级显式 token
  // （theme.ts components.Tabs/Progress/Radio/Checkbox）把用户最大感知缺陷与
  // 派生链解耦。热切档窗口：ThemeRoot Fragment 按档重挂只覆盖根 Provider 的
  // 内容树；插件 Layout 的 theme scope（侧栏药丸派生族、.ant-pro-layout-bg-list
  // 背景渐变等）只在整页加载时按档求值（2026-11-25 取证：切档/路由变化后
  // bg-list 渐变仍停留首载档位），该窗口由 global.less 深档 CSS 兜底层
  // （毛玻璃/药丸/bg-list 渐变 !important 压内联，值同源镜像）恒一致。
  const scheme = getCurrentScheme();
  return {
    ...defaultSettings,
    ...(scheme === 'dark'
      ? { navTheme: 'realDark' as const, colorPrimary: DSH_PRIMARY_DARK }
      : {}),
    // ProLayout 布局 token（theme.ts 单源）：PageContainer 内容区左右留白 40px
    // 压缩为 15px（页头标题行同 token 自动对齐）；窄屏 12px 由 global.less 覆盖。
    // 深色档 chrome 染色（顶栏玻璃/侧栏底）双通道：dshLayoutTokenFor 运行时
    // 按档取值（插件 Layout 在 route/initialState 变化重渲染时重跑本配置）+
    // global.less 深档 CSS 覆写层兜底（档位切换不触发本配置重跑的窗口，
    // 值同源镜像恒一致，dashboard-dark-theme 1.4）。
    token: dshLayoutTokenFor(getCurrentScheme()),
    // 左上角标题对齐 v1 brand；headerTitleRender 会整体覆盖 ProLayout 默认「logo+title」组合。
    // 不把节点放进 title——umi 插件会用 title 拼 document.title，节点会变成 "[object Object]"。
    headerTitleRender: () => <HeaderTitle />,
    logo: logoUrl,
    menuItemRender: (item, dom) =>
      item.path ? <Link to={item.path}>{dom}</Link> : dom,
    // 菜单数据：基础四项 + 「项目」下动态二级菜单（各项目名）。菜单名经目录
    // （add-framework-i18n-zh-en 3.1：渲染期 getIntl 取当前档，语言切换即时
    // 生效——@@intl model 更新带动 ProLayout 重渲染）；menu 配置 locale:false
    // 关闭插件内置翻译，name 字符串即所给文本。
    menuDataRender: () => {
      const intl = getIntl();
      return [
        { path: '/overview', name: intl.formatMessage({ id: 'menu.overview' }), icon: <DashboardOutlined /> },
        {
          path: '/projects',
          name: intl.formatMessage({ id: 'menu.projects' }),
          icon: <ProjectOutlined />,
          children: (initialState?.projects || []).map((n) => ({
            path: `/projects/${encodeURIComponent(n)}`,
            name: n,
          })),
        },
        // 菜单名「配置」（2026-11-05 用户指令）：避免与 dsh web 既有「设置」菜单重名
        { path: '/settings', name: intl.formatMessage({ id: 'menu.settings' }), icon: <SettingOutlined /> },
        // 告警徽标挂运维菜单项（consolidate-alerts-to-ops-page 4.2）：name 为
        // 独立组件节点，计数经 useOpsAlertBadge SSE 合帧 + 降级轮询驱动
        { path: '/activities', name: <OpsMenuName />, icon: <HistoryOutlined /> },
        // 管理指挥中心（add-command-center 3.2；2026-11-04 去脱壳改内容区常规页）
        { path: '/command-center', name: intl.formatMessage({ id: 'menu.commandCenter' }), icon: <ControlOutlined /> },
        // 处置链菜单项已并入运维页三页签（2026-11-05 用户指令），路由 /chain 保留重定向
        { path: '/help', name: intl.formatMessage({ id: 'menu.help' }), icon: <QuestionCircleOutlined /> },
      ];
    },
    // document.title 链路（add-framework-i18n-zh-en 3.1）：routes.ts 静态 name
    // 为构建期快照（构建期 Node 环境不可用 umi 运行时 API，改从目录单源取
    // 中文——见 routes.ts 注），运行时页题由本渲染期 pageTitleRender 按当前
    // 语言求值，语言切换即时更新标签页标题。
    pageTitleRender: (props, defaultPageTitle) => {
      const key = pageTitleKeyForPath(props?.location?.pathname ?? '');
      if (!key) return defaultPageTitle;
      return getIntl().formatMessage({ id: key });
    },
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
