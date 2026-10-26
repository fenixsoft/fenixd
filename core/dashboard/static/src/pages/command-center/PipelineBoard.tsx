// PipelineBoard.tsx — 指挥中心「交付流水线」屏（add-command-center 4.2）。
//
// 五列泳道（drafted/ready/implementing/verifying/pushed，后端单点桶映射）
// + 项目筛选下拉（数据源=响应 projects 全集 +「全部项目」）；implementing
// 卡存在在飞 run 时渲染 running lane 与开始时间；卡片点击跳既有 SPEC 详情
// 页 /projects/:name/:spec。

import { useState } from 'react';
import { history } from '@umijs/max';
import { Alert, Select, Tag } from 'antd';
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

export default function PipelineBoard({ active }: { active: boolean }) {
  // project='' = 全部项目（服务端缺省聚合范围）
  const [project, setProject] = useState('');
  const { data, error, loading, retry } = useScreenResource<CommandCenterPipeline>(
    () => commandCenterPipeline(project || undefined),
    active,
  );
  if (error && !data) return <ScreenErrorPlaceholder error={error} onRetry={retry} />;
  if (!data) return <ScreenLoading hint="交付流水线加载中" />;
  return (
    <div>
      {error ? (
        <Alert style={{ marginBottom: 12 }} type="warning" showIcon message={`交付流水线刷新失败：${error}`} />
      ) : null}
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        <Select
          value={project}
          onChange={setProject}
          style={{ minWidth: 180 }}
          options={[
            { label: '全部项目', value: '' },
            ...data.projects.map((p) => ({ label: p, value: p })),
          ]}
        />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 12 }}>
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
              minHeight: 160,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', color: TEXT_SUB, fontSize: 13 }}>
              <span style={{ fontWeight: 600, color: TEXT_MAIN }}>{columnLabel(col.key)}</span>
              <span>{col.cards.length}</span>
            </div>
            {col.cards.map((c) => (
              <PipelineCard key={`${c.project}/${c.spec}`} card={c} />
            ))}
            {!col.cards.length ? (
              <div style={{ color: TEXT_SUB, fontSize: 12, textAlign: 'center', padding: '12px 0' }}>
                暂无
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
