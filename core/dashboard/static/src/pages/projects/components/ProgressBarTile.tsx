// ProgressBarTile.tsx — 「任务进度」同款进度条控件（原 detail.tsx 内联组件，2026-09-23
// 抽出共享：代码审查页签的自动修复进度卡片 CodeFixProgressCard 也要用）。
//
// 大百分比 + 已完成 x/y + 蓝绿渐变进度条（任务清单/质量门禁/验证进度共用）。
// status 可选参数化（缺省 'active'，既有调用零回归）：自动修复进度链在终止态/
// 读取失败时传 'exception' 呈现红色，对齐原卡片的失败视觉信号。
import { Progress, Typography } from 'antd';

export default function ProgressBarTile(
  { done, total, status = 'active' }: {
    done: number;
    total: number;
    status?: 'normal' | 'exception' | 'active' | 'success';
  },
) {
  const p = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', margin: '4px 0 10px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 28, fontWeight: 600, lineHeight: '40px' }}>{p}%</span>
        <span>
          <Typography.Text type="secondary">已完成 </Typography.Text>
          <Typography.Text strong>
            {done} / {total}
          </Typography.Text>
        </span>
      </div>
      <Progress
        percent={p}
        strokeColor={{ '0%': '#108ee9', '100%': '#87d068' }}
        status={status}
        style={{ marginBottom: 12 }}
      />
    </>
  );
}
