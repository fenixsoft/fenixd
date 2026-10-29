// PipelineBoard.tsx — 指挥中心「交付流水线」屏（add-command-center 4.2）。
//
// 五列泳道（drafted/ready/implementing/verifying/pushed，后端单点桶映射）
// + 项目筛选（2026-10-28 上移壳层页签右侧全局下拉，本屏经 props 接收）；
// implementing 卡存在在飞 run 时渲染 running lane 与开始时间；卡片点击跳
// 既有 SPEC 详情页 /projects/:name/:spec。
//
// 2026-10-28 用户定稿：定高屏（100vh 减页签区），body 不滚动——滚动条
// 下沉到各赛道内部，哪条赛道卡片超高哪条赛道自己出纵向滚动条
// （.cmdcenter-lanescroll，深色蓝系样式单点在 index.tsx 页级 style）。

import { useEffect } from 'react';
import { history } from '@umijs/max';
import { Alert, Tag } from 'antd';
import { commandCenterPipeline } from '@/services/dashboard';
import type { CommandCenterPipeline, CommandCenterPipelineCard } from '@/services/dashboard';
import { useScreenResource } from './useScreen';
import { ScreenErrorPlaceholder, ScreenLoading } from './ScreenStates';
import { BG, PANEL_BORDER, TEXT_MAIN, TEXT_SUB, columnLabel, fmtShortTs } from './shared';

// 原生 SpecStatus 中文标签（列内卡片展示；未知值原样透出）
const STATUS_LABELS: Record<string, string> = {
  drafted: '草稿',
  reviewing: '评审中',
  ready: '就绪',
  implementing: '实现中',
  'bug-found': '有缺陷',
  blocked: '受阻',
  implemented: '已实现',
  testing: '测试中',
  verified: '已验证',
  done: '完成',
  pushed: '已推送',
};

function PipelineCard({
  card,
}: {
  card: CommandCenterPipelineCard;
}) {
  const open = () =>
    history.push(
      `/projects/${encodeURIComponent(card.project)}/${encodeURIComponent(card.spec)}`,
    );
  return (
    <div
      onClick={open}
      style={{
        border: `1px solid ${PANEL_BORDER}`,
        borderRadius: 8,
        padding: '8px 10px',
        background: BG,
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        // flexShrink 0：卡片恒按内容高度渲染，超高由赛道滚动区承接
        flexShrink: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ fontWeight: 600 }}>{card.spec}</span>
        <Tag style={{ marginInlineEnd: 0 }}>{card.project}</Tag>
      </div>
      <div style={{ fontSize: 12, color: TEXT_SUB }}>
        {STATUS_LABELS[card.status] ?? card.status}
      </div>
      {card.running ? (
        <div
          style={{
            fontSize: 12,
            color: '#52c41a',
            borderTop: `1px solid ${PANEL_BORDER}`,
            paddingTop: 6,
          }}
        >
          在飞 · {card.running.lane} · 自 {fmtShortTs(card.running.started_at)}
        </div>
      ) : null}
    </div>
  );
}

export default function PipelineBoard({
  active,
  project,
  onProjects,
}: {
  active: boolean;
  /** 项目筛选：''=全部项目（服务端缺省聚合范围；壳层页签右侧全局下拉注入） */
  project: string;
  /** 项目全集上报（供壳层全局下拉合并），数据变化时回调一次 */
  onProjects?: (projects: string[]) => void;
}) {
  const { data, error, loading, retry } = useScreenResource<CommandCenterPipeline>(
    () => commandCenterPipeline(project || undefined),
    active,
    // 筛选切换即时重拉（project 变化经 refreshKey 触发激活 effect；BUG-01
    // 修复——specs「交付流水线筛选」Scenario：切换后仅剩该项目卡片）
    project,
  );
  // 项目全集上报给壳层（页签右侧全局下拉数据源）
  useEffect(() => {
    if (data?.projects) onProjects?.(data.projects);
  }, [data, onProjects]);
  if (error && !data) return <ScreenErrorPlaceholder error={error} onRetry={retry} />;
  if (!data) return <ScreenLoading hint="交付流水线加载中" />;
  return (
    // 定高屏（与组织总览同款 78px 口径=页面 padding-top 8 + 页签条 70）：
    // 页面 body 不滚动，滚动下沉到各赛道——哪条赛道卡片超高，哪条赛道自己
    // 出纵向滚动条（2026-10-28 用户定稿）
    <div
      style={{
        height: 'calc(100vh - 78px)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {error ? (
        <Alert
          style={{ marginBottom: 12, flexShrink: 0 }}
          type="warning"
          showIcon
          message={`交付流水线刷新失败：${error}`}
        />
      ) : null}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: 'grid',
          gridTemplateColumns: 'repeat(5, minmax(0, 1fr))',
          gap: 12,
        }}
      >
        {data.columns.map((col) => (
          <div
            key={col.key}
            style={{
              border: `1px solid ${PANEL_BORDER}`,
              borderRadius: 8,
              padding: 10,
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
              minHeight: 0,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                color: TEXT_SUB,
                fontSize: 13,
                flexShrink: 0,
              }}
            >
              <span style={{ fontWeight: 600, color: TEXT_MAIN }}>{columnLabel(col.key)}</span>
              <span>{col.cards.length}</span>
            </div>
            {/* 赛道滚动区：卡片列表独立滚动，赛道头/计数恒可见 */}
            <div
              className="cmdcenter-lanescroll"
              style={{
                flex: 1,
                minHeight: 0,
                overflowY: 'auto',
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
              }}
            >
              {col.cards.map((c) => (
                <PipelineCard key={`${c.project}/${c.spec}`} card={c} />
              ))}
              {!col.cards.length ? (
                <div style={{ color: TEXT_SUB, fontSize: 12, textAlign: 'center', padding: '12px 0' }}>
                  暂无
                </div>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
