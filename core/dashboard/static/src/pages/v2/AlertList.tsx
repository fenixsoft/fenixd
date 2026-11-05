// v2 告警行共享渲染（redesign-dashboard-v2-ui）：概览告警横幅与运维页「人工
// 告警」页签复用同一行渲染——严重级胶囊 + 多行明细（pre-wrap）+ 裁决选择题/
// 标记已处理闭环。裁决交互实体复用全局共享 hook（useAlertAdjudication，同现产
// 横幅/详情页语义单源：防重、destructive 二次确认、结果文案），本组件只承载
// Bento 视觉与容器布局。
import { App, Button, Input, Popover, Select } from 'antd';
import { useState } from 'react';
import dayjs from 'dayjs';
import { markAlertHandled } from '@/services/dashboard';
import type { AlertItem } from '@/services/dashboard';
import { useAlertAdjudication, AlertAdjudicationExec } from '@/hooks/useAlertAdjudication';
import { V2Pill } from './shared';
import { useV2IsMobile, V2_SPLIT, V2_TEXT_QUATERNARY, V2_TEXT_SECONDARY } from './theme';

/** 严重级 → 中文短标签（定稿原型 ops.html/variant-b-bento.html 词表）。 */
const SEV_LABEL: Record<string, string> = { critical: '严重', major: '较重', minor: '轻微' };

function sevTone(sev?: string): string {
  if (sev === 'critical') return 'critical';
  if (sev === 'major') return 'warning';
  return 'muted';
}

/** 单条告警行。last=true 时省略顶部分隔线（列表末行）。移动形态（prototype/
 * m-ops.html ops-alert-item）：堆叠卡——胶囊在上、明细换行完整（pre-wrap）、
 * 裁决 Select 全宽、执行/标记已处理按钮行（无选择题时标记已处理全宽单按钮）。 */
export function V2AlertRow({
  alert,
  last,
  onChanged,
}: {
  alert: AlertItem;
  last?: boolean;
  onChanged?: () => void;
}) {
  const { message } = App.useApp();
  const adj = useAlertAdjudication();
  const mobile = useV2IsMobile();
  // 附注输入开合（Popover 受控）：确认后写入共享 hook 的 alertNotes（裁决提交
  // 随 resolveAlert note 通道走）
  const [noteOpen, setNoteOpen] = useState(false);
  const [handling, setHandling] = useState(false);
  const hasChoices = (alert.choices || []).length > 0;
  const detailed = Boolean(alert.evidence) || hasChoices;

  const markHandled = async () => {
    setHandling(true);
    try {
      await markAlertHandled(alert.project, alert.id);
      message.success('已标记处理');
      onChanged?.();
    } catch (e) {
      message.error(`标记失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setHandling(false);
    }
  };

  if (mobile) {
    const selChoiceId = adj.alertChoiceSels[alert.id] || '';
    return (
      <div style={{ padding: '10px 2px', borderTop: last ? 'none' : `1px solid ${V2_SPLIT}` }}>
        <V2Pill tone={sevTone(alert.severity)}>{SEV_LABEL[alert.severity || ''] || alert.severity || '未知'}</V2Pill>
        <div style={{ fontSize: 13.5, fontWeight: 600, marginTop: 5, whiteSpace: 'pre-wrap' }}>
          {alert.description || alert.id}
        </div>
        {alert.evidence ? (
          <div
            style={{
              fontSize: 12.5,
              color: V2_TEXT_SECONDARY,
              lineHeight: '19px',
              whiteSpace: 'pre-wrap',
              marginTop: 4,
            }}
          >
            {alert.evidence}
          </div>
        ) : null}
        <div className="v2-num" style={{ fontSize: 12, color: V2_TEXT_QUATERNARY, marginTop: 4 }}>
          {alert.project ? `项目 ${alert.project}` : ''}
          {alert.spec ? ` · ${alert.spec}` : ''}
          {alert.created ? ` · ${dayjs(alert.created).format('MM-DD HH:mm')}` : ''}
        </div>
        {hasChoices ? (
          <>
            <Select
              size="small"
              placeholder="选择处置动作"
              style={{ width: '100%', marginTop: 8 }}
              value={selChoiceId || undefined}
              onChange={(v) => adj.setAlertChoiceSels((s) => ({ ...s, [alert.id]: v }))}
              options={(alert.choices || []).map((c) => ({ value: c.id, label: c.label, title: c.desc }))}
            />
            <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center' }}>
              <Popover
                title="处置附注"
                trigger="click"
                open={noteOpen}
                onOpenChange={setNoteOpen}
                content={
                  <div style={{ width: 260 }}>
                    <Input.TextArea
                      rows={2}
                      value={adj.alertNotes[alert.id] || ''}
                      onChange={(e) => adj.setAlertNotes((s) => ({ ...s, [alert.id]: e.target.value }))}
                      placeholder="随裁决留痕写入（可空）"
                    />
                  </div>
                }
              >
                <a className="touch-expand" style={{ fontSize: 12, color: V2_TEXT_QUATERNARY }}>
                  附注{adj.alertNotes[alert.id] ? '·已填' : ''}
                </a>
              </Popover>
              <span style={{ flex: 1 }} />
              <AlertAdjudicationExec alert={alert} adj={adj} onResolved={onChanged} />
            </div>
          </>
        ) : (
          <Button size="small" block loading={handling} onClick={() => void markHandled()} style={{ marginTop: 8 }}>
            标记已处理
          </Button>
        )}
      </div>
    );
  }

  const kids = [
    <div key="title" className="v2-ellipsis" style={{ fontSize: 13, fontWeight: 500 }}>
      {alert.description || alert.id}
    </div>,
  ];
  if (alert.evidence) {
    kids.push(
      <div
        key="body"
        style={{
          fontSize: 12,
          color: V2_TEXT_SECONDARY,
          lineHeight: '20px',
          whiteSpace: 'pre-wrap',
          marginTop: 5,
        }}
      >
        {alert.evidence}
      </div>,
    );
  }
  if (hasChoices) {
    const selChoiceId = adj.alertChoiceSels[alert.id] || '';
    kids.push(
      <div key="choices" style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
        <Select
          size="small"
          placeholder="选择处置动作"
          style={{ width: 220 }}
          value={selChoiceId || undefined}
          onChange={(v) => adj.setAlertChoiceSels((s) => ({ ...s, [alert.id]: v }))}
          options={(alert.choices || []).map((c) => ({ value: c.id, label: c.label, title: c.desc }))}
        />
        <Popover
          title="处置附注"
          trigger="click"
          open={noteOpen}
          onOpenChange={setNoteOpen}
          content={
            <div style={{ width: 260 }}>
              <Input.TextArea
                rows={2}
                value={adj.alertNotes[alert.id] || ''}
                onChange={(e) => adj.setAlertNotes((s) => ({ ...s, [alert.id]: e.target.value }))}
                placeholder="随裁决留痕写入（可空）"
              />
            </div>
          }
        >
          <a style={{ fontSize: 12, color: V2_TEXT_QUATERNARY }}>
            附注{adj.alertNotes[alert.id] ? '·已填' : ''}
          </a>
        </Popover>
        <AlertAdjudicationExec alert={alert} adj={adj} onResolved={onChanged} />
      </div>,
    );
  }
  kids.push(
    <div
      key="meta"
      className="v2-num"
      style={{ fontSize: 12, color: V2_TEXT_QUATERNARY, marginTop: detailed ? 6 : 1 }}
    >
      {alert.project ? `项目 ${alert.project}` : ''}
      {alert.spec ? ` · ${alert.spec}` : ''}
      {alert.created ? ` · ${dayjs(alert.created).format('MM-DD HH:mm')}` : ''}
    </div>,
  );

  return (
    <div
      style={{
        display: 'flex',
        alignItems: detailed ? 'flex-start' : 'center',
        gap: 10,
        padding: '9px 10px',
        borderTop: last ? 'none' : `1px solid ${V2_SPLIT}`,
      }}
    >
      <V2Pill tone={sevTone(alert.severity)}>{SEV_LABEL[alert.severity || ''] || alert.severity || '未知'}</V2Pill>
      <div style={{ flex: 1, minWidth: 0 }}>{kids}</div>
      {hasChoices ? null : (
        <Button size="small" loading={handling} onClick={() => void markHandled()} style={alert.evidence ? { marginTop: 2 } : undefined}>
          标记已处理
        </Button>
      )}
    </div>
  );
}

/** 告警行容器（Bento 白磁贴内的行集合；顶部行无分隔线由行内 last 判定）。 */
export function V2AlertRows({
  alerts,
  onChanged,
}: {
  alerts: AlertItem[];
  onChanged?: () => void;
}) {
  return (
    <div>
      {alerts.map((a, i) => (
        <V2AlertRow key={a.id} alert={a} last={i === alerts.length - 1} onChanged={onChanged} />
      ))}
    </div>
  );
}
