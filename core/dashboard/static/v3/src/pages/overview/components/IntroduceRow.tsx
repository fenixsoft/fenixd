import { Card, Progress, Statistic } from 'antd';
import type { ReactNode } from 'react';
import type { OverviewTotals } from '@/services/dashboard';

/**
 * 统计卡行（参考 ant-design-pro analysis 页 IntroduceRow 形态）。
 * 数据规范：stat tile = label + semibold value；无历史时序数据，不放虚构趋势图。
 * 进度条按 meter 规范：蓝色填充 + 同 ramp 浅阶轨道。
 */
const TRACK_LIGHT = '#e6f4ff'; // antd blue-1，与 #1677ff 同 ramp

function pct(done: number, total: number) {
  return total > 0 ? Math.round((done / total) * 100) : 0;
}

function Tile({ children }: { children: ReactNode }) {
  return (
    <Card size="small" styles={{ body: { padding: '16px 24px' } }}>
      {children}
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
      <Tile>
        <Statistic title="SPEC 总数" value={totals.spec_count ?? 0} valueStyle={{ fontWeight: 600 }} />
      </Tile>
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
