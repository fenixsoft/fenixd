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
// - `active` 门控：分面未选中零请求（本组件在 QualityTab 内常驻挂载）；
// - blocked/failed 展示原因（**与 running 无关**：后端 blocked 置
//   running=false，若按 running 过滤则该分支永不渲染）；
// - onSettled 仅在观察到链收尾（running→非 running）或进入终止态时回调一次，
//   缺省态（total=0 / 从未激活）不回调，避免与 QualityTab mount 加载重复；
// - total=0 或读取失败静默降级（不渲染、不阻断页签既有布局）；连续读取失败
//   达上限后停轮询（4xx/5xx 常态下 2s 空转没有意义），且 MUST NOT 回调刷新。
import { useEffect, useRef, useState } from 'react';
import { Card, Progress, Space, Typography } from 'antd';
import { getCodeReviewFixProgress } from '../../../services/dashboard';
import type { CodeReviewFixProgress } from '../../../services/dashboard';

const POLL_INTERVAL_MS = 2000;
// 终止态：轮询停止（spec「blocked/failed 停止轮询并刷新条目表格」）。
// `ReadonlySet<CodeReviewFixProgress['phase']>` 只约束**本文件字面量**必须是 TS 侧
// phase 联合类型的合法取值（防拼写漂移成「终止态漏停」）；它看不到 Python 侧
// `FIX_PHASES`（core/code_fix.py），不存在跨 FE/BE 边界的编译期检查——后端新增/
// 改名 phase 的漂移由运行时 `PHASE_LABELS[phase] || phase` 兜底展示。
const STOP_PHASES: ReadonlySet<CodeReviewFixProgress['phase']> =
  new Set(['blocked', 'failed']);
// 连续读取失败上限：达到即停轮询（无退避的 2s 空转无意义）
const MAX_CONSECUTIVE_ERRORS = 3;
// 阶段中文名（模块作用域：不随每次渲染重建）。键与后端 FIX_PHASES 同源。
const PHASE_LABELS: Record<CodeReviewFixProgress['phase'], string> = {
  idle: '空闲',
  selecting: '选批中',
  fixing: '修复中',
  regressing: '全量回归中',
  retrying: '回归失败重试中',
  merging: '合回主树中',
  blocked: '已阻塞',
  failed: '失败',
};
// 条级状态中文（模块作用域）。后端 out 行 status ∈ {fixed, skipped}，未知值
// 原样回显（与 PHASE_LABELS 的运行时兜底同口径）。
const ITEM_STATUS_LABELS: Record<string, string> = {
  fixed: '已修复',
  skipped: '已跳过',
};

interface CodeFixProgressCardProps {
  project: string;
  /** 分面是否激活：未激活零请求（对齐 QualityTab/SessionPanel 门控约定） */
  active: boolean;
  /** 进度进入终止态/收尾时回调（QualityTab 据此刷新条目表格） */
  onSettled?: () => void;
}

export default function CodeFixProgressCard(
  { project, active, onSettled }: CodeFixProgressCardProps,
) {
  const [progress, setProgress] = useState<CodeReviewFixProgress | null>(null);
  // 连续读取失败停轮询后的展示标记：此时最后一帧可能仍是 running=true，
  // MUST NOT 以 active 进度条无限展示陈旧「进行中」（ocr 收尾审查）。
  const [readFailed, setReadFailed] = useState(false);
  // onSettled 经 ref 传递：轮询 effect 不因回调身份变化重启（父组件未 memo 时
  // 每帧新函数会让 2s 轮询不断重置）。赋值在 effect 内（post-commit），
  // MUST NOT 在渲染期写 ref——渲染必须保持纯净。
  const onSettledRef = useRef(onSettled);
  useEffect(() => {
    onSettledRef.current = onSettled;
  }, [onSettled]);

  useEffect(() => {
    // active 门控（对齐 QualityTab/SessionPanel 的「未选中零请求」约定）：项目页
    // <Tabs> 未设 destroyInactiveTabPane，本组件首次激活后会一直挂载；若修复链
    // 卡在 running=true，分面切走后仍会每 2s 打 fix-progress。
    if (!active || !project) return;
    setReadFailed(false);
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let errors = 0;
    // 本次挂载是否观察到修复链在跑：用于把「链收尾」与「从未激活的缺省态」
    // 区分开——后者不应触发父组件刷新（否则每次挂载/切项目都白打一次
    // getCodeReviewItems，与 QualityTab 自身 mount 加载重复）。
    let sawRunning = false;

    const tick = async () => {
      let settled = false;
      let notify = false;
      try {
        const p = await getCodeReviewFixProgress(project);
        if (!alive) return;
        errors = 0;
        if (p.running) sawRunning = true;
        setProgress(p);
        // 「或」语义：running=false 停（链已收尾/无进度），终止态停（失败链
        // 的 running 仍为 true，须靠 phase 收口）
        settled = p.running === false || STOP_PHASES.has(p.phase);
        // 仅在观察到链收尾（sawRunning）或进入终止态时通知刷新
        notify = sawRunning || STOP_PHASES.has(p.phase);
      } catch {
        // 读取失败静默降级（非关键路径，spec：MUST NOT 阻断页签既有布局）：
        // 保留上一帧进度，连续失败达上限后退避停轮询。MUST NOT 回调 onSettled
        // ——进度读取失败触发条目刷新会把静默路径变成有副作用（且可能弹错）的路径。
        if (!alive) return;
        errors += 1;
        settled = errors >= MAX_CONSECUTIVE_ERRORS;
        if (settled) setReadFailed(true);
      }
      if (settled) {
        // 进入终态/收尾：停轮询，必要时通知父组件刷新（一次）
        if (notify) onSettledRef.current?.();
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
  }, [active, project]);

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
  // 终止渲染判定（非纯别名）：phase 终态，或连续读取失败停轮询——后者下最后一帧
  // 可能 running=true，以 exception 呈现而非无限 active（ocr 收尾审查）。
  const stopped = terminal || readFailed;

  // 条级进度文案（add-code-fix-item-level-progress 5.1）：仅 fixing 阶段渲染。
  // item_done 为 null 表示「明细尚未产生/不可得」（D4：与「已处置 0 条」是
  // 两件事——null 渲染可读提示，绝不显示 0/N 这类可被误读为卡死的计数）。
  const itemDone = progress.item_done;
  const batchTotal = progress.batch_total;
  const currentItem = progress.current_item;
  let itemProgressText: string;
  if (itemDone != null) {
    itemProgressText =
      batchTotal != null
        ? `本批已处置 ${itemDone}/${batchTotal} 条`
        : `本批已处置 ${itemDone} 条`;
    if (currentItem) {
      const statusLabel = ITEM_STATUS_LABELS[currentItem.status] ?? currentItem.status;
      const titlePart = currentItem.title ? ` ${currentItem.title}` : '';
      itemProgressText += ` · 刚完成：${statusLabel}：${currentItem.file}${titlePart}`;
    }
  } else {
    itemProgressText = '批内明细尚未产生（agent 处置中）';
  }

  return (
    <Card
      size="small"
      style={{ marginBottom: 12, background: '#fafafa' }}
      data-testid="code-fix-progress-card"
    >
      <Space direction="vertical" style={{ width: '100%' }} size={4}>
        <Typography.Text strong>
          自动修复代码问题（第 {progress.batch_no} 批 · {PHASE_LABELS[phase] || phase}）
        </Typography.Text>
        <Progress
          percent={percent}
          status={stopped ? 'exception' : 'active'}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          已处理 {done}/{total} 条
          {current ? ` · ${current}` : ''}
          {stopped && reason ? ` · 原因：${reason}` : ''}
          {stopped && !reason && readFailed ? ' · 进度读取失败，已停止轮询' : ''}
        </Typography.Text>
        {phase === 'fixing' && (
          <Typography.Text
            type="secondary"
            style={{ fontSize: 12 }}
            data-testid="code-fix-item-progress"
          >
            {itemProgressText}
          </Typography.Text>
        )}
      </Space>
    </Card>
  );
}
