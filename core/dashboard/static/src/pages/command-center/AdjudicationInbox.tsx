// AdjudicationInbox.tsx — 指挥中心「裁决收件箱」屏（add-command-center 4.3）。
//
// 决策卡：严重度徽标/项目/SPEC/signal_type/调查叙事全文/溯源链接/choices
// 选项组（label+desc）。执行复用既有裁决闭环（useAlertAdjudication +
// AlertAdjudicationExec → POST /api/alert-resolve，本屏零新增执行端点）；
// destructive 选项执行前二次确认（Popconfirm 由选项数据驱动）；成功后卡片
// 移出并触发 KPI 刷新（onKpiRefresh → shell kpiTick → 执行台账重拉）；失败
// 保留卡片展示错误可重试；空态「无待人工裁决事项」。

import { useState } from 'react';
import { history } from '@umijs/max';
import { Alert, Empty, Radio, Tag } from 'antd';
import { commandCenterInbox } from '@/services/dashboard';
import type { CommandCenterInbox, CommandCenterInboxCard } from '@/services/dashboard';
import type { AlertItem } from '@/services/dashboard';
import { AlertAdjudicationExec, useAlertAdjudication } from '@/hooks/useAlertAdjudication';
import { useScreenResource } from './useScreen';
import { ScreenErrorPlaceholder, ScreenLoading } from './ScreenStates';
import { BG, PANEL_BORDER, TEXT_MAIN, TEXT_SUB, isDestructiveChoice, severityBadge } from './shared';

// 收件箱卡 → AlertItem 适配：useAlertAdjudication 裁决闭环仅消费
// id/project/choices（resolveAlert(a.project, a.id, choiceId, notes)），
// 其余溯源字段由本屏自有渲染承载。
function toAlertItem(c: CommandCenterInboxCard): AlertItem {
  return {
    id: c.id,
    project: c.project,
    spec: c.spec,
    severity: c.severity,
    created: c.created_at,
    choices: c.choices,
    narrative: c.narrative,
    narrative_pending: c.narrative_pending,
  };
}

function InboxCard({
  card,
  adj,
  onResolved,
}: {
  card: CommandCenterInboxCard;
  adj: ReturnType<typeof useAlertAdjudication>;
  onResolved: () => void;
}) {
  const sev = severityBadge(card.severity);
  const selected = adj.alertChoiceSels[card.id] || '';
  const resolving = adj.resolvingAlerts.has(card.id);
  const resolveMsg = adj.alertResolveMsgs[card.id];
  return (
    <div
      style={{
        border: `1px solid ${PANEL_BORDER}`,
        borderRadius: 8,
        padding: '12px 14px',
        background: BG,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      {/* 头部：严重度徽标 + 溯源（项目/SPEC/signal_type/run） */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
        <Tag color={sev.color} style={{ marginInlineEnd: 0 }}>
          {sev.text}
        </Tag>
        <span style={{ fontWeight: 600 }}>{card.signal_type || card.kind || '升级告警'}</span>
        <span style={{ fontSize: 12, color: TEXT_SUB }}>
          {card.project}
          {card.spec ? (
            <>
              {' / '}
              <a
                onClick={() =>
                  history.push(
                    `/projects/${encodeURIComponent(card.project)}/${encodeURIComponent(card.spec ?? '')}`,
                  )
                }
              >
                {card.spec}
              </a>
            </>
          ) : null}
          {card.run_id ? ` · ${card.run_id}` : ''}
        </span>
      </div>

      {/* 调查叙事全文（侧车合并产物；生成中占位不阻塞 choices） */}
      {card.narrative?.text ? (
        <div
          style={{
            fontSize: 12,
            color: TEXT_MAIN,
            whiteSpace: 'pre-wrap',
            border: `1px solid ${PANEL_BORDER}`,
            borderRadius: 6,
            padding: '8px 10px',
          }}
        >
          {card.narrative.text}
        </div>
      ) : card.narrative_pending ? (
        <div style={{ fontSize: 12, color: TEXT_SUB }}>调查生成中…</div>
      ) : null}

      {/* choices 选项组（label + desc；注册表快照原样） */}
      <Radio.Group
        value={selected}
        onChange={(e) => adj.setAlertChoiceSels((m) => ({ ...m, [card.id]: e.target.value as string }))}
        disabled={resolving}
        style={{ display: 'flex', flexDirection: 'column', gap: 6 }}
      >
        {(card.choices || []).map((choice) => (
          <Radio key={choice.id} value={choice.id}>
            <span>
              {choice.label}
              {isDestructiveChoice(choice) ? (
                <Tag color="red" style={{ marginLeft: 6 }}>
                  不可逆
                </Tag>
              ) : null}
              {choice.desc ? (
                <span style={{ fontSize: 12, color: TEXT_SUB, marginLeft: 8 }}>{choice.desc}</span>
              ) : null}
            </span>
          </Radio>
        ))}
      </Radio.Group>

      {/* 执行行：复用既有裁决执行控件（destructive 二次确认门内聚）+ 留痕回执 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <AlertAdjudicationExec alert={toAlertItem(card)} adj={adj} onResolved={onResolved} />
        {resolveMsg ? (
          <span style={{ fontSize: 12, color: resolveMsg.tone === 'error' ? '#ff4d4f' : TEXT_SUB }}>
            {resolveMsg.text}
          </span>
        ) : null}
      </div>
    </div>
  );
}

export default function AdjudicationInbox({
  active,
  onKpiRefresh,
}: {
  active: boolean;
  onKpiRefresh: () => void;
}) {
  const { data, error, loading, retry } = useScreenResource<CommandCenterInbox>(
    () => commandCenterInbox(),
    active,
  );
  // 裁决闭环单实例（hook 内部按告警 id 分键管理选择/防重/回执）
  const adj = useAlertAdjudication();
  // 裁决成功后卡片本地移出（服务端真相经 60s 轮询回归：仍未决会重新出现）
  const [resolvedIds, setResolvedIds] = useState<Set<string>>(new Set());

  if (error && !data) return <ScreenErrorPlaceholder error={error} onRetry={retry} />;
  if (!data) return <ScreenLoading hint="裁决收件箱加载中" />;

  const cards = data.cards.filter((c) => !resolvedIds.has(c.id));
  return (
    <div>
      {error ? (
        <Alert style={{ marginBottom: 12 }} type="warning" showIcon message={`裁决收件箱刷新失败：${error}`} />
      ) : null}
      {!cards.length ? (
        <div style={{ padding: 48 }}>
          <Empty description="无待人工裁决事项" />
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 860 }}>
          {cards.map((c) => (
            <InboxCard
              key={c.id}
              card={c}
              adj={adj}
              onResolved={() => {
                // 成功 → 卡片移出 + 触发 KPI 刷新（执行台账屏重拉）
                setResolvedIds((s) => new Set(s).add(c.id));
                onKpiRefresh();
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
