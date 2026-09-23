import { Alert, App, Button, Card, Collapse, Input, List, Popconfirm, Select, Space, Tag, Typography } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useState } from 'react';
import type { AlertItem, AlertsData } from '@/services/dashboard';
import { clearAllAlerts, getAlerts, markAlertHandled, resolveAlert } from '@/services/dashboard';
import { fmtEvidence } from '@/utils/evidence';

/**
 * 人工升级告警横幅（对齐 v1：/api/alerts + SSE alerts 事件驱动刷新）。
 * antd 组合：Alert banner（条）+ List（待处理项，含标记已处理）+ Collapse（已解决折叠区）。
 * 乐观移除：点击标记后先前端隐藏，后端确认消失后才真正清除（防 3s 收敛窗口内重现）。
 * add-human-adjudication-choices 5.4：带 choices 的告警内嵌裁决选择题
 * （Select + note + 执行，与 SPEC 详情页同一 alert-resolve 闭环端点），
 * abandon / skip_review_gate 执行前二次确认；无 choices 保持「标记已处理」。
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
  // add-human-adjudication-choices 5.4：裁决选择题交互状态（按告警 id 分键）
  const [alertChoiceSels, setAlertChoiceSels] = useState<Record<string, string>>({});
  const [alertNotes, setAlertNotes] = useState<Record<string, string>>({});
  const [resolvingAlerts, setResolvingAlerts] = useState<Set<string>>(new Set());
  const [alertResolveMsgs, setAlertResolveMsgs] = useState<Record<string, { text: string; tone: 'error' | 'info' }>>({});

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

  // add-human-adjudication-choices 5.4：横幅内人工裁决闭环（同详情页语义：
  // loading 防重、成功回显步骤、失败展示错误且恢复可交互可重试）
  const handleResolve = async (a: AlertItem, choiceId: string) => {
    if (resolvingAlerts.has(a.id)) return;
    setResolvingAlerts((s) => new Set(s).add(a.id));
    setAlertResolveMsgs((m) => {
      const n = { ...m };
      delete n[a.id];
      return n;
    });
    try {
      const r = await resolveAlert(a.project, a.id, choiceId, alertNotes[a.id] || '');
      const steps = Array.isArray(r.steps) ? r.steps : [];
      // 成功文案按后端结果如实组织（code-review item 896c7e54dafd）：留痕写入
      // 失败后端只落 WARNING 不回滚动作，marked=false（kind 不匹配/并发处置）
      // 时告警仍在——旧实现一律断言「留痕已写入」，审计轨迹缺失时误导用户
      const caveats: string[] = [];
      if (r.marked === false) caveats.push('告警未入已处理（可重试「标记已处理」）');
      if (r.disposition_logged === false) caveats.push('处置留痕写入失败（审计轨迹缺失）');
      const stepSuffix = steps.length ? `：${steps.join('；')}` : '';
      const text = caveats.length
        ? `裁决已执行${stepSuffix}（${caveats.join('；')}）`
        : `裁决已执行，处置留痕已写入${stepSuffix}`;
      setAlertResolveMsgs((m) => ({ ...m, [a.id]: { text, tone: 'info' } }));
      if (caveats.length) {
        message.warning(text);
      } else {
        message.success('裁决已执行，处置留痕已写入');
      }
      void load();
    } catch (err) {
      setAlertResolveMsgs((m) => ({
        ...m,
        [a.id]: { text: err instanceof Error ? err.message : String(err), tone: 'error' },
      }));
      message.error('裁决执行失败，告警保持未处理，可调整后重试');
    } finally {
      setResolvingAlerts((s) => {
        const n = new Set(s);
        n.delete(a.id);
        return n;
      });
    }
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
            renderItem={(a) => {
              const adjudicable = Array.isArray(a.choices) && a.choices.length > 0;
              const selChoiceId = alertChoiceSels[a.id] || '';
              const selChoice = (a.choices || []).find((c) => c.id === selChoiceId);
              /* 不可逆/越权裁决（撤销丢弃 / 跳过评审门）执行前二次确认（5.3）。
                 确认门由注册表的 destructive 标志驱动（code-review item
                 19f72b875e8f：业务 id 由后端单源拥有，前端硬编码会在 id 改名
                 时静默丢失二次确认）；历史告警快照（D2 不回写）缺该字段时，
                 按已知不可逆 id 回退保底。 */
              const needsConfirm =
                selChoice?.destructive === true ||
                (selChoice?.destructive === undefined &&
                  (selChoiceId === 'abandon' || selChoiceId === 'skip_review_gate'));
              const resolving = resolvingAlerts.has(a.id);
              const resolveMsg = alertResolveMsgs[a.id];
              const execBtn = (
                <Button
                  key="exec"
                  size="small"
                  type={needsConfirm ? 'primary' : 'default'}
                  danger={needsConfirm}
                  loading={resolving}
                  disabled={!selChoiceId || resolving}
                  onClick={() => selChoiceId && !needsConfirm && void handleResolve(a, selChoiceId)}
                >
                  执行
                </Button>
              );
              return (
                <List.Item
                  actions={[
                    adjudicable ? (
                      needsConfirm ? (
                        <Popconfirm
                          key="exec"
                          title="确认执行该裁决？"
                          description={selChoice?.desc || '该操作可能不可自动恢复，请确认'}
                          okText="确认执行"
                          cancelText="取消"
                          onConfirm={() => selChoiceId && void handleResolve(a, selChoiceId)}
                          disabled={resolving}
                        >
                          {execBtn}
                        </Popconfirm>
                      ) : (
                        execBtn
                      )
                    ) : null,
                    <Button key="handled" size="small" onClick={() => void handleOne(a)}>
                      标记已处理
                    </Button>,
                  ].filter(Boolean)}
                >
                  <List.Item.Meta
                    title={<AlertTitle item={a} />}
                    description={
                      <>
                        <AlertLines item={a} />
                        {adjudicable && (
                          /* 裁决控件常驻；wrap 布局适配窄屏（screen-xs 自查）。
                             静态样式落样式表类（code-review item d893e16d11de），
                             行内 style 只留真正动态的值 */
                          <div className="alert-adjudication-row">
                            <Select
                              size="small"
                              className="alert-adjudication-select"
                              placeholder="选择裁决项"
                              value={selChoiceId || undefined}
                              onChange={(v) => setAlertChoiceSels((m) => ({ ...m, [a.id]: v }))}
                              disabled={resolving}
                              options={(a.choices || []).map((c) => ({ value: c.id, label: c.label, title: c.desc }))}
                            />
                            <Input
                              size="small"
                              className="alert-adjudication-input"
                              maxLength={200}
                              placeholder="处置依据（可选）"
                              value={alertNotes[a.id] || ''}
                              onChange={(e) => setAlertNotes((m) => ({ ...m, [a.id]: e.target.value }))}
                              disabled={resolving}
                            />
                          </div>
                        )}
                        {adjudicable && selChoice?.desc && (
                          <div className="alert-adjudication-desc">
                            <Typography.Text type="secondary">{selChoice.desc}</Typography.Text>
                          </div>
                        )}
                        {resolveMsg && (
                          <div className="alert-resolve-msg">
                            <Typography.Text type={resolveMsg.tone === 'error' ? 'danger' : 'secondary'}>
                              {resolveMsg.text}
                            </Typography.Text>
                          </div>
                        )}
                      </>
                    }
                  />
                </List.Item>
              );
            }}
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
