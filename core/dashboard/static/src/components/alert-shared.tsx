import dayjs from 'dayjs';
import { Space, Tag, Typography } from 'antd';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { AlertItem } from '@/services/dashboard';
import { markdownComponents } from '@/pages/projects/components/SpecDocModal';
import { fmtEvidence } from '@/utils/evidence';

/**
 * 告警展示单源（code-review item 5478d16d70c7）：SEV 常量、告警标题、明细字段
 * 与时间格式化此前在 overview/AlertBanner 与 pages/activities 各写一份且已漂移
 * （SEV_COLOR 缺 warning 键、fmtDate 空值占位一处 '' 一处 '—'），收敛到本模块。
 * 两个 surface 的历史布局差异经 variant 参数保留，不改任一页现有视觉行为：
 * - 'banner'（overview 横幅）：spec 以 📌 前缀并入明细首行、时间省年份；
 * - 'page'（activities 页）：标题带 spec 蓝标签、明细字段分行、完整年月日。
 */
export type AlertSurfaceVariant = 'banner' | 'page';

/** 严重度 → 中文标签（info 供后端 info 级信号，如 code_fix_wip_gate_deferred） */
export const SEV_LABEL: Record<string, string> = { critical: '严重', major: '较高', warning: '警告', minor: '一般', info: '提示' };

/** 严重度 → antd Tag 配色（取两份历史实现的超集，补齐横幅侧缺失的 warning 键；info 用 default 灰最弱档） */
export const SEV_COLOR: Record<string, string> = { critical: 'red', major: 'orange', warning: 'gold', minor: 'blue', info: 'default' };

/**
 * 时间格式化。空值统一占位 '—'（此前漂移：横幅 ''、activities '—'）；
 * withYear=false 供横幅窄空间用 MM-DD 起头（历史布局差异，经参数保留）。
 */
export function fmtDate(v?: string, { withYear = true }: { withYear?: boolean } = {}) {
  if (!v) return '—';
  const d = dayjs(v);
  return d.isValid() ? d.format(withYear ? 'YYYY-MM-DD HH:mm:ss' : 'MM-DD HH:mm:ss') : v;
}

/** 告警标题：SEV 标签 +（已解决时）解决方式 + 项目 +（page 变体）spec + 时间 */
export function AlertTitle({
  item,
  resolved,
  variant,
}: {
  item: AlertItem;
  resolved?: boolean;
  variant: AlertSurfaceVariant;
}) {
  const isPage = variant === 'page';
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
      {isPage && item.spec ? <Tag style={{ marginInlineEnd: 0 }} color="blue">{item.spec}</Tag> : null}
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {fmtDate(resolved ? item.handled_at || item.created : item.created, { withYear: !isPage })}
      </Typography.Text>
    </Space>
  );
}

/**
 * 三段式叙事区块（add-adjudication-alert-narrative 4.1）：在证据之前渲染
 * narrative.text（Markdown、默认展开），标注「建议倾向仅供参考」。
 * - 纯展示、不可交互（叙事仅为可读性增强，不承载任何机器语义）；
 * - 无 narrative 字段时不渲染任何容器（DOM 与现状一致，无空壳区块）；
 * - 长文本按既有容器规则滚动展示（maxHeight + overflowY auto），不横向溢出、
 *   不遮挡 choices 操作区。
 */
function AlertNarrative({ text }: { text: string }) {
  return (
    <div data-testid="alert-narrative" style={{ margin: '4px 0' }}>
      <div
        style={{
          maxHeight: 320,
          overflowY: 'auto',
          border: '1px solid #f0f0f0',
          borderRadius: 6,
          padding: '6px 8px',
          background: '#fafafa',
          fontSize: 12,
        }}
      >
        <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
          {text}
        </Markdown>
      </div>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        以上叙事由 AI 生成，建议倾向仅供参考，最终由你决定。
      </Typography.Text>
    </div>
  );
}

/**
 * 告警明细字段区（描述/叙事/证据/处置/建议/解决依据），六段行单源只写一份，
 * 布局差异按 variant 保留、isPage 仅在真实差异点分支（两变体渲染输出逐字等价）：
 * - 描述行：page 有描述才独占一行渲染，banner 恒渲染并入 📌 spec 前缀；
 * - 证据行：page 外包一层 div，banner 直接内联；
 * - 处置/建议：page 文案在 Typography 外作同级文本节点，banner 并入 Typography 内。
 */
export function AlertLines({ item, variant }: { item: AlertItem; variant: AlertSurfaceVariant }) {
  const isPage = variant === 'page';
  const evidenceText = fmtEvidence(item.evidence);
  const resolveNote = item.resolve_note ? (
    <div>
      <Typography.Text type="secondary">解决依据：{item.resolve_note}</Typography.Text>
    </div>
  ) : null;
  const descriptionLine = isPage ? (
    item.description ? (
      <div>{item.description}</div>
    ) : null
  ) : (
    <div>{item.spec ? `📌 ${item.spec} ` : ''}{item.description}</div>
  );
  const evidenceLine = evidenceText ? (
    <Typography.Text type="secondary">证据：{evidenceText}</Typography.Text>
  ) : null;
  return (
    // pre-wrap 保留字段内的 \n / \t 格式（JSON 存储层未丢失，HTML 默认会折叠成空格）
    <div style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
      {descriptionLine}
      {item.narrative?.text ? <AlertNarrative text={item.narrative.text} /> : null}
      {isPage ? (evidenceLine ? <div>{evidenceLine}</div> : null) : evidenceLine}
      {item.action_taken ? (
        <div>
          <Typography.Text type="secondary">处置：{!isPage && item.action_taken}</Typography.Text>
          {isPage && item.action_taken}
        </div>
      ) : null}
      {item.recommended_action ? (
        <div>
          <Typography.Text type="secondary">建议：{!isPage && item.recommended_action}</Typography.Text>
          {isPage && item.recommended_action}
        </div>
      ) : null}
      {resolveNote}
    </div>
  );
}
