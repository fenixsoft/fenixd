// 告警人工裁决共享交互（add-human-adjudication-choices 5.2/5.4）：
// SPEC 详情页告警与 overview AlertBanner 的裁决闭环此前近乎逐行双写（状态
// 四元组 + handleResolve + destructive 二次确认门），两副本会各自漂移（caveat
// 判定一处 !r.marked、一处 r.marked === false）。收敛为共享 hook + 执行按钮
// 控件（code-review item f86171cc149d）：防重、结果文案、二次确认门、服务端
// 契约单源；两 surface 只注入裁决成功后的界面刷新回调。Select/Input 的容器
// 布局差异（横幅把执行按钮放 List actions 列、详情页与控件同行为内联行）留在
// 各自 surface，不做强行统一的视觉变更。
import { App, Button, Popconfirm } from 'antd';
import { useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { AlertChoice, AlertItem } from '@/services/dashboard';
import { resolveAlert } from '@/services/dashboard';

export type AlertResolveMsg = { text: string; tone: 'error' | 'info' };

// 不可逆/越权裁决执行前二次确认（5.3）：确认门由注册表 destructive 标志单源
// 驱动（code-review item 19f72b875e8f，前端不硬编码业务 id）；历史告警快照
//（D2 不回写）缺该字段时按已知不可逆 id 回退保底。
export function choiceNeedsConfirm(selChoice: AlertChoice | undefined, selChoiceId: string): boolean {
  return (
    selChoice?.destructive === true ||
    (selChoice?.destructive === undefined &&
      (selChoiceId === 'abandon' || selChoiceId === 'skip_review_gate'))
  );
}

export interface AlertAdjudication {
  alertChoiceSels: Record<string, string>;
  setAlertChoiceSels: Dispatch<SetStateAction<Record<string, string>>>;
  alertNotes: Record<string, string>;
  setAlertNotes: Dispatch<SetStateAction<Record<string, string>>>;
  resolvingAlerts: Set<string>;
  alertResolveMsgs: Record<string, AlertResolveMsg>;
  handleResolve: (a: AlertItem, choiceId: string, opts?: { onResolved?: () => void }) => Promise<void>;
}

export function useAlertAdjudication(): AlertAdjudication {
  const { message } = App.useApp();
  // 裁决选择题交互状态（按告警 id 分键）
  const [alertChoiceSels, setAlertChoiceSels] = useState<Record<string, string>>({});
  const [alertNotes, setAlertNotes] = useState<Record<string, string>>({});
  const [resolvingAlerts, setResolvingAlerts] = useState<Set<string>>(new Set());
  const [alertResolveMsgs, setAlertResolveMsgs] = useState<Record<string, AlertResolveMsg>>({});

  // 人工裁决一次选择完成处置闭环（动作执行 + 状态推进 + handled + 处置留痕）。
  // loading 防重；成功回显执行步骤并按后端结果如实组织文案（code-review item
  // a09d0b6c26dd / 896c7e54dafd：动作成功但 marked/disposition_logged 为 false
  // 时告警未入已处理/留痕缺失，一律报「留痕已写入」会诱导用户对不可逆裁决
  // 重复执行）；失败展示错误且恢复可交互（告警保持未处理，可调整后重试）。
  const handleResolve = async (
    a: AlertItem,
    choiceId: string,
    opts?: { onResolved?: () => void },
  ) => {
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
      const stepSuffix = steps.length ? `：${steps.join('；')}` : '';
      const caveats: string[] = [];
      if (r.marked === false) caveats.push('告警未入已处理（可重试「标记已处理」）');
      if (r.disposition_logged === false) caveats.push('处置留痕写入失败（审计轨迹缺失）');
      const text = caveats.length
        ? `裁决已执行${stepSuffix}（${caveats.join('；')}）`
        : `裁决已执行，处置留痕已写入${stepSuffix}`;
      setAlertResolveMsgs((m) => ({ ...m, [a.id]: { text, tone: 'info' } }));
      if (caveats.length) {
        message.warning(text);
      } else {
        message.success('裁决已执行，处置留痕已写入');
      }
      opts?.onResolved?.();
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

  return {
    alertChoiceSels,
    setAlertChoiceSels,
    alertNotes,
    setAlertNotes,
    resolvingAlerts,
    alertResolveMsgs,
    handleResolve,
  };
}

// 裁决执行按钮（含 destructive 二次确认门）：横幅放 List actions 列、详情页放
// 裁决控件行尾，确认门/防重/loading 态经共享 hook 单源；onResolved 供 surface
// 注入裁决成功后的界面刷新（横幅重拉列表、详情页刷新告警与 spec 详情）。
export function AlertAdjudicationExec({
  alert,
  adj,
  onResolved,
}: {
  alert: AlertItem;
  adj: AlertAdjudication;
  onResolved?: () => void;
}) {
  const selChoiceId = adj.alertChoiceSels[alert.id] || '';
  const selChoice = (alert.choices || []).find((c) => c.id === selChoiceId);
  const needsConfirm = choiceNeedsConfirm(selChoice, selChoiceId);
  const resolving = adj.resolvingAlerts.has(alert.id);
  const execBtn = (
    <Button
      size="small"
      type={needsConfirm ? 'primary' : 'default'}
      danger={needsConfirm}
      loading={resolving}
      disabled={!selChoiceId || resolving}
      onClick={() =>
        selChoiceId && !needsConfirm && void adj.handleResolve(alert, selChoiceId, { onResolved })
      }
    >
      执行
    </Button>
  );
  if (!needsConfirm) return execBtn;
  return (
    <Popconfirm
      title="确认执行该裁决？"
      description={selChoice?.desc || '该操作可能不可自动恢复，请确认'}
      okText="确认执行"
      cancelText="取消"
      onConfirm={() =>
        selChoiceId && void adj.handleResolve(alert, selChoiceId, { onResolved })
      }
      disabled={resolving}
    >
      {execBtn}
    </Popconfirm>
  );
}
