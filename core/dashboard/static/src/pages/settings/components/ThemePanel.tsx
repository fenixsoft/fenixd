// ThemePanel.tsx — 配置页「界面风格」面板（dashboard-dark-theme 3.1 /
// v3-settings-page「界面风格子项」Requirement）。
//
// 主题偏好三档单选（跟随系统/浅色/深色，缺省跟随系统）：选择后立即全站生效
// 并写入浏览器 localStorage（键 fenix.theme，utils/themePreference 单点）；
// 该项不参与 PUT /api/config 保存路径（无表单无保存按钮）。系统档跟随
// prefers-color-scheme 并实时切换（themePreference.matchMedia 监听驱动重渲染）。
//
// 嵌入态（embed=1）渲染锁定态：三档控件置灰不可改 + 「跟随 dsh web」说明
// 文案——主题由宿主控制（URL theme 参数 / postMessage 实时广播），嵌入态
// 不读写 localStorage（宿主优先且不污染独立偏好）。锁定态仍实时显示宿主
// 跟随档（useThemeScheme 订阅，宿主切换时控件档位随之翻转）。
//
// 命名纪律（settings-page 能力页）：页面整体叫「配置」、控件名「界面风格」，
// 不触「设置」避让词汇面。配色零新值：面板自身只用 antd 语义 token
// （darkAlgorithm 随档自适应）；需要显式色的场景从 theme.ts 单源取
// （useDshPalette）。
// 文案经 useIntl（i18n 修复轮 batch-S：本文件静态中文文案迁 i18n 目录）
import { useIntl } from '@umijs/max';
import { Card, Radio, Space, Typography } from 'antd';
import { isEmbedMode } from '@/utils/embedMount';
import { useThemeScheme } from '@/utils/themeHooks';
import {
  getCurrentPreference,
  setThemePreference,
  type ThemePreference,
} from '@/utils/themePreference';
import { useDshPalette } from '@/utils/themeHooks';

const { Text } = Typography;

/** 三档选项（键=偏好值；label/hint 为消息 id，文案与 v3-settings-page spec 三档命名逐字一致）。 */
const THEME_OPTIONS: { value: ThemePreference; label: string; hint: string }[] = [
  { value: 'system', label: 'settings.theme.mode.system', hint: 'settings.theme.hint.system' },
  { value: 'light', label: 'settings.theme.mode.light', hint: 'settings.theme.hint.light' },
  { value: 'dark', label: 'settings.theme.mode.dark', hint: 'settings.theme.hint.dark' },
];

export default function ThemePanel() {
  const intl = useIntl();
  const scheme = useThemeScheme();
  const pal = useDshPalette();
  const embed = isEmbedMode();
  // 当前偏好渲染期读取（模块态单一事实源 themePreference.getCurrentPreference；
  // 不直读 localStorage——隐私模式等 setItem 抛错场景下模块态已切新档而存储
  // 仍是旧值，直读会让控件选中档跳回旧档、与实际生效配色脱节；嵌入态宿主档
  // 生效时模块态恒 system 语义占位——锁定态不依赖该值）
  const preference = getCurrentPreference();
  // 控件显示档：嵌入态显示宿主跟随档（实时翻转），独立态显示偏好档
  const displayValue: ThemePreference = embed ? scheme : preference;

  return (
    <div>
      <h3>{intl.formatMessage({ id: 'settings.theme.title' })}</h3>
      <Text type="secondary">
        {intl.formatMessage({ id: 'settings.theme.desc' })}
      </Text>
      <Card style={{ marginTop: 12 }}>
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          <Radio.Group
            value={displayValue}
            disabled={embed}
            onChange={(e) => setThemePreference(e.target.value as ThemePreference)}
            options={THEME_OPTIONS.map((o) => ({
              value: o.value,
              label: intl.formatMessage({ id: o.label }),
            }))}
          />
          {embed ? (
            // 嵌入态锁定说明（v3-settings-page「嵌入态锁定」Scenario：控件旁
            // 展示「跟随 dsh web」文案；档位随宿主 postMessage 实时翻转）
            <Text type="secondary" style={{ color: pal.textTertiary }}>
              {intl.formatMessage(
                { id: 'settings.theme.embedLock' },
                {
                  mode: intl.formatMessage({
                    id: scheme === 'dark' ? 'settings.theme.mode.dark' : 'settings.theme.mode.light',
                  }),
                },
              )}
            </Text>
          ) : (
            THEME_OPTIONS.filter((o) => o.value === displayValue).map((o) => (
              <Text key={o.value} type="secondary">
                {intl.formatMessage({ id: o.hint })}
              </Text>
            ))
          )}
        </Space>
      </Card>
    </div>
  );
}
