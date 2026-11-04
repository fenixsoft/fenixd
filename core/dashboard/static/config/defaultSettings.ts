import type { ProLayoutProps } from '@ant-design/pro-components';

const Settings: ProLayoutProps = {
  navTheme: 'light',
  // 宿主对齐（theme.ts DSH_PRIMARY 同值）：dsh web 黑系主色，ProLayout 侧
  // 选中态/主色与 ConfigProvider token 保持一致（DESIGN.md「宿主对齐基线」）。
  colorPrimary: '#0f1115',
  // mix：上部标题栏 + 左侧菜单 + 右侧内容区
  layout: 'mix',
  contentWidth: 'Fluid',
  fixedHeader: true,
  fixSiderbar: true,
  title: 'Fenix Dashboard',
};

export default Settings;
