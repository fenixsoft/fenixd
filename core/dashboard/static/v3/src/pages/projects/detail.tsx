import { PageContainer } from '@ant-design/pro-components';
import { Alert, Card, Checkbox, Col, Descriptions, Progress, Row, Space, Spin, Statistic, Tag, Typography } from 'antd';
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

  // 格式化 token 数量
  const fmtMillions = (tokens: number) => {
    const m = (tokens || 0) / 1e6;
    return m >= 1000 ? (m / 1000).toFixed(2) + 'G' : m.toFixed(1) + 'M';
  };

  // 计算任务进度
  const taskGroups = detail?.tasks?.groups || [];
  const allTasks = taskGroups.flatMap((g) => g.tasks || []);
  const completedTasks = allTasks.filter((t) => t.done).length;
  const totalTasks = allTasks.length;

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

      {/* 常驻信息区 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {/* 验证结论 */}
        <Col span={12}>
          <Card title="验证结论" size="small">
            {detail?.verdict ? (
              <div>
                <Space size={8} style={{ marginBottom: 8 }}>
                  <Tag color={detail.verdict.passed ? 'success' : 'error'}>
                    {detail.verdict.passed ? '✅ 通过' : '❌ 未通过'}
                  </Tag>
                  {detail.verdict.summary && (
                    <Typography.Text type="secondary">
                      {detail.verdict.summary}
                    </Typography.Text>
                  )}
                </Space>
                {detail.verdict.details && (
                  <Typography.Paragraph style={{ marginBottom: 0 }}>
                    {detail.verdict.details}
                  </Typography.Paragraph>
                )}
              </div>
            ) : (
              <Typography.Text type="secondary">暂无验证结论</Typography.Text>
            )}
          </Card>
        </Col>

        {/* 验证进度 */}
        <Col span={12}>
          <Card title="验证进度" size="small">
            {detail?.verify ? (
              <div>
                <Progress
                  percent={detail.verify.total > 0 ? Math.round((detail.verify.done / detail.verify.total) * 100) : 0}
                  size="small"
                  style={{ marginBottom: 8 }}
                />
                <Typography.Text type="secondary">
                  {detail.verify.done}/{detail.verify.total}
                </Typography.Text>
                {detail.verify.error && (
                  <Alert type="error" message={detail.verify.error} style={{ marginTop: 8 }} />
                )}
              </div>
            ) : (
              <Typography.Text type="secondary">暂无验证进度</Typography.Text>
            )}
          </Card>
        </Col>

        {/* Token 用量 */}
        <Col span={12}>
          <Card title="Token 消耗（累计）" size="small">
            {detail?.token_usage ? (
              <div>
                <Row gutter={16}>
                  <Col span={12}>
                    <Statistic
                      title="输入"
                      value={fmtMillions(detail.token_usage.tokens_in)}
                      valueStyle={{ fontSize: 16 }}
                    />
                  </Col>
                  <Col span={12}>
                    <Statistic
                      title="输出"
                      value={fmtMillions(detail.token_usage.tokens_out)}
                      valueStyle={{ fontSize: 16 }}
                    />
                  </Col>
                </Row>
                <div style={{ marginTop: 8 }}>
                  <Typography.Text type="secondary">
                    {detail.token_usage.cost_available
                      ? `成本 $${Number(detail.token_usage.cost).toFixed(2)}`
                      : '成本不可用（网关未回传）'}
                  </Typography.Text>
                </div>
              </div>
            ) : (
              <Typography.Text type="secondary">暂无 Token 用量</Typography.Text>
            )}
          </Card>
        </Col>

        {/* 任务清单 */}
        <Col span={12}>
          <Card title={`任务清单 (${completedTasks}/${totalTasks})`} size="small">
            {taskGroups.length > 0 ? (
              <div>
                <Progress
                  percent={totalTasks > 0 ? Math.round((completedTasks / totalTasks) * 100) : 0}
                  size="small"
                  style={{ marginBottom: 12 }}
                />
                {taskGroups.map((group, idx) => (
                  <div key={idx} style={{ marginBottom: 12 }}>
                    <Typography.Text strong style={{ display: 'block', marginBottom: 4 }}>
                      {group.name} ({group.tasks.filter((t) => t.done).length}/{group.tasks.length})
                    </Typography.Text>
                    {group.tasks.map((task, taskIdx) => (
                      <div key={taskIdx} style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 4 }}>
                        <Checkbox checked={task.done} disabled style={{ marginRight: 8 }} />
                        <Typography.Text
                          style={{
                            textDecoration: task.done ? 'line-through' : 'none',
                            color: task.done ? '#999' : 'inherit',
                          }}
                        >
                          {task.description}
                        </Typography.Text>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            ) : (
              <Typography.Text type="secondary">暂无任务清单</Typography.Text>
            )}
          </Card>
        </Col>
      </Row>

      {/* 页签骨架 */}
      <Card title="页签区">
        <Typography.Paragraph>详情页骨架 - 待实现四个页签</Typography.Paragraph>
      </Card>
    </PageContainer>
  );
}