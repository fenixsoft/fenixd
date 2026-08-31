import { InfoCircleOutlined } from '@ant-design/icons';
import { Card, Progress, Statistic, Tooltip, Typography } from 'antd';
import type { ReactNode } from 'react';
import type { OverviewTotals } from '@/services/dashboard';

/**
 * 统计卡行（参考 ant-design-pro analysis 页 IntroduceRow 形态）。
 * 数据规范：stat tile = label + semibold value；无历史时序数据，不放虚构趋势图。
 * 进度条按 meter 规范：蓝色填充 + 同 ramp 浅阶轨道。
 */
const TRACK_LIGHT = '#e6f4ff'; // antd blue-1，与 #1677ff 同 ramp
const CARD_BODY = { padding: '16px 24px' } as const;

function pct(done: number, total: number) {
  return total > 0 ? Math.round((done / total) * 100) : 0;
}

function Tile({ children }: { children: ReactNode }) {
  return (
    <Card variant="borderless" styles={{ body: CARD_BODY }}>
      {children}
    </Card>
  );
}

/**
 * 卡1：SPEC 总数 — 复刻 analysis 总销售额卡布局：
 * 标题 + 指标说明 Tooltip / 大数字 / 下方小字统计（对应参考卡周同比、日同比位置）。
 */
function SpecCountTile({ totals }: { totals: OverviewTotals }) {
  return (
    <Card variant="borderless" styles={{ body: CARD_BODY }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Text type="secondary">SPEC 总数</Typography.Text>
        <Tooltip title="小字口径：按各项目 STATE.md 的 updated 时间统计；今日 = 本地自然日 0 点起，近 7 天 = 滚动 7×24 小时">
          <InfoCircleOutlined style={{ color: 'rgba(0,0,0,.45)' }} />
        </Tooltip>
      </div>
      <div style={{ fontSize: 28, fontWeight: 600, lineHeight: '40px', margin: '4px 0 6px' }}>
        {totals.spec_count ?? 0}
      </div>
      <div style={{ minHeight: 46, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '4px 12px' }}>
        <span style={{ whiteSpace: 'nowrap' }}>
          <Typography.Text type="secondary">今日更新 </Typography.Text>
          <Typography.Text strong>{totals.spec_updated_today ?? 0}</Typography.Text>
        </span>
        <span style={{ whiteSpace: 'nowrap' }}>
          <Typography.Text type="secondary">近 7 天更新 </Typography.Text>
          <Typography.Text strong>{totals.spec_updated_week ?? 0}</Typography.Text>
        </span>
      </div>
    </Card>
  );
}

export default function IntroduceRow({ totals }: { totals: OverviewTotals }) {
  const progress = pct(totals.task_done, totals.task_total);
  const hasProblem = (totals.problems || 0) > 0;
  const hasActive = (totals.active_runs || 0) > 0;
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
        gap: 16,
      }}
    >
      <SpecCountTile totals={totals} />
      <Tile>
        <Statistic
          title="任务进度"
          value={totals.task_done ?? 0}
          formatter={(v) => String(v)}
          suffix={`/ ${totals.task_total ?? 0}`}
          valueStyle={{ fontWeight: 600, fontSize: 24 }}
        />
        <Progress percent={progress} size="small" strokeColor="#1677ff" trailColor={TRACK_LIGHT} />
      </Tile>
      <Tile>
        <Statistic
          title="问题/阻塞"
          value={totals.problems ?? 0}
          valueStyle={{ fontWeight: 600, color: hasProblem ? '#ff4d4f' : undefined }}
        />
      </Tile>
      <Tile>
        <Statistic
          title="活跃 Agent 运行"
          value={totals.active_runs ?? 0}
          valueStyle={{ fontWeight: 600, color: hasActive ? '#faad14' : undefined }}
        />
      </Tile>
      <Tile>
        <Statistic
          title="总体实现进度"
          value={progress}
          suffix="%"
          valueStyle={{ fontWeight: 600 }}
        />
      </Tile>
    </div>
  );
}
