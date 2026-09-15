import { Alert, App, Button, Card, Collapse, List, Space, Tag, Typography } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useState } from 'react';
import type { AlertItem, AlertsData } from '@/services/dashboard';
import { clearAllAlerts, getAlerts, markAlertHandled } from '@/services/dashboard';
import { fmtEvidence } from '@/utils/evidence';

/**
 * 人工升级告警横幅（对齐 v1：/api/alerts + SSE alerts 事件驱动刷新）。
 * antd 组合：Alert banner（条）+ List（待处理项，含标记已处理）+ Collapse（已解决折叠区）。
 * 乐观移除：点击标记后先前端隐藏，后端确认消失后才真正清除（防 3s 收敛窗口内重现）。
 */
const SEV_LABEL: Record<string, string> = { critical: '严重', major: '较高', warning: '警告', minor: '一般' };
const SEV_COLOR: Record<string, string> = { critical: 'red', major: 'orange', minor: 'blue' };
const SEV_RANK: Record<string, number> = { critical: 3, major: 2, minor: 1 };

function sevRank(sev?: string) {
  return SEV_RANK[sev || ''] || 0;
}

function fmtDate(iso?: string) {
  if (!iso) return '';
  const d = dayjs(iso);
  return d.isValid() ? d.format('MM-DD HH:mm:ss') : String(iso);
}

function AlertLines({ item }: { item: AlertItem }) {
  // pre-wrap 保留字段内的 \n / \t 格式（JSON 存储层未丢失，HTML 默认会折叠成空格）
  const evidenceText = fmtEvidence(item.evidence);
  return (
    <div style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
      <div>{item.spec ? `📌 ${item.spec} ` : ''}{item.description}</div>
      {evidenceText ? (
        <Typography.Text type="secondary">证据：{evidenceText}</Typography.Text>
      ) : null}
      {item.action_taken ? (
        <div>
          <Typography.Text type="secondary">处置：{item.action_taken}</Typography.Text>
        </div>
      ) : null}
      {item.recommended_action ? (
        <div>
          <Typography.Text type="secondary">建议：{item.recommended_action}</Typography.Text>
        </div>
      ) : null}
      {item.resolve_note ? (
        <div>
          <Typography.Text type="secondary">解决依据：{item.resolve_note}</Typography.Text>
        </div>
      ) : null}
    </div>
  );
}

function AlertTitle({ item, resolved }: { item: AlertItem; resolved?: boolean }) {
  return (
    <Space wrap size={6}>
      <Tag color={SEV_COLOR[item.severity || ''] || 'default'} style={{ marginInlineEnd: 0 }}>
        {SEV_LABEL[item.severity || ''] || item.severity || '未知'}
      </Tag>
      {resolved ? (
        <Tag style={{ marginInlineEnd: 0 }} color={item.handled_by === 'auto-resolve' ? 'cyan' : 'geekblue'}>
          {item.handled_by === 'auto-resolve' ? '🤖 自动解决' : '👤 人工处理'}
        </Tag>
      ) : null}
      {item.project ? <Tag style={{ marginInlineEnd: 0 }}>{item.project}</Tag> : null}
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {fmtDate(resolved ? item.handled_at || item.created : item.created)}
      </Typography.Text>
    </Space>
  );
}

export default function AlertBanner({ refreshTick }: { refreshTick: number }) {
  const { message } = App.useApp();
  const [data, setData] = useState<AlertsData | null>(null);
  const [optimistic, setOptimistic] = useState<string[]>([]);
  const [expanded, setExpanded] = useState(true);

  const load = useCallback(async () => {
    try {
      const d = await getAlerts();
      if (!d.error) setData(d);
    } catch {
      // 告警拉取失败静默，不影响主视图
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshTick]);

  const inOptimistic = (id: string) => optimistic.includes(id);
  const alerts = (data?.alerts || []).filter((a) => !inOptimistic(a.id));

  // 后端确认已消失的乐观 id 才真正移除，绝不永久遮蔽
  useEffect(() => {
    if (!optimistic.length || !data) return;
    const stillThere = new Set((data.alerts || []).map((a) => a.id));
    const next = optimistic.filter((id) => stillThere.has(id));
    if (next.length !== optimistic.length) setOptimistic(next);
  }, [data, optimistic]);

  if (!alerts.length) return null;

  const count = Math.min(data?.total_unhandled ?? alerts.length, alerts.length);
  const top = alerts.reduce((m, a) => (sevRank(a.severity) > sevRank(m.severity) ? a : m), alerts[0]);
  const latest = alerts[0];
  const resolved = (data?.resolved || []).filter((a) => !inOptimistic(a.id));

  const handleOne = async (a: AlertItem) => {
    setOptimistic((prev) => [...prev, a.id]);
    try {
      await markAlertHandled(a.project, a.id);
      message.success('已标记处理');
    } catch (err) {
      message.error(`标记失败：${err instanceof Error ? err.message : String(err)}`);
    }
    void load();
  };

  const handleClearAll = async () => {
    try {
      await clearAllAlerts();
      setOptimistic([]);
      message.success('已清理所有事件');
    } catch (err) {
      message.error(`清理失败：${err instanceof Error ? err.message : String(err)}`);
    }
    void load();
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <Alert
        banner
        type={top.severity === 'critical' ? 'error' : 'warning'}
        showIcon
        message={
          <Space wrap size={8}>
            <span style={{ fontWeight: 600 }}>需人工介入</span>
            <span>{count} 条未处理</span>
            <Typography.Text ellipsis style={{ maxWidth: 560 }}>
              {latest.project ? `[${latest.project}] ` : ''}
              {latest.description || latest.action_taken || ''}
            </Typography.Text>
          </Space>
        }
        action={
          <Space size={4}>
            <Button size="small" type="text" onClick={() => setExpanded((v) => !v)}>
              {expanded ? '收起列表' : '展开列表'}
            </Button>
            <Button size="small" type="text" onClick={() => void handleClearAll()}>
              清理所有事件
            </Button>
          </Space>
        }
      />
      {expanded ? (
        <Card variant="borderless" styles={{ body: { paddingBlock: 0 } }}>
          <List
            size="small"
            dataSource={alerts}
            renderItem={(a) => (
              <List.Item
                actions={[
                  <Button key="handled" size="small" onClick={() => void handleOne(a)}>
                    标记已处理
                  </Button>,
                ]}
              >
                <List.Item.Meta title={<AlertTitle item={a} />} description={<AlertLines item={a} />} />
              </List.Item>
            )}
          />
        </Card>
      ) : null}
      {resolved.length ? (
        <Card variant="borderless" style={{ marginTop: 8 }} styles={{ body: { paddingBlock: 0 } }}>
          <Collapse
            ghost
            items={[
              {
                key: 'resolved',
                label: `已解决 (${resolved.length})`,
                children: (
                  <List
                    size="small"
                    dataSource={resolved}
                    renderItem={(a) => (
                      <List.Item>
                        <List.Item.Meta
                          title={<AlertTitle item={a} resolved />}
                          description={<AlertLines item={a} />}
                        />
                      </List.Item>
                    )}
                  />
                ),
              },
            ]}
          />
        </Card>
      ) : null}
    </div>
  );
}
