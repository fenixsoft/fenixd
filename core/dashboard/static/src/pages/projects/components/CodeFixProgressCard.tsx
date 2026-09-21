// CodeFixProgressCard.tsx — 自动修复进度卡片（add-code-review-auto-fix，task 9.3）
//
// 独立成文件（非内联进 QualityTab）：QualityTab 已近 500 行且被
// QualityTab.test.tsx 以测试替身隔离渲染，新增进度轮询会改动其渲染面与
// 既有断言。本组件自带轮询生命周期，对 QualityTab 是零耦合挂载点。
//
// 呈现契约（spec code-fix-progress）：
// - 「已处理 {done}/{total} 条」+ Progress percent={done/total*100} +
//   当前阶段/描述（与「审查进行中」卡片同款式：Card + Progress + 次级文案）；
// - running=true 时 2s 轮询，running=false 或 phase ∈ {blocked, failed} 停止
//   （blocked/failed 展示原因，不显示为「运行中」而无限轮询）；
// - total=0 或读取失败静默降级（不渲染、不阻断页签既有布局）。
import { useEffect, useRef, useState } from 'react';
import { Card, Progress, Space, Typography } from 'antd';
import { getCodeReviewFixProgress } from '../../../services/dashboard';
import type { CodeReviewFixProgress } from '../../../services/dashboard';

const POLL_INTERVAL_MS = 2000;
// 终止态：轮询停止（spec「blocked/failed 停止轮询并刷新条目表格」）
const STOP_PHASES = new Set(['blocked', 'failed']);

interface CodeFixProgressCardProps {
  project: string;
  /** 进度进入终止态/消失时回调（QualityTab 据此刷新条目表格） */
  onSettled?: () => void;
}

export default function CodeFixProgressCard({ project, onSettled }: CodeFixProgressCardProps) {
  const [progress, setProgress] = useState<CodeReviewFixProgress | null>(null);
  // onSettled 经 ref 传递：轮询 effect 不因回调身份变化重启（父组件未 memo 时
  // 每帧新函数会让 2s 轮询不断重置）
  const onSettledRef = useRef(onSettled);
  onSettledRef.current = onSettled;

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      try {
        const p = await getCodeReviewFixProgress(project);
        if (!alive) return;
        setProgress(p);
        const settled =
          !p.running && (p.phase === 'idle' || STOP_PHASES.has(p.phase));
        if (settled) {
          // 进入终态：停轮询并通知父组件刷新（一次）
          onSettledRef.current?.();
          return; // 不再排下一轮
        }
      } catch {
        // 读取失败静默降级（非关键路径，spec：MUST NOT 阻断页签既有布局）
        if (!alive) return;
      }
      if (alive) {
        timer = setTimeout(tick, POLL_INTERVAL_MS);
      }
    };

    void tick();
    return () => {
      alive = false;
      if (timer !== null) clearTimeout(timer);
    };
  }, [project]);

  if (!progress || !progress.running) {
    // 无进行中的自动修复（含 blocked/failed 已展示过一帧后停轮询的场景）：
    // 不渲染，MUST NOT 占布局。blocked/failed 需要「可见原因」——running 仍为
    // true 的 blocked/failed 才是「进行中出问题」，此处仅在 running=false 时隐藏。
    return null;
  }

  const { phase, total, done, current, reason } = progress;
  const percent = total > 0 ? Math.round((done / total) * 100) : 0;
  const phaseLabel: Record<string, string> = {
    selecting: '选批中',
    fixing: '修复中',
    regressing: '全量回归中',
    retrying: '回归失败重试中',
    merging: '合回主树中',
    blocked: '已阻塞',
    failed: '失败',
  };
  const blocked = STOP_PHASES.has(phase);

  return (
    <Card
      size="small"
      style={{ marginBottom: 12, background: '#fafafa' }}
      data-testid="code-fix-progress-card"
    >
      <Space direction="vertical" style={{ width: '100%' }} size={4}>
        <Typography.Text strong>
          自动修复代码问题（第 {progress.batch_no} 批 · {phaseLabel[phase] || phase}）
        </Typography.Text>
        <Progress
          percent={percent}
          status={blocked ? 'exception' : 'active'}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          已处理 {done}/{total} 条
          {current ? ` · ${current}` : ''}
          {blocked && reason ? ` · 原因：${reason}` : ''}
        </Typography.Text>
      </Space>
    </Card>
  );
}
