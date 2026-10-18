import { Alert, App, Button, Card, Collapse, Input, List, Select, Space, Typography } from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { AlertItem, AlertsData } from '@/services/dashboard';
import { clearAllAlerts, getAlerts } from '@/services/dashboard';
// 告警标题/明细展示单源（code-review item 5478d16d70c7，SEV 常量与 fmtDate 同源收敛）
import {
  AlertActionColumn,
  AlertLines,
  AlertReportButton,
  AlertTitle,
  hasNarrativeReport,
} from '@/components/alert-shared';
// 裁决交互收敛共享 hook（code-review item f86171cc149d）：状态四元组、结果
// 文案、destructive 二次确认门与 SPEC 详情页同源，本组件只注入刷新回调
import { AlertAdjudicationExec, useAlertAdjudication } from '@/hooks/useAlertAdjudication';
// 乐观遮蔽/标记已处理收敛共享 hook（code-review items d9c50f5bcc38、
// e673281b0b03）：与 activities 页同源逻辑单点维护，两页复用
import { useOptimisticAlerts } from '@/hooks/useOptimisticAlerts';

/**
 * 人工升级告警横幅（对齐 v1：/api/alerts + SSE alerts 事件驱动刷新）。
 * antd 组合：Alert banner（条）+ List（待处理项，含标记已处理）+ Collapse（已解决折叠区）。
 * 乐观移除：点击标记后先前端隐藏，标记成功后由共享 hook 收敛（后端确认消失或
 * 超时兜底解除，防 3s 收敛窗口内重现；失败立即回滚，见 useOptimisticAlerts）。
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
  const { message, modal } = App.useApp();
  const [data, setData] = useState<AlertsData | null>(null);
  // 告警拉取失败提示（code-review item f6ef9d6c2c12）：对齐 activities 页口径
  // （fix df39d8bbc138）——人工告警接口失败必须提示，不再静默吞掉；主视图不受阻断
  const [loadError, setLoadError] = useState<string | null>(null);
  // 乐观遮蔽单源（items d9c50f5bcc38、e673281b0b03）：optimistic、inOptimistic、
  // 收敛 effect（确认消失/超时兜底）与 markHandled 包装都在共享 hook 内
  const { optimistic, inOptimistic, markHandled } = useOptimisticAlerts(data);
  const [expanded, setExpanded] = useState(true);
  // add-human-adjudication-choices 5.4：裁决选择题交互状态经共享 hook
  //（按告警 id 分键；与 SPEC 详情页同源，item f86171cc149d）
  const adj = useAlertAdjudication();
  const {
    alertChoiceSels, setAlertChoiceSels, alertNotes, setAlertNotes,
    resolvingAlerts, alertResolveMsgs,
  } = adj;

  // fix 9e69e892b7e5: load 自增请求序号——refreshTick / handleOne / handleClearAll /
  // 裁决 onResolved 多处触发的 load 可并发在飞，响应到达顺序不保证，旧响应后到会把
  // 已处理告警的旧快照写回 setData 致其闪回「未处理」。仿 activities 页 loadSeqRef
  // （fix 01635701025b）：仅最新一次请求允许落状态，过期响应（含其失败）直接丢弃
  const loadSeqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeqRef.current;
    try {
      const d = await getAlerts();
      // 写回前复核序号：过期请求不改写任何状态（data 与 loadError 均不覆盖）
      if (seq !== loadSeqRef.current) return;
      if (!d.error) {
        setData(d);
        setLoadError(null);
      } else {
        // 响应级 error 同样上屏（对齐 activities 页 fix 2ca9c5ff7be6 的 alerts.error
        // 通道口径）；保留旧 data 不覆盖，主视图不因失败回退为空
        setLoadError(d.error);
      }
    } catch (err) {
      // 过期请求的失败同样不落状态，防旧错误提示覆盖新请求结果
      if (seq !== loadSeqRef.current) return;
      // 请求级失败不再静默（item f6ef9d6c2c12）：上屏轻量错误提示，主视图不受阻断
      setLoadError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshTick]);

  const alerts = (data?.alerts || []).filter((a) => !inOptimistic(a.id));

  // 轻量错误提示（item f6ef9d6c2c12）：文案对齐 activities 页「人工告警加载失败」，
  // 保留主视图不阻断——有告警时与横幅并存，无告警时单独呈现不静默
  const errorBanner = loadError ? (
    <Alert banner type="error" showIcon message={`人工告警加载失败：${loadError}`} />
  ) : null;

  if (!alerts.length) {
    return errorBanner ? <div style={{ marginBottom: 16 }}>{errorBanner}</div> : null;
  }

  const count = Math.min(data?.total_unhandled ?? alerts.length, alerts.length);
  const top = alerts.reduce((m, a) => (sevRank(a.severity) > sevRank(m.severity) ? a : m), alerts[0]);
  const latest = alerts[0];
  const resolved = (data?.resolved || []).filter((a) => !inOptimistic(a.id));

  const handleOne = async (a: AlertItem) => {
    // markHandled（hook 单源）：成功返回 null、失败已回滚并返回错误文案
    const err = await markHandled(a);
    if (err == null) message.success('已标记处理');
    else message.error(`标记失败：${err}`);
    void load();
  };

  // add-human-adjudication-choices 5.4：横幅内人工裁决闭环——交互实体在共享
  // hook（同详情页语义：loading 防重、成功回显步骤、失败展示错误且恢复可交互
  // 可重试），刷新回调经执行按钮的 onResolved 注入

  // 「清理所有事件」是影响全部项目的破坏性批量操作（后端逐条 mark_alert_handled，
  // 标记单向不可撤销，AdminMonitor 不会对同一告警重新升级），与 ProjectCards 删除
  // 项目的确认约定对齐：先 modal.confirm 说明影响范围，误触不再静默抹掉待决策告警
  const confirmClearAll = () => {
    modal.confirm({
      title: '清理所有事件',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认清理全部项目的 ${count} 条未处理告警？\n\n`}
          该操作会把所有项目的未处理告警标记为已处理，且不可撤销；标记后
          AdminMonitor 不会对同一告警重新升级，请确认已逐条知悉。
        </div>
      ),
      okText: '全部清理',
      okButtonProps: { danger: true },
      cancelText: '取消',
      // 不返回 promise：立即关弹窗，清理在后台进行（与 ProjectCards 删除同款）
      onOk: () => {
        void handleClearAll();
      },
    });
  };

  const handleClearAll = async () => {
    try {
      await clearAllAlerts();
      // 不整组清空 optimistic：若另有 handleOne 的 markAlertHandled 在途，
      // 其 id 已入遮蔽、尚未获后端确认，整组清空会让它提前露出并以
      // 「未处理」闪现。复用共享 hook 收敛 effect 的口径——保留遮蔽，待下方
      // load 拉到后端已无该告警的数据后由收敛 effect 统一移除（绝不永久遮蔽）。
      message.success('已清理所有事件');
    } catch (err) {
      message.error(`清理失败：${err instanceof Error ? err.message : String(err)}`);
    }
    void load();
  };

  return (
    <div style={{ marginBottom: 16 }}>
      {errorBanner}
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
            <Button size="small" type="text" onClick={confirmClearAll}>
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
                    /* 操作按钮竖排列（查看调查报告/执行/标记已处理同列、随最宽者
                       等宽）：调查报告入口与处置动作同列，先读报告再裁决 */
                    <AlertActionColumn key="ops">
                      {hasNarrativeReport(a) && <AlertReportButton text={a.narrative!.text} />}
                      {adjudicable && (
                        /* 执行按钮（含 destructive 二次确认门）经共享控件，
                           确认门与详情页同源（item f86171cc149d）；裁决成功后
                           重拉横幅数据 */
                        <AlertAdjudicationExec alert={a} adj={adj} onResolved={() => void load()} />
                      )}
                      <Button size="small" onClick={() => void handleOne(a)}>
                        标记已处理
                      </Button>
                    </AlertActionColumn>,
                  ]}
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
                      <List.Item
                        /* 已解决告警保留调查报告入口（处置后补叙照常落盘，
                           历史完整性）；无报告时不传 actions，不出空壳列 */
                        actions={
                          hasNarrativeReport(a)
                            ? [
                                <AlertActionColumn key="report">
                                  <AlertReportButton text={a.narrative!.text} />
                                </AlertActionColumn>,
                              ]
                            : undefined
                        }
                      >
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
