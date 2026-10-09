import dayjs from 'dayjs';
import { useState } from 'react';
import type { ReactNode } from 'react';
import { Button, Modal, Space, Tag, Typography } from 'antd';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { AlertItem } from '@/services/dashboard';
import { markdownComponents } from '@/pages/projects/components/SpecDocModal';
import { fmtEvidence } from '@/utils/evidence';
import { MaximizeTitle, useMaximizeModal } from '@/components/useMaximizeModal';

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
        <Tag
          style={{ marginInlineEnd: 0 }}
          color={
            item.handled_by === 'auto-resolve'
              ? 'cyan'
              : item.handled_by === 'auto-self-heal'
                ? 'green'
                : 'geekblue'
          }
        >
          {/* add-alert-self-heal-marking 5.3：auto-self-heal（自愈闭环）独立
              徽标文案，区别于既有 auto-resolve（自动解决） */}
          {item.handled_by === 'auto-resolve'
            ? '🤖 自动解决'
            : item.handled_by === 'auto-self-heal'
              ? '♻️ 已自愈'
              : '👤 人工处理'}
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

/** 该告警是否携带正式调查报告（sidecar model 有值；null=失败/熔断终态机械说明） */
export function hasNarrativeReport(item: AlertItem): boolean {
  return !!(item.narrative?.text && item.narrative.model);
}

/**
 * 告警操作按钮竖排列（查看调查报告 / 执行 / 标记已处理同列）：竖向排布、
 * 按钮随最宽者拉伸等宽（align-items stretch），作为单个元素传入 antd
 * List.Item 的 actions（antd 本身只做横向排布，竖排语义由本容器承载）。
 */
export function AlertActionColumn({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        alignItems: 'stretch',
        minWidth: 88,
      }}
    >
      {children}
    </div>
  );
}

/**
 * 调查报告弹窗入口（原三段式内联叙事区块，add-adjudication-alert-narrative 4.1
 * → 弹窗化改造）：四段式调查报告动辄数千字，内联 320px 小框滚动不利于阅读，
 * 改为「查看调查报告」入口按钮 + 居中 Modal 全文阅读。
 * - 按钮纯文字无图标（与执行/标记已处理同列竖排、等宽，见 AlertActionColumn）；
 * - Modal 默认即视口 80% × 80%（width 80vw / body 高 80vh），可最大化占满
 *   视口、移动端自动全屏（useMaximizeModal 既有模式）；
 * - 纯展示、Modal 内不可交互（报告仅为可读性增强，不承载任何机器语义）；
 * - 安全前提：narrative.text 为 AI 生成内容，无注入风险依赖 react-markdown
 *   默认不执行原始 HTML（跳过 raw HTML 节点、链接经 SafeLink 渲染），且共享
 *   映射 markdownComponents（SpecDocModal）不放行 raw HTML——后者不得引入
 *   rehype-raw，否则静默放开 HTML 注入面；
 * - AI 免责声明移入弹窗底部随全文同读（入口按钮窄空间不重复占位）。
 */
export function AlertReportButton({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const { modalProps, maximizeButton } = useMaximizeModal({
    defaultWidth: '80vw',
    defaultBodyHeight: '80vh',
    centered: true,
    extraBodyStyle: { overflowY: 'auto' },
  });
  return (
    <>
      <Button size="small" onClick={() => setOpen(true)}>
        查看调查报告
      </Button>
      <Modal
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        title={<MaximizeTitle text="调查报告" button={maximizeButton} />}
        {...modalProps}
      >
        <div style={{ fontSize: 13 }}>
          <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {text}
          </Markdown>
        </div>
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 12 }}>
          以上调查报告由 AI 生成，建议倾向仅供参考，最终由你决定。
        </Typography.Text>
      </Modal>
    </>
  );
}

/**
 * 「调查生成中」占位（upgrade-narrative-to-investigation 3.5）：告警已落盘、
 * 后台调查叙事尚在生成（读侧 narrative_pending 标记，侧车缺失且未 handled
 * 的裁决类告警）时渲染；灰态纯展示、不可交互，不阻塞 choices 下拉与处置
 * 动作（处置不依赖 narrative）。侧车补叙完成后轮询自然补齐为 AlertNarrative；
 * 终态侧车（生成失败/熔断跳过）渲染失败说明、不出本占位。
 */
function AlertNarrativePending() {
  return (
    <div data-testid="alert-narrative-pending" style={{ margin: '4px 0' }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        调查生成中…
      </Typography.Text>
    </div>
  );
}

/**
 * 告警明细字段区（描述/叙事/证据/处置/建议/解决依据），六段行单源只写一份，
 * 布局差异按 variant 保留、isPage 仅在真实差异点分支（两变体渲染输出逐字等价）：
 * - 描述行：page 有描述才独占一行渲染，banner 恒渲染并入 📌 spec 前缀；
 * - 叙事行：仅承载失败终态机械说明与「调查生成中」占位；正式调查报告的
 *   「查看调查报告」入口在操作按钮列（AlertReportButton + AlertActionColumn）；
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
      {item.narrative?.text && !hasNarrativeReport(item) ? (
        // 终态机械说明（生成失败/熔断跳过，sidecar model=null，一句话）：
        // 内联灰字即可，不值得一次弹窗点击。正式调查报告的「查看调查报告」
        // 入口在操作按钮列（AlertReportButton），不在明细区渲染。
        <div data-testid="alert-narrative-failed" style={{ margin: '4px 0' }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {item.narrative.text}
          </Typography.Text>
        </div>
      ) : null}
      {item.narrative_pending ? <AlertNarrativePending /> : null}
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
