import { PageContainer } from '@ant-design/pro-components';
import { Alert, Card, Descriptions, Space, Spin, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { history, useParams } from '@umijs/max';
import dayjs from 'dayjs';
import { getSpecDetail, statusMeta } from '@/services/dashboard';
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

  const statusInfo = statusMeta(detail?.status || '');

  return (
    <PageContainer
      header={{
        title: (
          <Space size={8} align="baseline">
            <span>{spec}</span>
            {detail?.status && (
              <Tag color={statusInfo.tone === 'good' ? 'success' : statusInfo.tone === 'critical' ? 'error' : 'processing'}>
                {statusInfo.label}
              </Tag>
            )}
          </Space>
        ),
        onBack: () => history.push(`/projects/${name}`),
      }}
    >
      {/* Error 横幅 */}
      {detail?.error && (
        <Alert
          type="error"
          showIcon
          message="错误信息"
          description={detail.error}
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 元信息区 */}
      <Card style={{ marginBottom: 16 }}>
        <Descriptions column={4} size="small">
          <Descriptions.Item label="优先级">
            <span>P{detail?.priority ?? '?'}</span>
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {detail?.created ? dayjs(detail.created).format('YYYY-MM-DD HH:mm:ss') : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="更新时间">
            {detail?.updated ? dayjs(detail.updated).format('YYYY-MM-DD HH:mm:ss') : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="依赖">
            {detail?.status || '—'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

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