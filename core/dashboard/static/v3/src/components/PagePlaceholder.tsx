import { Card, Empty } from 'antd';
import { PageContainer } from '@ant-design/pro-components';

/**
 * 占位页：菜单已就位、页面按阶段逐一实现
 */
export function PagePlaceholder({ title }: { title: string }) {
  return (
    <PageContainer
      header={{
        title,
      }}
    >
      <Card>
        <Empty description="建设中 — 该页面将在后续阶段实现" />
      </Card>
    </PageContainer>
  );
}
