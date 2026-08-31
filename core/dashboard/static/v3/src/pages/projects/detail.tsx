import { PageContainer } from '@ant-design/pro-components';
import { Alert, Card, Checkbox, Col, Collapse, Descriptions, Empty, Progress, Row, Space, Spin, Statistic, Tabs, Tag, Timeline, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { history, useParams } from '@umijs/max';
import dayjs from 'dayjs';
import { getSpecDetail, statusMeta } from '@/services/dashboard';
import type { SpecDetail } from '@/services/dashboard';
import RunStream from './components/RunStream';

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

  // 格式化时长
  const fmtDuration = (seconds: number) => {
    if (seconds == null || Number.isNaN(seconds)) return '';
    let s = Math.max(0, Math.round(seconds));
    if (s < 60) return `${s}秒`;
    const m = Math.floor(s / 60);
    s %= 60;
    if (m < 60) return s ? `${m}分${s}秒` : `${m}分`;
    return `${Math.floor(m / 60)}时${m % 60}分${s ? `${s}秒` : ''}`;
  };

  // 渲染时间轴内容
  const renderTimeline = () => {
    const timeline = detail?.timeline || [];
    if (!timeline.length) {
      return <Empty description="暂无运行时间轴" />;
    }

    return (
      <Timeline
        items={timeline.map((item, index) => {
          if (item.kind === 'state') {
            // 状态节点
            const isRollback = !!item.reason;
            return {
              color: isRollback ? '#ec835a' : '#3987e5',
              dot: (
                <span style={{ fontSize: 16 }}>
                  {isRollback ? '↩' : '·'}
                </span>
              ),
              children: (
                <div>
                  <Typography.Text strong>
                    {item.state || '状态迁移'}
                  </Typography.Text>
                  {isRollback && (
                    <div style={{ marginTop: 4 }}>
                      <Typography.Text type="warning">
                        ↩ {item.reason || '状态回退'}
                      </Typography.Text>
                    </div>
                  )}
                  <div style={{ marginTop: 4 }}>
                    <Typography.Text type="secondary">
                      {dayjs(item.time).format('YYYY-MM-DD HH:mm:ss')}
                    </Typography.Text>
                  </div>
                </div>
              ),
            };
          } else {
            // 运行节点
            const st = item.status || '';
            const color = st === 'error' ? '#d03b3b' : (st === 'running' || st === 'empty') ? '#fab219' : '#199e70';
            const iconChar = st === 'error' ? '✕' : (st === 'running' || st === 'empty') ? '…' : '✓';
            const dur = item.duration_seconds != null ? fmtDuration(item.duration_seconds) : '';
            const isFix = item.spec && String(item.spec).startsWith('fix-');

            return {
              color: color,
              dot: (
                <span style={{ fontSize: 16 }}>
                  {iconChar}
                </span>
              ),
              children: (
                <div>
                  <Space size={8} style={{ marginBottom: 4 }}>
                    <Typography.Text strong>{item.agent || '未知类型'}</Typography.Text>
                    <Tag color={color} style={{ margin: 0 }}>
                      {st || '未知状态'}
                    </Tag>
                    {isFix && (
                      <Tag color="orange" style={{ margin: 0 }}>
                        🔧 {item.spec}
                      </Tag>
                    )}
                  </Space>
                  {dur && (
                    <div style={{ marginTop: 4 }}>
                      <Typography.Text type="secondary">
                        耗时：{dur}
                      </Typography.Text>
                    </div>
                  )}
                  <div style={{ marginTop: 4 }}>
                    <Typography.Text type="secondary">
                      {dayjs(item.time).format('YYYY-MM-DD HH:mm:ss')}
                    </Typography.Text>
                  </div>
                  {item.run_id && (
                    <div style={{ marginTop: 8 }}>
                      <Collapse
                        ghost
                        size="small"
                        items={[
                          {
                            key: 'run-stream',
                            label: '查看运行记录',
                            children: <RunStream runId={item.run_id!} project={name} />,
                          },
                        ]}
                      />
                    </div>
                  )}
                </div>
              ),
            };
          }
        })}
      />
    );
  };

  // 页签配置
  const tabItems = [
    {
      key: 'timeline',
      label: '运行时间轴',
      children: (
        <div style={{ padding: '20px 0' }}>
          {renderTimeline()}
        </div>
      ),
    },
    {
      key: 'scenarios',
      label: '场景结果',
      children: (
        <div style={{ padding: '20px 0' }}>
          {detail?.scenarios?.report_status === 'corrupted' ? (
            <Empty description="report.json 损坏或不可读" />
          ) : detail?.scenarios?.items && detail.scenarios.items.length > 0 ? (
            <div>
              {/* 汇总计数 */}
              {detail.scenarios.summary && (
                <div style={{ marginBottom: 16 }}>
                  <Space size={8}>
                    <Tag color="success">通过 {detail.scenarios.summary.passed}</Tag>
                    <Tag color="warning">警告 {detail.scenarios.summary.warning}</Tag>
                    <Tag color="error">失败 {detail.scenarios.summary.failed}</Tag>
                    <Tag color="error">错误 {detail.scenarios.summary.error}</Tag>
                  </Space>
                </div>
              )}

              {/* 场景卡片列表 */}
              {detail.scenarios.items.map((scenario, idx) => (
                <Card
                  key={idx}
                  size="small"
                  style={{ marginBottom: 12 }}
                  title={
                    <Space size={8}>
                      <Tag
                        color={
                          scenario.status === 'passed'
                            ? 'success'
                            : scenario.status === 'warning'
                              ? 'warning'
                              : 'error'
                        }
                      >
                        {scenario.status === 'passed'
                          ? '✅ 通过'
                          : scenario.status === 'warning'
                            ? '⚠️ 警告'
                            : scenario.status === 'failed'
                              ? '✗ 失败'
                              : '✗ 错误'}
                      </Tag>
                      <Typography.Text strong>{scenario.scenario_id}</Typography.Text>
                      {scenario.description && (
                        <Typography.Text type="secondary">{scenario.description}</Typography.Text>
                      )}
                    </Space>
                  }
                >
                  {/* 失败断言明细 */}
                  {scenario.assertions && scenario.assertions.some((a) => !a.passed) && (
                    <div style={{ marginBottom: 8 }}>
                      <Typography.Text strong style={{ display: 'block', marginBottom: 4 }}>
                        失败断言:
                      </Typography.Text>
                      {scenario.assertions
                        .filter((a) => !a.passed)
                        .map((assertion, aIdx) => (
                          <div
                            key={aIdx}
                            style={{
                              padding: '4px 8px',
                              marginBottom: 4,
                              background: '#fff2f0',
                              border: '1px solid #ffccc7',
                              borderRadius: 4,
                            }}
                          >
                            <Typography.Text type="danger">✗ {assertion.message || '断言失败'}</Typography.Text>
                          </div>
                        ))}
                    </div>
                  )}

                  {/* 失败步骤明细 */}
                  {scenario.steps && scenario.steps.some((s) => s.status === 'failed') && (
                    <div>
                      <Typography.Text strong style={{ display: 'block', marginBottom: 4 }}>
                        失败步骤:
                      </Typography.Text>
                      {scenario.steps
                        .filter((s) => s.status === 'failed')
                        .map((step, sIdx) => (
                          <div
                            key={sIdx}
                            style={{
                              padding: '4px 8px',
                              marginBottom: 4,
                              background: '#fff2f0',
                              border: '1px solid #ffccc7',
                              borderRadius: 4,
                            }}
                          >
                            <Typography.Text type="danger">
                              ✗ {step.name}: {step.error || '步骤失败'}
                            </Typography.Text>
                          </div>
                        ))}
                    </div>
                  )}
                </Card>
              ))}
            </div>
          ) : (
            <Empty description="暂无场景结果" />
          )}
        </div>
      ),
    },
    {
      key: 'bugs',
      label: 'Bug 列表',
      children: (
        <div style={{ padding: '20px 0' }}>
          <Empty description="暂无 Bug" />
        </div>
      ),
    },
    {
      key: 'screenshots',
      label: '失败截图',
      children: (
        <div style={{ padding: '20px 0' }}>
          <Empty description="暂无失败截图" />
        </div>
      ),
    },
  ];

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

      {/* 页签区 */}
      <Card>
        <Tabs items={tabItems} />
      </Card>
    </PageContainer>
  );
}