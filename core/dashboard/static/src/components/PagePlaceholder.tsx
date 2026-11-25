import { Card, Empty } from 'antd';
import { PageContainer } from '@ant-design/pro-components';
import { useIntl } from '@umijs/max';

/**
 * 占位页：菜单已就位、页面按阶段逐一实现
 */
export function PagePlaceholder({ title }: { title: string }) {
  // 建设中文案经 useIntl 渲染期取值（add-framework-i18n-zh-en 3.5）
  const intl = useIntl();
  return (
    <PageContainer
      header={{
        title,
      }}
    >
      <Card>
        <Empty
          description={intl.formatMessage({ id: 'components.pagePlaceholder.underConstruction' })}
        />
      </Card>
    </PageContainer>
  );
}
