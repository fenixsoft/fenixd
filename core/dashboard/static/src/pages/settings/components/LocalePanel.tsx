// LocalePanel.tsx — 配置页「界面语言」面板（add-framework-i18n-zh-en 2.1 /
// dashboard-i18n「手动切换与持久化」Requirement）。
//
// 语言偏好三档单选（跟随系统/中文/English，缺省跟随系统）：选择后立即全站
// 生效并写入浏览器 localStorage（键 fenix.locale，utils/localePreference
// 单点；umi setLocale(target, false) 应用，不刷新页面）；该项不参与
// PUT /api/config 保存路径（无表单无保存按钮，ThemePanel 同款口径）。
//
// 形态与色值对齐 ThemePanel（theme.ts 单源，零新硬编码色）：面板自身只用
// antd 语义 token；需要显式色的场景从 theme.ts 单源取（useDshPalette）。
//
// 嵌入态不锁定（design Non-Goals：embed 态语言不跟随宿主 dsh web——与主题
// 不同，不扩 embed 契约；嵌入下行为与 standalone 一致）。
//
// 命名纪律（settings-page 能力页）：页面整体叫「配置」、控件名「界面语言」，
// 不触「设置」避让词汇面。面板文案经 useIntl（本面板即双语切换的自样例）。
import { Card, Radio, Space, Typography } from 'antd';
import { useIntl } from '@umijs/max';
import {
  getCurrentPreference,
  setLocalePreference,
  type LocalePreference,
} from '@/utils/localePreference';

const { Text } = Typography;

/** 三档选项（键=偏好值；文案与 dashboard-i18n「手动切换与持久化」三档命名
 * 一致：跟随系统 / 中文 / English）。 */
const LOCALE_OPTIONS: { value: LocalePreference; id: string; hintId: string }[] = [
  { value: 'system', id: 'settings.locale.option.system', hintId: 'settings.locale.option.systemHint' },
  { value: 'zh-CN', id: 'settings.locale.option.zh', hintId: 'settings.locale.option.zhHint' },
  { value: 'en-US', id: 'settings.locale.option.en', hintId: 'settings.locale.option.enHint' },
];

export default function LocalePanel() {
  const intl = useIntl();
  // 当前偏好渲染期读取（模块态单一事实源 localePreference.getCurrentPreference；
  // 不直读 localStorage——隐私模式等 setItem 抛错场景下模块态已切新档而存储
  // 仍是旧值，直读会让控件选中档跳回旧档、与实际生效语言脱节）
  const preference = getCurrentPreference();

  return (
    <div>
      <h3>{intl.formatMessage({ id: 'settings.locale.title' })}</h3>
      <Text type="secondary">{intl.formatMessage({ id: 'settings.locale.desc' })}</Text>
      <Card style={{ marginTop: 12 }}>
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          <Radio.Group
            value={preference}
            onChange={(e) => setLocalePreference(e.target.value as LocalePreference)}
            options={LOCALE_OPTIONS.map((o) => ({
              value: o.value,
              label: intl.formatMessage({ id: o.id }),
            }))}
          />
          {LOCALE_OPTIONS.filter((o) => o.value === preference).map((o) => (
            <Text key={o.value} type="secondary">
              {intl.formatMessage({ id: o.hintId })}
            </Text>
          ))}
        </Space>
      </Card>
    </div>
  );
}
