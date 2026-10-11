// ProgressBarTile.tsx — 「任务进度」同款进度条控件（原 detail.tsx 内联组件，2026-09-23
// 抽出共享：代码审查页签的自动修复进度卡片 CodeFixProgressCard 也要用）。
//
// 大百分比 + 已完成 x/y + 蓝绿渐变进度条（任务清单/质量门禁/验证进度共用）。
// status 可选参数化（缺省 'active'，既有调用零回归）：自动修复进度链在终止态/
// 读取失败时传 'exception' 呈现红色，对齐原卡片的失败视觉信号。
// strokeColor 可选覆盖（2026-09-24）：缺省蓝绿渐变；调用方传纯红时压过渐变——
// antd 的 strokeColor 优先级高于 status 配色，exception 不显式给红保不住失败
// 视觉信号（此前调用方一直传但本组件未消费，红色信号实际未生效，本次补齐）。
import { Progress, Typography } from 'antd';

export default function ProgressBarTile(
  { done, total, status = 'active', strokeColor }: {
    done: number;
    total: number;
    status?: 'normal' | 'exception' | 'active' | 'success';
    strokeColor?: string;
  },
) {
  // 纵深防御：Math.round/Math.max/Math.min 遇 NaN 均透传，NaN/Infinity 会渲染出
  // 「NaN%」「NaN / NaN」——入口先做有限性守卫，任一非有限时 done 与 total 均归零
  // 回退再走既有钳制；合法值路径完全不变。
  const finite = Number.isFinite(done) && Number.isFinite(total);
  const safeDone = finite ? done : 0;
  const safeTotal = finite ? total : 0;
  const p = safeTotal > 0 ? Math.min(100, Math.max(0, Math.round((safeDone / safeTotal) * 100))) : 0;
  // done 超过 total 时文本同样钳到 total / total：与上方百分比钳制口径一致，
  // 避免进度条满格 100% 却显示「12 / 10」的矛盾信号（上游重复计数/统计滞后）。
  // 负值对称钳到 [0, total]：防御统计口径异常，避免渲染出负百分比/负计数。
  const shownDone = Math.max(0, Math.min(safeDone, safeTotal));
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', margin: '4px 0 10px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 28, fontWeight: 600, lineHeight: '40px' }}>{p}%</span>
        <span>
          <Typography.Text type="secondary">已完成 </Typography.Text>
          <Typography.Text strong>
            {shownDone} / {safeTotal}
          </Typography.Text>
        </span>
      </div>
      <Progress
        percent={p}
        strokeColor={strokeColor ?? { '0%': '#108ee9', '100%': '#87d068' }}
        status={status}
        style={{ marginBottom: 12 }}
      />
    </>
  );
}
