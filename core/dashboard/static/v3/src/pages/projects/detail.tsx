import { PageContainer } from '@ant-design/pro-components';
import { Alert, Card, Space, Spin, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { history, useParams } from '@umijs/max';
import { getSpecDetail } from '@/services/dashboard';
import type { SpecDetail } from '@/services/dashboard';

export default function SpecDetailPage() {
  const { name = '', spec = '' } = useParams<{ name: string; spec: string }>();
  const [detail, setDetail] = useState<SpecDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!name || !spec) return;

    const load = async () => {
      try {
        setLoading(true);
        const data = await getSpecDetail(name, spec);
        setDetail(data);
        setError('');
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    };

    void load();
  }, [name, spec]);

  if (loading) {
    return (
      <PageContainer
        header={{
          title: spec,
          onBack: () => history.push(`/projects/${name}`),
        }}
      >
        <div style={{ textAlign: 'center', padding: '50px 0' }}>
          <Spin size="large" />
        </div>
      </PageContainer>
    );
  }

  if (error) {
    return (
      <PageContainer
        header={{
          title: spec,
          onBack: () => history.push(`/projects/${name}`),
        }}
      >
        <Alert type="error" showIcon message="加载失败" description={error} />
      </PageContainer>
    );
  }

  return (
    <PageContainer
      header={{
        title: (
          <Space size={8} align="baseline">
            <span>{spec}</span>
            {detail?.status && (
              <Typography.Text type="secondary" style={{ fontSize: 14, fontWeight: 400 }}>
                {detail.status}
              </Typography.Text>
            )}
          </Space>
        ),
        onBack: () => history.push(`/projects/${name}`),
      }}
    >
      {/* 常驻信息区骨架 */}
      <Card title="常驻信息区" style={{ marginBottom: 16 }}>
        <Typography.Paragraph>详情页骨架 - 待实现常驻信息区</Typography.Paragraph>
      </Card>

      {/* 页签骨架 */}
      <Card title="页签区">
        <Typography.Paragraph>详情页骨架 - 待实现四个页签</Typography.Paragraph>
      </Card>
    </PageContainer>
  );
}