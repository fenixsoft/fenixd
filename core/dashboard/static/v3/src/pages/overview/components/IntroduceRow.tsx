import { InfoCircleOutlined } from '@ant-design/icons';
import { Area, Column } from '@ant-design/plots';
import { Card, Progress, Tooltip, Typography } from 'antd';
import type { ReactNode } from 'react';
import type { OverviewTotals, TokenUsageItem } from '@/services/dashboard';

/**
 * 统计卡行（复刻 ant-design-pro analysis 页 IntroduceRow 各卡布局）。
 * 5 卡：SPEC总数(总销售额) / 任务进度(运营活动效果) / 活跃Agent(支付笔数·柱状图) /
 *       Token消耗(访问量·面积图) / 问题阻塞。
 * 数据规范：stat tile = label + semibold value；文字一律文本色，语义色只用于状态值。
 */
const CARD_BODY = { padding: '16px 24px' } as const;

function pct(done: number, total: number) {
  return total > 0 ? Math.round((done / total) * 100) : 0;
}

function compactTokens(n: number): string {
  if (n >= 1e8) return (n / 1e8).toFixed(1) + '亿';
  if (n >= 1e4) return (n / 1e4).toFixed(1) + '万';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return String(n);
}

function Tile({ children }: { children: ReactNode }) {
  return (
    <Card variant="borderless" styles={{ body: CARD_BODY }}>
      {children}
    </Card>
  );
}

function TileHeader({ title, tooltip }: { title: string; tooltip?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: 'rgba(0,0,0,0.88)' }}>{title}</div>
      {tooltip ? (
        <Tooltip title={tooltip}>
          <InfoCircleOutlined style={{ color: 'rgba(0,0,0,.45)' }} />
        </Tooltip>
      ) : null}
    </div>
  );
}

/** 卡1：SPEC 总数 — 复刻 analysis 总销售额卡（大数字 + 周同比/日同比位置放今日/近7天更新小字） */
function SpecCountTile({ totals }: { totals: OverviewTotals }) {
  return (
    <Card variant="borderless" styles={{ body: CARD_BODY }}>
      <TileHeader
        title="SPEC 总数"
        tooltip="小字口径：按各项目 STATE.md 的 updated 时间统计；今日 = 本地自然日 0 点起，近 7 天 = 滚动 7×24 小时"
      />
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

/** 卡2：任务进度 — 复刻 analysis 运营活动效果卡（大数字百分比 + 已完成小字跟随 + 渐变进度条） */
function TaskProgressTile({ totals }: { totals: OverviewTotals }) {
  const progress = pct(totals.task_done ?? 0, totals.task_total ?? 0);
  return (
    <Card variant="borderless" styles={{ body: CARD_BODY }}>
      <TileHeader title="任务进度" />
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, margin: '4px 0 10px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 28, fontWeight: 600, lineHeight: '40px' }}>{progress}%</span>
        <span>
          <Typography.Text type="secondary">已完成 </Typography.Text>
          <Typography.Text strong>
            {totals.task_done ?? 0} / {totals.task_total ?? 0}
          </Typography.Text>
        </span>
      </div>
      <Progress
        percent={progress}
        strokeColor={{ '0%': '#108ee9', '100%': '#87d068' }}
        status="active"
      />
    </Card>
  );
}

// 活跃 Agent 类型展示分类（planner 家族合并为「规划」，评审独立；未知类型归「其它」）
const AGENT_CATS: [keys: string[], label: string][] = [
  [['implementer'], '实现'],
  [['planner', 'planner-plan'], '规划'],
  [['planner-judge'], '评审'],
  [['verifier'], '验证'],
  [['tester'], '测试'],
];

// 分类调色板（按 AGENT_CATS 顺序 + 其它），已过 dataviz 六项校验（light 模式，含 CVD 相邻对）；
// 橙/绿对白底对比度 WARN 由柱顶直接数值标签缓解
const AGENT_PALETTE = ['#1677ff', '#fa8c16', '#08979c', '#722ed1', '#52c41a', '#eb2f96'];

/** 卡3：活跃 Agent — 大数字 + 行内图例 + 柱状图（每类一色，数值白字居中柱内） */
function ActiveAgentTile({ totals }: { totals: OverviewTotals }) {
  const byType = totals.active_runs_by_type || {};
  const total = totals.active_runs ?? 0;
  const catTotal = AGENT_CATS.reduce((s, [keys]) => s + keys.reduce((x, k) => x + (byType[k] || 0), 0), 0);
  const other = Math.max(0, total - catTotal);
  const data = [
    ...AGENT_CATS.map(([keys, label]) => ({
      type: label,
      value: keys.reduce((s, k) => s + (byType[k] || 0), 0),
    })),
    { type: '其它', value: other },
  ].filter((d) => d.value > 0);
  return (
    <Card variant="borderless" styles={{ body: CARD_BODY }}>
      <TileHeader title="活跃 Agent 运行" tooltip="运行中/刚启动的 agent run 按类型分布" />
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, margin: '4px 0 6px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 28, fontWeight: 600, lineHeight: '40px' }}>{total}</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {data.map((d, i) => (
            <span
              key={d.type}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                fontSize: 12,
                color: 'rgba(0,0,0,0.65)',
                whiteSpace: 'nowrap',
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  background: AGENT_PALETTE[i % AGENT_PALETTE.length],
                  borderRadius: 2,
                  display: 'inline-block',
                }}
              />
              {d.type}
            </span>
          ))}
        </span>
      </div>
      <div style={{ height: 46 }}>
        {data.length ? (
          <Column
            data={data}
            xField="type"
            yField="value"
            colorField="type"
            height={46}
            autoFit
            axis={false}
            padding={0}
            scale={{ color: { range: AGENT_PALETTE } }}
            labels={[
              {
                text: 'value',
                position: 'inside',
                style: { fill: '#fff', fontSize: 11, fontWeight: 600, textAlign: 'center', textBaseline: 'middle' },
              },
            ]}
            style={{ insetLeft: 4, insetRight: 4 }}
          />
        ) : (
          <Typography.Text type="secondary">暂无活跃运行</Typography.Text>
        )}
      </div>
    </Card>
  );
}

/** 卡4：Token 消耗 — 复刻 analysis 访问量卡（大数字合计 + 平滑面积图展示近 20 个 spec） */
function TokenTile({ recent }: { recent: TokenUsageItem[] }) {
  const sum = recent.reduce((s, r) => s + r.tokens, 0);
  // recent 为 updated 倒序（最新在前）；面积图 x 轴从旧到新 → 反转，最新在最右
  const seen = new Set<string>();
  const data = recent
    .slice()
    .reverse()
    .map((r) => {
      const spec = seen.has(r.spec) ? `${r.spec}·${r.project}` : r.spec;
      seen.add(r.spec);
      return { spec, tokens: r.tokens };
    });
  return (
    <Card variant="borderless" styles={{ body: CARD_BODY }}>
      <TileHeader
        title="Token 消耗"
        tooltip="最近 20 个有消耗的 SPEC（_tokens_in + _tokens_out 累计），按最近活跃排序；悬浮查看单点数值"
      />
      <div style={{ fontSize: 28, fontWeight: 600, lineHeight: '40px', margin: '4px 0 6px' }}>
        {compactTokens(sum)}
      </div>
      <div style={{ height: 46 }}>
        {data.length ? (
          <Area
            data={data}
            xField="spec"
            yField="tokens"
            shapeField="smooth"
            height={46}
            axis={false}
            padding={-20}
            autoFit
            style={{
              fill: 'linear-gradient(-90deg, white 0%, #1677ff 100%)',
              fillOpacity: 0.6,
            }}
          />
        ) : (
          <Typography.Text type="secondary">暂无数据</Typography.Text>
        )}
      </div>
    </Card>
  );
}

/** 卡5：问题/阻塞 */
function ProblemTile({ totals }: { totals: OverviewTotals }) {
  const hasProblem = (totals.problems || 0) > 0;
  return (
    <Tile>
      <TileHeader title="问题/阻塞" />
      <div style={{ fontSize: 28, fontWeight: 600, lineHeight: '40px', margin: '4px 0 6px', color: hasProblem ? '#ff4d4f' : undefined }}>
        {totals.problems ?? 0}
      </div>
    </Tile>
  );
}

export default function IntroduceRow({
  totals,
  tokenRecent,
}: {
  totals: OverviewTotals;
  tokenRecent: TokenUsageItem[];
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
        gap: 16,
      }}
    >
      <SpecCountTile totals={totals} />
      <TaskProgressTile totals={totals} />
      <ActiveAgentTile totals={totals} />
      <TokenTile recent={tokenRecent} />
      <ProblemTile totals={totals} />
    </div>
  );
}
