// CodeFixProgressCard.tsx — 自动修复进度卡片（add-code-review-auto-fix，task 9.3）
//
// 独立成文件（非内联进 QualityTab）：QualityTab 已近 500 行且被
// QualityTab.test.tsx 以测试替身隔离渲染，新增进度轮询会改动其渲染面与
// 既有断言。本组件自带轮询生命周期，对 QualityTab 是零耦合挂载点。
//
// 呈现契约（spec code-fix-progress）：
// - 「已处理 {done}/{total} 条」+ Progress percent={done/total*100} +
//   当前阶段/描述（与「审查进行中」卡片同款式：Card + Progress + 次级文案）；
// - running=true 时 2s 轮询；running=false **或** phase ∈ {blocked, failed}
//   即停止（两者是「或」——后端 `_finish("failed", …)` 不回写 running，
//   失败链会长期停在 running=true/phase=failed，只看 running 会无限轮询）；
// - blocked/failed 展示原因（**与 running 无关**：后端 blocked 置
//   running=false，若按 running 过滤则该分支永不渲染）；
// - total=0 或读取失败静默降级（不渲染、不阻断页签既有布局）；连续读取失败
//   达上限后停轮询（4xx/5xx 常态下 2s 空转没有意义）。
import { useEffect, useRef, useState } from 'react';
import { Card, Progress, Space, Typography } from 'antd';
import { getCodeReviewFixProgress } from '../../../services/dashboard';
import type { CodeReviewFixProgress } from '../../../services/dashboard';

const POLL_INTERVAL_MS = 2000;
// 终止态：轮询停止（spec「blocked/failed 停止轮询并刷新条目表格」）
const STOP_PHASES = new Set(['blocked', 'failed']);
// 连续读取失败上限：达到即停轮询（无退避的 2s 空转无意义）
const MAX_CONSECUTIVE_ERRORS = 3;

interface CodeFixProgressCardProps {
  project: string;
  /** 进度进入终止态/消失时回调（QualityTab 据此刷新条目表格） */
  onSettled?: () => void;
}

export default function CodeFixProgressCard({ project, onSettled }: CodeFixProgressCardProps) {
  const [progress, setProgress] = useState<CodeReviewFixProgress | null>(null);
  // onSettled 经 ref 传递：轮询 effect 不因回调身份变化重启（父组件未 memo 时
  // 每帧新函数会让 2s 轮询不断重置）。赋值在 effect 内（post-commit），
  // MUST NOT 在渲染期写 ref——渲染必须保持纯净。
  const onSettledRef = useRef(onSettled);
  useEffect(() => {
    onSettledRef.current = onSettled;
  }, [onSettled]);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let errors = 0;

    const tick = async () => {
      let settled = false;
      try {
        const p = await getCodeReviewFixProgress(project);
        if (!alive) return;
        errors = 0;
        setProgress(p);
        // 「或」语义：running=false 停（链已收尾/无进度），终止态停（失败链
        // 的 running 仍为 true，须靠 phase 收口）
        settled = p.running === false || STOP_PHASES.has(p.phase);
      } catch {
        // 读取失败静默降级（非关键路径，spec：MUST NOT 阻断页签既有布局）：
        // 保留上一帧进度，连续失败达上限后退避停轮询
        if (!alive) return;
        errors += 1;
        settled = errors >= MAX_CONSECUTIVE_ERRORS;
      }
      if (settled) {
        // 进入终态：停轮询并通知父组件刷新（一次）
        onSettledRef.current?.();
        return; // 不再排下一轮
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

  if (!progress) {
    return null;
  }
  const terminal = STOP_PHASES.has(progress.phase);
  if (!progress.running && !terminal) {
    // 无进行中的自动修复（total=0 的缺省态 / 链已正常收尾为 idle）：
    // 不渲染，MUST NOT 占布局。
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
  const stopped = terminal;

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
          status={stopped ? 'exception' : 'active'}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          已处理 {done}/{total} 条
          {current ? ` · ${current}` : ''}
          {stopped && reason ? ` · 原因：${reason}` : ''}
        </Typography.Text>
      </Space>
    </Card>
  );
}
