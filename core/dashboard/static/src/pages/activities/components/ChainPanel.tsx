/**
 * 处置链页签（redesign-chain-panel-ui：bento 卡片重绘）
 *
 * UI 真相源：specs/redesign-chain-panel-ui/prototype/index.html（视觉/布局/
 * 交互以原型为准）。Admin→Arbiter→Human 自动处置链的观测面，五段 bento——
 * 统计行（5 磁贴）→ 人工队列（置首，空则整卡不渲染，内嵌裁决面板）→
 * 链在办（行卡 + 点击处置过程视图）→ 签名配额（按 spec 分组 + 双芯片）→
 * 上升件全量（行卡 + 分段筛选 + 详情抽屉）。数据源 /api/chain
 * （data/admin_alerts.py chain_overview 单读聚合）；项目筛选 Select 由宿主页
 * （activities）在统一标题栏 filters 槽位渲染，本组件只持有数据与轮询。
 *
 * 只读纪律（分层）：视图主面零写动作；唯一执行面是人工队列内嵌裁决（复用
 * alert-resolve 闭环端点，与「告警记录」同款交互），上升件全量/详情抽屉为
 * 纯只读预览。30s 轮询对齐人观测频率；页签失活即卸载，轮询随卸载自动停止。
 *
 * 有意偏离原型的两处（对齐仓库单源而非原型近似值）：严重度配色沿用
 * alert-shared SEV_COLOR 单源（major=orange，与告警记录页签同词表，不引入
 * 跨页签双色）；时间格式化沿用 fmtDate（MM-DD HH:mm:ss，比原型 MM-DD HH:mm
 * 多秒位，属既有共享组件精度）。
 */
import { Alert, App as AntdApp, Button, Drawer, Empty, Input, Radio, Select, Spin, Tag, Timeline } from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { getChainOverview, markAlertHandled, autoExecBadge, autoExecCountdown } from '@/services/dashboard';
import type {
  AlertChoice,
  AlertItem,
  ChainEscalationItem,
  ChainInFlightItem,
  ChainOverviewData,
  ChainSignatureQuota,
} from '@/services/dashboard';
import { AlertAdjudicationExec, useAlertAdjudication } from '@/hooks/useAlertAdjudication';
import type { AlertAdjudication } from '@/hooks/useAlertAdjudication';
import AdminRunModal from './AdminRunModal';
import { SEV_COLOR, SEV_LABEL, fmtDate } from '@/components/alert-shared';
import { DSH_BG_SOFT, DSH_ERROR, DSH_LINK, DSH_TEXT, DSH_TEXT_CAPTION, DSH_TEXT_SECONDARY, DSH_TEXT_TERTIARY, DSH_WARNING } from '@/theme';
import { useIsMobile } from '@/hooks/useIsMobile';

// 轮询周期：与设置页链配置热更新（30s）同拍——观测面无需更快
const REFRESH_MS = 30_000;

// DSH token 色（code-review item 9c524b0c1927：由字面值双写改为 '@/theme'
// 单源 import，消除主题改色漂移面；hair/hover 在 theme.ts 无单源键，
// 保留原型字面值）
const T = {
  text: DSH_TEXT,
  text2: DSH_TEXT_SECONDARY,
  text3: DSH_TEXT_TERTIARY,
  text4: DSH_TEXT_CAPTION,
  hair: '#f1f5f9',
  soft: DSH_BG_SOFT,
  hover: '#f8fafc',
  err: DSH_ERROR,
  warn: DSH_WARNING,
  link: DSH_LINK,
} as const;

// 原型小标签统一形态（11px / 18px 行高 / 6px 水平内边距）
const tagSm = { fontSize: 11, lineHeight: '18px', padding: '0 6px' } as const;

const PHASE_META: Record<string, { label: string; color: string }> = {
  admin: { label: 'Admin 处置中', color: 'blue' },
  arbiter: { label: 'Arbiter 调查中', color: 'purple' },
};

// 链终点短标签（endpoint_kind 封闭词表；未知值回退原文不臆造归因）
const ENDPOINT_META: Record<string, string> = {
  'quota-exhausted': '配额耗尽',
  'dead-man-permanent': '死管永久',
  'arbiter-escalated': '转人工',
  'arbiter-unavailable': 'Arbiter 不可用',
};

/** 签名展示主体：spec 归属优先，spec=null 回落主体键（类型级显式标注） */
function subjectLabel(row: { spec?: string; subject?: string; granularity: string }) {
  if (row.granularity === 'subject') return row.subject || '(主体键缺失)';
  if (row.granularity === 'type') return '(类型级)';
  return row.spec || '(未知)';
}

function sevTag(sev?: string) {
  return (
    <Tag style={{ ...tagSm, marginInlineEnd: 0 }} color={SEV_COLOR[sev || ''] || 'default'}>
      {SEV_LABEL[sev || ''] || sev || '未知'}
    </Tag>
  );
}

/** 耗时格式化（原型 fmtDur：<60 显 Xm，否则 Xh Ym）；分钟不可得显「—」 */
function fmtDur(min: number | null) {
  if (min == null) return '—';
  if (min < 60) return `${min}m`;
  return `${Math.floor(min / 60)}h ${min % 60}m`;
}

/** 入链耗时（started_at → 分钟；脏值/缺失 null——显「—」不伪 0） */
function elapsedMin(startedAt?: string) {
  const t = startedAt ? Date.parse(startedAt) : NaN;
  return Number.isFinite(t) ? Math.max(0, Math.round((Date.now() - t) / 60000)) : null;
}

/** 该签名在办件梯（Admin n/N → Arbiter n/N → 人工；当前相强调、已过相置灰）。
 * used null（签名无计数条目，联查 fail-open）显「—/N」不伪 0 */
function InFlightStepper({ it }: { it: ChainInFlightItem }) {
  const steps = [
    { key: 'admin', label: 'Admin', used: it.admin_attempts_used, cap: it.admin_cap, hasBar: true },
    { key: 'arbiter', label: 'Arbiter', used: it.arbiter_rulings, cap: it.arbiter_cap, hasBar: true },
    { key: 'manual', label: '人工', used: null as number | null, cap: null as number | null, hasBar: false },
  ];
  const curIdx = steps.findIndex((s) => s.key === it.phase);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      {steps.map((s, i) => {
        const state = i === curIdx ? 'cur' : curIdx > i ? 'done' : 'future';
        const labelColor = state === 'cur' ? T.text : state === 'done' ? T.text3 : T.text4;
        // 嵌套三元展开为 if/else（项目清单禁嵌套三元，code-review item 97ea9c6cbb9c）
        let barColor: string | null = null;
        if (s.hasBar) {
          if (state === 'cur') {
            barColor = T.warn;
          } else if (state === 'done') {
            barColor = T.text3;
          } else {
            barColor = 'transparent';
          }
        }
        return (
          <span key={s.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
            <span style={{ color: labelColor, fontWeight: state === 'cur' ? 600 : 400 }}>{s.label}</span>
            {s.cap != null && (
              <span className="ov-mono" style={{ color: T.text3, fontVariantNumeric: 'tabular-nums' }}>
                {s.used ?? '—'}/{s.cap}
              </span>
            )}
            {barColor !== null && (
              <span style={{ width: 72, height: 4, borderRadius: 2, background: T.hair, overflow: 'hidden', display: 'inline-block' }}>
                <span style={{ display: 'block', height: '100%', width: '100%', background: barColor }} />
              </span>
            )}
            {i < steps.length - 1 && <span style={{ color: T.text4, fontSize: 12 }}>→</span>}
          </span>
        );
      })}
    </div>
  );
}

/** 配额静态填充条（56×4）：耗尽红/顶格橙/正常灰 */
function quotaBarColor(used: number, cap: number, exhausted: boolean) {
  if (exhausted) return T.err;
  if (cap > 0 && used >= cap) return T.warn;
  return T.text3;
}

function QuotaChip({ label, used, cap, exhausted }: { label: string; used: number; cap: number; exhausted: boolean }) {
  const pct = cap > 0 ? Math.min(100, Math.round((used * 100) / cap)) : 0;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{ fontSize: 11, color: T.text3 }}>{label}</span>
      <span className="ov-mono" style={{ fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
        {used}/{cap}
      </span>
      <span style={{ width: 56, height: 4, borderRadius: 2, background: T.hair, overflow: 'hidden', display: 'inline-block' }}>
        <span style={{ display: 'block', height: '100%', width: `${pct}%`, borderRadius: 2, background: quotaBarColor(used, cap, exhausted) }} />
      </span>
    </span>
  );
}

/** 签名链上结果标签（原型 outcomeChips）：待人工红/已收口绿/耗尽红/顶格橙/无上升件灰字 */
function outcomeChips(s: ChainSignatureQuota) {
  const chips: ReactNode[] = [];
  const closed = s.esc_total - s.esc_pending;
  if (s.esc_pending > 0) chips.push(<Tag key="p" style={{ ...tagSm, marginInlineEnd: 0 }} color="volcano">待人工 {s.esc_pending}</Tag>);
  if (closed > 0) chips.push(<Tag key="c" style={{ ...tagSm, marginInlineEnd: 0 }} color="green">已收口 {closed}</Tag>);
  if (s.exhausted) chips.push(<Tag key="e" style={{ ...tagSm, marginInlineEnd: 0 }} color="red">配额耗尽</Tag>);
  else if (s.admin_cap > 0 && s.admin_attempts >= s.admin_cap)
    chips.push(<Tag key="af" style={{ ...tagSm, marginInlineEnd: 0 }} color="orange">Admin 顶格</Tag>);
  else if (s.arbiter_cap > 0 && s.arbiter_rulings >= s.arbiter_cap)
    chips.push(<Tag key="rf" style={{ ...tagSm, marginInlineEnd: 0 }} color="orange">Arbiter 顶格</Tag>);
  if (!chips.length) chips.push(<span key="n" style={{ fontSize: 12, color: T.text4 }}>无上升件</span>);
  return chips;
}

// ── 上升件行（人工队列 / 全量共用，原型 EscRow） ──

function EscRow({
  esc,
  sig,
  onClick,
  style,
}: {
  esc: ChainEscalationItem;
  /** 同签名配额条目（联查上限；缺省 null 上限显「—」不伪 0） */
  sig: ChainSignatureQuota | null;
  onClick: () => void;
  style?: CSSProperties;
}) {
  // 链痕计数（chain_context 终点时刻配额快照；链外记录缺 chain 显「—」）
  const usedAdmin = esc.chain?.admin_attempts_used;
  const usedArb = esc.chain?.arbiter_rulings;
  // 自动执行徽标与 grace 倒计时（add-adjudication-auto-exec 5.2）：徽标
  // 独立于「已收口」（表达执行者是策略引擎，非静默混入人工闭环）；倒计时
  // 仅满足条件的 pending 告警渲染（推荐明确 + 可逆档）
  const autoBadge = autoExecBadge(esc);
  const countdown = autoExecCountdown(esc);
  return (
    <div
      onClick={onClick}
      style={{ padding: '10px 14px', borderBottom: `1px solid ${T.hair}`, cursor: 'pointer', ...style }}
      onMouseEnter={(e) => (e.currentTarget.style.background = T.hover)}
      onMouseLeave={(e) => (e.currentTarget.style.background = '')}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {sevTag(esc.severity)}
        <span className="ov-mono" style={{ fontSize: 13, fontWeight: 600 }}>{esc.signal_type || '—'}</span>
        <span style={{ fontSize: 12, color: T.text3 }}>
          {esc.spec || '(主体键/类型级)'} · {esc.project || '—'}
        </span>
        {esc.chain?.endpoint_kind && (
          <Tag style={{ ...tagSm, marginInlineEnd: 0 }}>{ENDPOINT_META[esc.chain.endpoint_kind] || esc.chain.endpoint_kind}</Tag>
        )}
        {esc.handled ? (
          <Tag style={{ ...tagSm, marginInlineEnd: 0 }} color="green">已收口</Tag>
        ) : (
          <Tag style={{ ...tagSm, marginInlineEnd: 0 }} color="volcano">待人工</Tag>
        )}
        {autoBadge && (
          <Tag style={{ ...tagSm, marginInlineEnd: 0 }} color={autoBadge.color}>{autoBadge.label}</Tag>
        )}
        {countdown && (
          <Tag style={{ ...tagSm, marginInlineEnd: 0 }} color={countdown.done ? 'gold' : 'geekblue'}>
            {countdown.text}
          </Tag>
        )}
        <span className="ov-ellipsis" style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: T.text3, fontVariantNumeric: 'tabular-nums' }}>
          {fmtDate(esc.created, { withYear: false })}
        </span>
      </div>
      <div
        style={{
          marginTop: 5,
          color: T.text,
          fontSize: 13,
          lineHeight: '20px',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        }}
      >
        {esc.description || '—'}
      </div>
      <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', fontSize: 12, color: T.text3, fontVariantNumeric: 'tabular-nums' }}>
        <span>
          Admin {usedAdmin ?? '—'}/{sig?.admin_cap ?? '—'} → Arbiter {usedArb ?? '—'}/{sig?.arbiter_cap ?? '—'}
        </span>
        {(esc.choices?.length ?? 0) > 0 && <span>裁决选项 {esc.choices!.length}</span>}
        {esc.chain?.chain_id && <span className="ov-mono">{esc.chain.chain_id.slice(0, 22)}…</span>}
      </div>
    </div>
  );
}

/** 上升件详情抽屉（640px 只读预览，原型 EscDrawer）：描述/证据/链痕
 * Timeline/建议处置/裁决选项只读 + 只读纪律提示；抽屉零执行按钮 */
function EscDetailDrawer({
  esc,
  sig,
  onClose,
}: {
  esc: ChainEscalationItem | null;
  sig: ChainSignatureQuota | null;
  onClose: () => void;
}) {
  const isMobile = useIsMobile();
  const steps: { color: string; children: ReactNode }[] = [];
  if (esc) {
    steps.push({
      color: 'gray',
      children: (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600 }}>入链</div>
          <div className="ov-mono" style={{ fontSize: 11, color: T.text3 }}>{esc.chain?.chain_id || '—'}</div>
          <div style={{ fontSize: 12, color: T.text3 }}>
            签名 {esc.chain?.signature || '—'} · {fmtDate(esc.created, { withYear: false })}
          </div>
        </div>
      ),
    });
    steps.push({
      color: 'blue',
      children: (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600 }}>
            Admin 处置 {esc.chain?.admin_attempts_used ?? '—'}/{sig?.admin_cap ?? '—'}
          </div>
          {esc.chain?.handoff_reason && (
            <div style={{ color: T.text2, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {esc.chain.handoff_reason}
            </div>
          )}
        </div>
      ),
    });
    steps.push({
      color: 'purple',
      children: (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600 }}>
            Arbiter 裁决 {esc.chain?.arbiter_rulings ?? '—'}/{sig?.arbiter_cap ?? '—'}
          </div>
          {esc.chain?.arbiter_run_id && (
            <div className="ov-mono" style={{ fontSize: 11, color: T.text3 }}>run {esc.chain.arbiter_run_id}</div>
          )}
        </div>
      ),
    });
    steps.push({
      color: esc.handled ? 'green' : 'red',
      children: (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600 }}>{esc.handled ? '终点 · 已收口' : '终点 · 待人工'}</div>
          <div style={{ fontSize: 12, color: T.text3 }}>
            {(esc.chain?.endpoint_kind ? ENDPOINT_META[esc.chain.endpoint_kind] || esc.chain.endpoint_kind : '—')
              + (esc.handled ? ` · ${fmtDate(esc.handled_at, { withYear: false })}` : '')
              + (esc.handled && esc.close_cause ? ` · ${esc.close_cause}` : '')}
          </div>
          {esc.chain?.endpoint_reason && (
            <div style={{ color: T.text2, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {esc.chain.endpoint_reason}
            </div>
          )}
        </div>
      ),
    });
  }
  return (
    <Drawer
      open={!!esc}
      onClose={onClose}
      width={isMobile ? '100%' : 640}
      destroyOnHidden
      title={
        esc && (
          <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
            {sevTag(esc.severity)}
            <span className="ov-mono" style={{ fontSize: 14 }}>{esc.signal_type || '—'}</span>
          </span>
        )
      }
    >
      {esc && (
        <div>
          <div style={{ fontSize: 12, color: T.text3 }}>
            {esc.spec || '(主体键/类型级)'} · {esc.project || '—'} · {fmtDate(esc.created, { withYear: false })}
            {esc.handled ? ` → ${fmtDate(esc.handled_at, { withYear: false })}` : ''}
          </div>
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: T.text3, marginBottom: 6 }}>描述</div>
            <div style={{ fontSize: 13, lineHeight: '21px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {esc.description || '—'}
            </div>
          </div>
          {esc.evidence && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: T.text3, marginBottom: 6 }}>证据</div>
              <div
                className="ov-mono"
                style={{
                  background: T.soft,
                  border: `1px solid ${T.hair}`,
                  borderRadius: 8,
                  padding: '10px 12px',
                  fontSize: 12,
                  lineHeight: '19px',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  color: T.text2,
                }}
              >
                {esc.evidence}
              </div>
            </div>
          )}
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: T.text3, marginBottom: 6 }}>链痕</div>
            <Timeline items={steps} />
          </div>
          {esc.recommended_action && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: T.text3, marginBottom: 6 }}>建议处置</div>
              <div style={{ fontSize: 13, lineHeight: '21px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {esc.recommended_action}
              </div>
            </div>
          )}
          {(esc.choices?.length ?? 0) > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: T.text3, marginBottom: 6 }}>
                裁决选项（{esc.choices!.length} · 只读预览）
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {esc.choices!.map((c: AlertChoice, i: number) => (
                  <div
                    key={c.id || i}
                    style={{
                      border: `1px solid ${c.destructive ? T.err : '#eef2f7'}`,
                      borderRadius: 8,
                      padding: '6px 10px',
                      maxWidth: '100%',
                    }}
                  >
                    <div style={{ fontSize: 12, fontWeight: 600, color: c.destructive ? T.err : T.text }}>{c.label}</div>
                    {c.desc && <div style={{ fontSize: 11, color: T.text3, marginTop: 2 }}>{c.desc}</div>}
                  </div>
                ))}
              </div>
            </div>
          )}
          <div
            style={{
              marginTop: 12,
              padding: '8px 12px',
              background: T.soft,
              borderRadius: 8,
              fontSize: 12,
              color: T.text2,
            }}
          >
            处置链视图保持只读：裁决执行入口收敛于「人工队列」与「告警记录」页签。
          </div>
        </div>
      )}
    </Drawer>
  );
}

// ── 人工队列行（EscRow + 内嵌裁决面板，round3 面板式三段布局） ──

function QueueRow({
  esc,
  sig,
  first,
  onOpen,
  onRefresh,
}: {
  esc: ChainEscalationItem;
  sig: ChainSignatureQuota | null;
  first: boolean;
  onOpen: () => void;
  onRefresh: () => void;
}) {
  // 每行独立裁决实例（MobileAlertRow 同款惯例）：hook 状态按告警 id 分键，
  // 行卡生命周期内互不串扰；执行成功经 onRefresh 重拉队列（该项移除）
  const adj = useAlertAdjudication();
  const { message } = AntdApp.useApp();
  const isMobile = useIsMobile();
  const alert = esc as unknown as AlertItem;
  const selChoiceId = adj.alertChoiceSels[esc.id] || '';
  const selChoice = (esc.choices || []).find((c) => c.id === selChoiceId);
  const msg = adj.alertResolveMsgs[esc.id];
  // 消息色调映射（嵌套三元展开为 if/else：项目清单禁嵌套三元，
  // code-review item 97ea9c6cbb9c）
  let msgColor: string | undefined = undefined;
  if (msg?.tone === 'error') {
    msgColor = T.err;
  } else if (msg?.tone === 'warning') {
    msgColor = T.warn;
  } else if (msg) {
    msgColor = T.text3;
  }
  const hasChoices = (esc.choices?.length ?? 0) > 0;

  // 标记已处理防重（code-review item 4207183c0835）：state 是本次渲染快照，
  // 双击间隔小于一帧时两次调用都读到旧值、各自发出重复请求；ref 在请求发出前
  // 同步置位、finally 清除（useAlertAdjudication.handleResolve 的
  // resolvingIdsRef 同款口径），state 仅驱动按钮 loading 视图
  const handledInFlightRef = useRef(false);
  const [handlingHandled, setHandlingHandled] = useState(false);

  const handleMarkHandled = async () => {
    if (handledInFlightRef.current) return;
    handledInFlightRef.current = true;
    setHandlingHandled(true);
    try {
      await markAlertHandled(esc.project, esc.id);
      message.success('已标记处理');
      onRefresh();
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      handledInFlightRef.current = false;
      setHandlingHandled(false);
    }
  };

  return (
    <div>
      <EscRow esc={esc} sig={sig} onClick={onOpen} />
      <div
        {...(first ? { 'data-proto-id': 'chain-queue-adjudication' } : {})}
        style={{
          margin: '8px 14px 12px 32px',
          background: T.soft,
          border: `1px solid ${T.hair}`,
          borderRadius: 8,
          padding: '10px 12px',
          display: 'flex',
          flexDirection: isMobile ? 'column' : 'row',
          gap: 12,
          alignItems: 'stretch',
        }}
      >
        <div style={isMobile ? undefined : { flex: '0 0 64px', fontSize: 12, fontWeight: 600, color: T.text2, paddingTop: 4 }}>
          人工裁决
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          {hasChoices ? (
            <>
              <Select
                size="small"
                style={{ width: '100%' }}
                placeholder="选择裁决项"
                value={selChoiceId || undefined}
                onChange={(v: string) => adj.setAlertChoiceSels((m) => ({ ...m, [esc.id]: v }))}
                options={(esc.choices || []).map((c) => ({ value: c.id, label: c.label, title: c.desc }))}
              />
              <Input
                size="small"
                style={{ width: '100%', marginTop: 6 }}
                maxLength={200}
                placeholder="处置依据（可选）"
                value={adj.alertNotes[esc.id] || ''}
                onChange={(e) => adj.setAlertNotes((m) => ({ ...m, [esc.id]: e.target.value }))}
              />
              {selChoice?.desc && (
                <div style={{ fontSize: 12, color: T.text3, marginTop: 5 }}>{selChoice.desc}</div>
              )}
            </>
          ) : (
            <div style={{ fontSize: 12, color: T.text4 }}>该告警无裁决选项</div>
          )}
          {msg && (
            <div style={{ fontSize: 12, color: msgColor, marginTop: 5 }}>{msg.text}</div>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 88 }}>
          {hasChoices && <AlertAdjudicationExec alert={alert} adj={adj} onResolved={onRefresh} />}
          <Button size="small" loading={handlingHandled} disabled={handlingHandled} onClick={() => void handleMarkHandled()}>
            标记已处理
          </Button>
        </div>
      </div>
    </div>
  );
}

// spec 分组（redesign-chain-panel-ui 3.1）：签名按「项目+主体键」归组，
// 组序待人工数→上升数→last_seen 降序（待人工优先）
interface QuotaGroup {
  key: string;
  label: string;
  project: string;
  lastSpecStatus: string;
  sigs: ChainSignatureQuota[];
  escTotal: number;
  escPending: number;
  lastSeen: string;
}

function buildQuotaGroups(sigs: ChainSignatureQuota[]): QuotaGroup[] {
  const map = new Map<string, QuotaGroup>();
  for (const s of sigs) {
    const label = subjectLabel(s);
    const project = s.project || '—';
    const key = `${project}::${label}`;
    let g = map.get(key);
    if (!g) {
      g = { key, label, project, lastSpecStatus: '', sigs: [], escTotal: 0, escPending: 0, lastSeen: '' };
      map.set(key, g);
    }
    g.sigs.push(s);
    g.escTotal += s.esc_total;
    g.escPending += s.esc_pending;
    if ((s.last_seen || '') > g.lastSeen) {
      g.lastSeen = s.last_seen || '';
      g.lastSpecStatus = s.last_spec_status || '';
    }
  }
  return [...map.values()].sort(
    (a, b) =>
      b.escPending - a.escPending ||
      b.escTotal - a.escTotal ||
      (b.lastSeen || '').localeCompare(a.lastSeen || ''),
  );
}

export default function ChainPanel({
  project,
}: {
  /** 单项目聚合筛选（宿主页持有并同步到标题栏 Select，undefined=全部项目） */
  project?: string;
}) {
  const isMobile = useIsMobile();
  const { message } = AntdApp.useApp();
  const [data, setData] = useState<ChainOverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // fix 43351def1296: load 自增请求序号——project 变化时 useEffect 重建轮询，
  // 旧项目的在飞请求可能晚于新项目响应落地，过期响应直接丢弃不落状态，
  // 防旧项目链在办/配额/上升件覆盖当前筛选（activities 页 loadSeqRef 同款口径）
  const loadSeqRef = useRef(0);

  const load = useCallback(async (name?: string) => {
    const seq = ++loadSeqRef.current;
    try {
      const view = await getChainOverview(name);
      if (seq !== loadSeqRef.current) return;
      // fix 6fe630a044a7: 服务端对 ?project 指向不存在/未就绪项目返回**有意 200**
      // 错误体 {"error": "project not found"}（alert_routes.py _api_chain 契约、
      // ChainOverviewData.error 注释均声明「调用方按 error 分支」）——直接落盘会
      // 渲染成全「—」统计格与空态文案，误导用户以为链上确无数据。走既有错误
      // 横幅（「处置链刷新失败：」前缀）透出并保留上一帧数据（catch 分支同款
      // fail-soft），不清屏
      if (view.error) {
        setError(view.error);
        return;
      }
      setData(view);
      setError('');
    } catch (err) {
      // 观测面 fail-soft（command-center useScreen 同款口径）：刷新失败保留
      // 上一帧数据仅置 error，由页首内联 Alert 透出，不静默吞掉
      // 过期请求的失败同样不落状态，防旧项目错误横幅盖掉新项目数据
      if (seq !== loadSeqRef.current) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      // fix 6e3faa904945: 收尾置 false 同样纳入序号守卫（activities/index.tsx
      // fix 9fc948945fc7 同款口径）——旧请求不得抢在并发新请求之前撤加载指示
      if (seq === loadSeqRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    // fix 6e3faa904945: project 切换重建轮询时置加载反馈——重拉期间 Spin 转、
    // 旧项目数据不再持续可见（序号守卫只保证不落盘，不保证视觉中性）。
    // 30s 轮询重拉不置 true，防周期性闪烁；挂载时与初始 state true 重复赋值
    // 由 React 同值 bailout 吸收
    setLoading(true);
    load(project);
    const timer = setInterval(() => load(project), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load, project]);

  const inFlight = useMemo(() => data?.in_flight || [], [data]);
  const signatures = useMemo(() => data?.signatures || [], [data]);
  const escalations = useMemo(() => data?.escalations || [], [data]);
  const queue = useMemo(() => data?.queue || [], [data]);

  // 签名配额索引：EscRow/抽屉按「项目::签名」联查上限（退化按裸签名）
  const sigIdx = useMemo(() => {
    const m = new Map<string, ChainSignatureQuota>();
    for (const s of signatures) {
      m.set(s.signature, s);
      if (s.project) m.set(`${s.project}::${s.signature}`, s);
    }
    return m;
  }, [signatures]);
  const sigFor = useCallback(
    (esc: ChainEscalationItem) =>
      sigIdx.get(`${esc.project || ''}::${esc.chain?.signature || ''}`) ||
      sigIdx.get(esc.chain?.signature || '') ||
      null,
    [sigIdx],
  );

  const groups = useMemo(() => buildQuotaGroups(signatures), [signatures]);

  // 分段筛选（5.1）：全部/待人工/已收口（含计数，Radio.Group button 深色激活）
  const [escFilter, setEscFilter] = useState<'all' | 'pending' | 'closed'>('all');
  // 分段谓词（嵌套三元展开为 if/else：项目清单禁嵌套三元，code-review item 97ea9c6cbb9c）
  const escShown = useMemo(() => {
    return escalations.filter((e) => {
      if (escFilter === 'all') return true;
      if (escFilter === 'pending') return !e.handled;
      return !!e.handled;
    });
  }, [escalations, escFilter]);

  const [selEsc, setSelEsc] = useState<ChainEscalationItem | null>(null);
  const [selRun, setSelRun] = useState<{ project: string; spec?: string; runId: string } | null>(null);

  /** 该签名最近上升件（待人工优先，否则 created 最新——3.3 下钻/2.2 降级共用） */
  const pickLatestEsc = useCallback(
    (signature: string, sourceProject?: string) => {
      const cands = escalations.filter(
        (e) => e.chain?.signature === signature && (!sourceProject || !e.project || e.project === sourceProject),
      );
      if (!cands.length) return null;
      const pendingCands = cands.filter((e) => !e.handled);
      const pool = pendingCands.length ? pendingCands : cands;
      return [...pool].sort((a, b) => (b.created || '').localeCompare(a.created || ''))[0];
    },
    [escalations],
  );

  // 3.3 信号名下钻：打开该签名最近上升件详情抽屉
  const openSig = useCallback(
    (s: ChainSignatureQuota) => {
      const found = pickLatestEsc(s.signature, s.project);
      if (found) setSelEsc(found);
    },
    [pickLatestEsc],
  );

  // 2.2 在办行点击：run_id 可得 → AdminRunModal（80vw/72vh 流式转录窗）；
  // 否则降级打开该签名最近上升件的详情抽屉（复用 5.2）；双不可得如实提示
  const openRunView = useCallback(
    (it: ChainInFlightItem) => {
      if (it.run_id && it.project) {
        setSelRun({ project: it.project, spec: it.spec || undefined, runId: it.run_id });
        return;
      }
      const found = it.signature ? pickLatestEsc(it.signature, it.project) : null;
      if (found) {
        setSelEsc(found);
        return;
      }
      message.info('该在办件暂无 run 记录与链上上升件，处置过程不可回放');
    },
    [pickLatestEsc, message],
  );

  // 统计行派生指标（6.1，前端算——escalations/signatures 同请求下发无双源）
  const stats = useMemo(() => {
    const inflAdm = inFlight.filter((i) => i.phase === 'admin').length;
    const inflArb = inFlight.filter((i) => i.phase === 'arbiter').length;
    const queueMajor = queue.filter((e) => e.severity === 'major' || e.severity === 'critical').length;
    const nowMs = Date.now();
    const within24 = escalations.filter(
      (e) => e.created && Number.isFinite(new Date(e.created).getTime()) && nowMs - new Date(e.created).getTime() <= 24 * 3600 * 1000,
    ).length;
    const sigsN = signatures.length;
    const linkedSigs = signatures.filter((s) => s.esc_total > 0);
    const linked = linkedSigs.length;
    const linkedPending = linkedSigs.reduce((n, s) => n + s.esc_pending, 0);
    const adminFull = signatures.filter((s) => s.admin_cap > 0 && s.admin_attempts >= s.admin_cap).length;
    const arbFull = signatures.filter((s) => s.arbiter_cap > 0 && s.arbiter_rulings >= s.arbiter_cap).length;
    // null 指标占位口径（数据未到显「—」，0 与「口径不可得」语义不同）
    const v = (n: number) => (data ? String(n) : '—');
    return [
      { label: '链在办', value: v(inFlight.length), sub: `Admin ${inflAdm} · Arbiter ${inflArb}` },
      { label: '待人工', value: v(queue.length), sub: queueMajor > 0 ? `major+${queueMajor}` : '无 major+' },
      { label: '上升件', value: v(escalations.length), sub: `近 24h ${within24}` },
      { label: '签名水位', value: v(sigsN), sub: `顶格 Admin ${adminFull} · Arbiter ${arbFull}` },
      {
        label: '签名关联上升',
        value: v(linked),
        sub: `占水位 ${sigsN ? Math.round((linked * 100) / sigsN) : 0}% · 待 ${linkedPending}`,
      },
    ];
  }, [data, inFlight, queue, escalations, signatures]);

  const cardHd = { display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px', borderBottom: `1px solid ${T.hair}` } as const;

  return (
    <>
      <Spin spinning={loading}>
        {/* 刷新失败保留旧数据 + 内联 Alert（command-center 各屏同款形态） */}
        {error ? (
          <Alert style={{ marginBottom: 12 }} type="warning" showIcon message={`处置链刷新失败：${error}`} />
        ) : null}

        {/* 统计行（5 磁贴，bento） */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? 'repeat(2, 1fr)' : 'repeat(5, 1fr)',
            gap: 12,
            marginBottom: 12,
          }}
        >
          {stats.map((s) => (
            <div key={s.label} className="ov-bento" style={{ padding: '14px 16px' }}>
              <div style={{ fontSize: 12, color: T.text3 }}>{s.label}</div>
              <div className="ov-num" style={{ fontSize: 28, fontWeight: 600, lineHeight: '40px' }}>
                {s.value}
              </div>
              <div className="ov-num" style={{ fontSize: 11, color: T.text4 }}>
                {s.sub}
              </div>
            </div>
          ))}
        </div>

        {/* 人工队列（置首；无待人工件整卡不渲染——round1 批注） */}
        {queue.length > 0 && (
          <div className="ov-bento" style={{ marginBottom: 12 }}>
            <div style={cardHd}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>人工队列（{queue.length}）</div>
              <span className="ov-ellipsis" style={{ flex: 1 }} />
              <div style={{ fontSize: 12, color: T.text3 }}>裁决入口内嵌 · 复用「告警记录」同款交互</div>
            </div>
            <div>
              {queue.map((e, i) => (
                <QueueRow
                  key={e.id}
                  esc={e}
                  sig={sigFor(e)}
                  first={i === 0}
                  onOpen={() => setSelEsc(e)}
                  onRefresh={() => void load(project)}
                />
              ))}
            </div>
          </div>
        )}

        {/* 链在办（行卡：标识行→2 行 clamp 描述→静态链进度→mono 元信息行） */}
        <div className="ov-bento" style={{ marginBottom: 12 }}>
          <div style={cardHd}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>链在办（{inFlight.length}）</div>
            <span className="ov-ellipsis" style={{ flex: 1 }} />
            <div style={{ fontSize: 12, color: T.text3 }}>30s 自动刷新 · 点行看处置过程</div>
          </div>
          <div style={{ padding: '4px 16px 10px' }}>
            {inFlight.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前无在办处置链" />
            ) : (
              inFlight.map((it, i) => {
                // 签名后缀同上升件单元格口径：取 '::' 后全部剩余分段（code-review item 791ef5b2cb55）
                const sigTail = (it.signature || '').split('::').slice(1).join('::');
                return (
                  <div
                    key={it.chain_id || it.signature || `in-flight-${i}`}
                    onClick={() => openRunView(it)}
                    onMouseEnter={(e) => (e.currentTarget.style.background = T.hover)}
                    onMouseLeave={(e) => (e.currentTarget.style.background = '')}
                    style={{
                      padding: '12px 0',
                      cursor: 'pointer',
                      ...(i < inFlight.length - 1 ? { borderBottom: `1px solid ${T.hair}` } : {}),
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <Tag style={{ ...tagSm, marginInlineEnd: 0 }} color={it.phase === 'admin' ? 'blue' : 'purple'}>
                        {PHASE_META[it.phase]?.label || it.phase || '—'}
                      </Tag>
                      <span style={{ fontSize: 13, fontWeight: 600 }}>{it.spec || '(主体键/类型级)'}</span>
                      {sigTail && (
                        <span className="ov-mono" style={{ fontSize: 12, color: T.text3 }}>::{sigTail}</span>
                      )}
                      <span className="ov-ellipsis" style={{ flex: 1 }} />
                      <span style={{ fontSize: 12, color: T.text3, fontVariantNumeric: 'tabular-nums' }}>
                        已耗时 {fmtDur(elapsedMin(it.started_at))}
                      </span>
                    </div>
                    <div
                      style={{
                        marginTop: 6,
                        lineHeight: '20px',
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}
                    >
                      {it.problem || '—'}
                    </div>
                    <div style={{ marginTop: 8 }}>
                      <InFlightStepper it={it} />
                    </div>
                    <div
                      className="ov-mono"
                      style={{ marginTop: 8, fontSize: 11, color: T.text4, display: 'flex', gap: 14, flexWrap: 'wrap' }}
                    >
                      <span>run {it.run_id || '—'}</span>
                      <span>入链 {fmtDate(it.started_at, { withYear: false })}</span>
                      <span>{it.chain_id || '—'}</span>
                      <span className="ov-ellipsis" style={{ flex: 1 }} />
                      <span style={{ color: T.link }}>处置过程 ›</span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* 签名配额与上升（按 spec 分组 + 配额双芯片 + 链上结果标签） */}
        <div className="ov-bento" style={{ marginBottom: 12 }}>
          <div style={cardHd}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>
              签名配额与上升（{signatures.length}）
            </div>
            <span className="ov-ellipsis" style={{ flex: 1 }} />
            <div style={{ fontSize: 12, color: T.text3 }}>按 spec 分组 · 待人工优先排序</div>
          </div>
          <div style={{ padding: '4px 16px 10px' }}>
            {!isMobile && (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'minmax(0,1fr) 260px minmax(0,1.2fr) 120px',
                  gap: 12,
                  padding: '8px 12px 2px',
                  borderBottom: `1px solid ${T.hair}`,
                }}
              >
                {['信号签名', '配额水位', '链上结果'].map((h) => (
                  <span key={h} style={{ fontSize: 11, color: T.text3 }}>{h}</span>
                ))}
                <span style={{ fontSize: 11, color: T.text3, textAlign: 'right' }}>最近出现</span>
              </div>
            )}
            {groups.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无签名记录" />
            ) : (
              groups.map((g) => (
                <div key={g.key}>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      flexWrap: 'wrap',
                      background: T.soft,
                      borderRadius: 8,
                      padding: '7px 12px',
                      margin: '10px 0 2px',
                    }}
                  >
                    <span className="ov-mono" style={{ fontSize: 13, fontWeight: 600 }}>{g.label}</span>
                    <Tag style={{ ...tagSm, marginInlineEnd: 0 }}>{g.project}</Tag>
                    {g.lastSpecStatus && <Tag style={{ ...tagSm, marginInlineEnd: 0 }}>{g.lastSpecStatus}</Tag>}
                    <span className="ov-ellipsis" style={{ flex: 1 }} />
                    <span style={{ fontSize: 12, color: T.text3, fontVariantNumeric: 'tabular-nums' }}>
                      {g.sigs.length} 签名 · ↑{g.escTotal}
                      {g.escPending > 0 ? ` · 待 ${g.escPending}` : ''}
                    </span>
                  </div>
                  {g.sigs.map((s) => (
                    <div
                      key={s.signature}
                      style={
                        isMobile
                          ? { display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 12px', borderBottom: `1px solid ${T.hair}` }
                          : {
                              display: 'grid',
                              gridTemplateColumns: 'minmax(0,1fr) 260px minmax(0,1.2fr) 120px',
                              gap: 12,
                              alignItems: 'center',
                              padding: '8px 12px',
                              borderBottom: `1px solid ${T.hair}`,
                            }
                      }
                    >
                      {/* 3.3 有上升件信号名可点击下钻（详情抽屉）；无上升件纯展示。
                          单元格显信号名（签名 `::` 后缀；subject/type 签名首段
                          带主体键限定同取后缀），完整签名挂 title 悬停可见 */}
                      {(() => {
                        const sigName = s.signature.split('::').slice(1).join('::') || s.signature;
                        return s.esc_total > 0 ? (
                          <span
                            className="ov-mono ov-siglink ov-ellipsis"
                            style={{ fontSize: 12 }}
                            title={`${s.signature}（查看处置过程）`}
                            onClick={(e) => {
                              e.stopPropagation();
                              openSig(s);
                            }}
                          >
                            {sigName}
                          </span>
                        ) : (
                          <span className="ov-mono ov-ellipsis" style={{ fontSize: 12 }} title={s.signature}>
                            {sigName}
                          </span>
                        );
                      })()}
                      <span style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                        <QuotaChip label="Admin" used={s.admin_attempts} cap={s.admin_cap} exhausted={s.exhausted} />
                        <QuotaChip label="Arb" used={s.arbiter_rulings} cap={s.arbiter_cap} exhausted={s.exhausted} />
                        {s.granularity !== 'spec' && (
                          <Tag style={{ fontSize: 10, lineHeight: '16px', padding: '0 5px', marginInlineEnd: 0 }}>
                            {s.granularity === 'type' ? '类型级' : '主体级'}
                          </Tag>
                        )}
                      </span>
                      <span style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>{outcomeChips(s)}</span>
                      <span
                        style={{ fontSize: 12, color: T.text3, fontVariantNumeric: 'tabular-nums', textAlign: 'right' }}
                        title={s.last_seen}
                      >
                        {fmtDate(s.last_seen, { withYear: false })}
                      </span>
                    </div>
                  ))}
                </div>
              ))
            )}
          </div>
        </div>

        {/* 上升件全量（行卡 + 分段筛选 Radio.Group 深色激活） */}
        <div className="ov-bento" style={{ marginBottom: 12 }}>
          <div style={cardHd}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>上升件全量（{escalations.length}）</div>
            <span className="ov-ellipsis" style={{ flex: 1 }} />
            <Radio.Group
              size="small"
              value={escFilter}
              onChange={(e) => setEscFilter(e.target.value as 'all' | 'pending' | 'closed')}
              optionType="button"
              className="ov-radio-dark"
              options={[
                { value: 'all', label: `全部 ${escalations.length}` },
                { value: 'pending', label: `待人工 ${queue.length}` },
                { value: 'closed', label: `已收口 ${escalations.length - queue.length}` },
              ]}
            />
          </div>
          <div>
            {escShown.length === 0 ? (
              <div style={{ padding: '18px 16px' }}>
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无匹配上升件" />
              </div>
            ) : (
              escShown.map((e) => (
                <EscRow key={e.id} esc={e} sig={sigFor(e)} onClick={() => setSelEsc(e)} />
              ))
            )}
          </div>
        </div>
      </Spin>

      {/* 详情抽屉（5.2 只读预览）与在办处置过程窗（2.2 AdminRunModal 复用） */}
      <EscDetailDrawer esc={selEsc} sig={selEsc ? sigFor(selEsc) : null} onClose={() => setSelEsc(null)} />
      <AdminRunModal
        project={selRun?.project || ''}
        spec={selRun?.spec}
        adminRunId={selRun?.runId || ''}
        open={!!selRun}
        onClose={() => setSelRun(null)}
      />
    </>
  );
}
