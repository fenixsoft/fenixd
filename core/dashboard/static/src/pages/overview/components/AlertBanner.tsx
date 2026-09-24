import { Alert, App, Button, Card, Collapse, Input, List, Select, Space, Typography } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import type { AlertItem, AlertsData } from '@/services/dashboard';
import { clearAllAlerts, getAlerts, markAlertHandled } from '@/services/dashboard';
// 告警标题/明细展示单源（code-review item 5478d16d70c7，SEV 常量与 fmtDate 同源收敛）
import { AlertLines, AlertTitle } from '@/components/alert-shared';
// 裁决交互收敛共享 hook（code-review item f86171cc149d）：状态四元组、结果
// 文案、destructive 二次确认门与 SPEC 详情页同源，本组件只注入刷新回调
import { AlertAdjudicationExec, useAlertAdjudication } from '@/hooks/useAlertAdjudication';

/**
 * 人工升级告警横幅（对齐 v1：/api/alerts + SSE alerts 事件驱动刷新）。
 * antd 组合：Alert banner（条）+ List（待处理项，含标记已处理）+ Collapse（已解决折叠区）。
 * 乐观移除：点击标记后先前端隐藏，后端确认消失后才真正清除（防 3s 收敛窗口内重现）。
 * add-human-adjudication-choices 5.4：带 choices 的告警内嵌裁决选择题
 * （Select + note + 执行，与 SPEC 详情页同一 alert-resolve 闭环端点），
 * abandon / skip_review_gate 执行前二次确认；无 choices 保持「标记已处理」。
 */
// 横幅仅剩排序用途的 SEV 权重（标签/配色/标题/明细已收敛到 components/alert-shared）
const SEV_RANK: Record<string, number> = { critical: 3, major: 2, minor: 1 };

function sevRank(sev?: string) {
  return SEV_RANK[sev || ''] || 0;
}

export default function AlertBanner({ refreshTick }: { refreshTick: number }) {
  const { message } = App.useApp();
  const [data, setData] = useState<AlertsData | null>(null);
  const [optimistic, setOptimistic] = useState<string[]>([]);
  const [expanded, setExpanded] = useState(true);
  // add-human-adjudication-choices 5.4：裁决选择题交互状态经共享 hook
  //（按告警 id 分键；与 SPEC 详情页同源，item f86171cc149d）
  const adj = useAlertAdjudication();
  const {
    alertChoiceSels, setAlertChoiceSels, alertNotes, setAlertNotes,
    resolvingAlerts, alertResolveMsgs,
  } = adj;

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
      // 失败即回滚乐观遮蔽：后端列表仍含该 id，收敛逻辑（上）不会清 optimistic，
      // 不回滚会让未处理告警被永久隐藏（违背上方「绝不永久遮蔽」）
      setOptimistic((prev) => prev.filter((id) => id !== a.id));
      message.error(`标记失败：${err instanceof Error ? err.message : String(err)}`);
    }
    void load();
  };

  // add-human-adjudication-choices 5.4：横幅内人工裁决闭环——交互实体在共享
  // hook（同详情页语义：loading 防重、成功回显步骤、失败展示错误且恢复可交互
  // 可重试），刷新回调经执行按钮的 onResolved 注入

  const handleClearAll = async () => {
    try {
      await clearAllAlerts();
      // 不整组清空 optimistic：若另有 handleOne 的 markAlertHandled 在途，
      // 其 id 已入遮蔽、尚未获后端确认，整组清空会让它提前露出并以
      // 「未处理」闪现。复用上方收敛 effect 的口径——保留遮蔽，待下方
      // load 拉到后端已无该告警的数据后由收敛 effect 统一移除（绝不永久遮蔽）。
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
            {
              // [fenix-ignore:056de6cf9b67] 窄屏（<768px）已由 global.less 的 screen-xs/sm 规则以 max-width:100% !important + 多行换行接管该省略文本（选择器命中 .ant-alert-title .ant-typography-ellipsis 已核实），内联 560px 仅桌面端生效，375px 级视口不会横向溢出
            }
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
              const resolving = resolvingAlerts.has(a.id);
              const resolveMsg = alertResolveMsgs[a.id];
              return (
                <List.Item
                  actions={[
                    adjudicable ? (
                      /* 执行按钮（含 destructive 二次确认门）经共享控件，
                         确认门与详情页同源（item f86171cc149d）；裁决成功后
                         重拉横幅数据 */
                      <AlertAdjudicationExec key="exec" alert={a} adj={adj} onResolved={() => void load()} />
                    ) : null,
                    <Button key="handled" size="small" onClick={() => void handleOne(a)}>
                      标记已处理
                    </Button>,
                  ].filter(Boolean)}
                >
                  <List.Item.Meta
                    title={<AlertTitle item={a} variant="banner" />}
                    description={
                      <>
                        <AlertLines item={a} variant="banner" />
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
                          title={<AlertTitle item={a} resolved variant="banner" />}
                          description={<AlertLines item={a} variant="banner" />}
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
