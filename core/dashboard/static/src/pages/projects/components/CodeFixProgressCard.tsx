// CodeFixProgressCard.tsx — 自动修复进度卡片（add-code-review-auto-fix，task 9.3）
//
// 独立成文件（非内联进 QualityTab）：QualityTab 已近 500 行且被
// QualityTab.test.tsx 以测试替身隔离渲染，新增进度轮询会改动其渲染面与
// 既有断言。本组件自带轮询生命周期，对 QualityTab 是零耦合挂载点。
//
// 呈现契约（spec code-fix-progress；进度条 2026-09-23 起换用 spec 详情页同款
// ProgressBarTile 控件，shared：components/ProgressBarTile.tsx）：
// - ProgressBarTile（大百分比 + 已完成 x/y + 渐变条）+ 当前阶段/次级文案；
// - running=true 时 2s 轮询；**观察到链在跑后转非 running** 或 phase ∈
//   {blocked, failed} 才停止（code-review item 62f764043d88：仅看 running=false
//   会把常驻挂载期的缺省 idle 首帧当收尾而永久停轮询，之后新启动的修复链
//   无人观察——后端 `_finish("failed", …)` 不回写 running，失败链仍须靠
//   phase 收口）；QualityTab 触发成功经 restartKey 重启轮询；
// - `active` 门控：分面未选中零请求（本组件在 QualityTab 内常驻挂载）；
// - blocked/failed 展示原因（**与 running 无关**：后端 blocked 置
//   running=false，若按 running 过滤则该分支永不渲染）；
// - onSettled 仅在观察到链收尾（running→非 running）或进入终止态时回调一次，
//   缺省态（total=0 / 从未激活）不回调，避免与 QualityTab mount 加载重复；
// - total=0 或读取失败静默降级（不渲染、不阻断页签既有布局）；连续读取失败
//   达上限后停轮询（4xx/5xx 常态下 2s 空转没有意义），且 MUST NOT 回调刷新。
// - 切后台恢复（2026-09-25 用户事故）：移动端切后台会掐断在飞 fetch，连续
//   3 次失败即触发上述停轮询+红条，而 effect 依赖不变 → 回前台后永不恢复
//   （对照组 QualityTab 的审查进度靠 SSE 重连+30s 心跳自愈，本组件无冗余
//   驱动）。补 visibilitychange 监听：回前台即重置 retryKey 重启轮询
//   （effect 入口本就 setReadFailed(false) 并重置错误计数），顺带获得回前台
//   立即补刷一帧（对齐 list.tsx/overview 的 visibilitychange 补刷模式）。
import { useEffect, useRef, useState } from 'react';
import { Card, Space, Typography } from 'antd';
import ProgressBarTile from './ProgressBarTile';
import {
  blockedReasonDisplay,
  blockedReasonInfo,
  isSelfhealWait,
} from './codeFixGuidance';
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
// 自愈等待类 reason 的判定集合收在 codeFixGuidance（与同组 reason 的「无需
// 处理」指引文案同点维护，code-review item 5400cd0de2c3），本组件只保留渲染
// 口径：命中即中性等待态而非红色故障，红 exception 只留给真正需人工的终止态
// （failed_batch_maxed / 契约缺失等）；未知/空 reason 判 false，按需人工样式
// 回退（宁严勿松，reason 漂移不静默）。
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
  /**
   * 外部重启信号（code-review item 62f764043d88）：QualityTab 触发成功后递增。
   * 本组件随 Tab 常驻挂载、轮询停即死——新启动的修复链须靠该信号重启轮询，
   * 否则触发成功后进度卡片永不渲染（QualityTab 依赖本组件自动接管展示）。
   */
  restartKey?: number;
  /** 修复链运行态回调（2026-09-24 用户要求：修复进行中灰掉「自动修复」按钮
   *  ——运行态只有本组件的轮询知道，经此上抛给 QualityTab 做按钮门控） */
  onRunningChange?: (running: boolean) => void;
}

export default function CodeFixProgressCard(
  { project, active, onSettled, restartKey, onRunningChange }: CodeFixProgressCardProps,
) {
  const [progress, setProgress] = useState<CodeReviewFixProgress | null>(null);
  // 回前台重启信号（2026-09-25 切后台停轮询事故）：递增即重启主轮询 effect
  // ——连续读取失败停轮询是「宁停不错」的终态，但移动端切后台掐 fetch 造成
  // 的失败是环境性的，回前台必须可恢复（否则红条+冻结到手动刷新页面）。
  const [retryKey, setRetryKey] = useState(0);
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') setRetryKey((k) => k + 1);
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, []);
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
  // onRunningChange 经 ref 传递（同 onSettled 纪律）：回调身份变化不重置轮询。
  const onRunningChangeRef = useRef(onRunningChange);
  useEffect(() => {
    onRunningChangeRef.current = onRunningChange;
  }, [onRunningChange]);
  // 运行态变化上抛（2026-09-24「自动修复」按钮门控）：readFailed 停轮询视为
  // 非运行——停轮询后进度本就不再可信，按钮解禁回到用户可控。
  const fixRunning = !readFailed && Boolean(progress?.running);
  useEffect(() => {
    onRunningChangeRef.current?.(fixRunning);
  }, [fixRunning]);

  // 跨项目切换清态（code-review item 1d0b747da6b2）：本组件随 Tab 常驻挂载，
  // project 变化只重启轮询 effect、不卸载组件，组件级 progress 会保留上一项目
  // 最后一帧——新项目首个 tick 返回前（约 2s + 请求耗时）卡片按旧项目的
  // batch_no/current/file 渲染，旧帧 running=true 还会把父组件「自动修复」按钮
  // 多灰置一个轮询周期；新项目端点连续失败时旧帧一直展示到 readFailed。对
  // project 专门 effect 清空 progress 与 readFailed（对齐 ClaudeOutputPane 无 key
  // 复用切 run 清 status 的口径）。声明序在本轮询 effect 之前：project 变化时
  // 清空先于新轮询的 tick 执行，不会误清新项目刚取到的帧；restartKey/retryKey
  // 触发的正常轮询周期不经本 effect，已落地的进度不受影响。
  useEffect(() => {
    setProgress(null);
    setReadFailed(false);
  }, [project]);
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
        // 收尾判据（code-review item 62f764043d88）：running=false **且**本轮
        // 曾观察到在跑（sawRunning）才停——首个 tick 的缺省 idle 态（组件常驻
        // 挂载、修复链尚未启动时 running=false/total=0）不作为停轮询依据，
        // 否则之后点击「自动修复」启动的新链永远无人观察。终止态（blocked/
        // failed）不受 sawRunning 门限（失败链 running 可能恒 true，且挂在
        // 陈旧终态上持续 2s 空转无意义）。
        settled = (sawRunning && p.running === false) || STOP_PHASES.has(p.phase);
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
    // restartKey 入依赖（code-review item 62f764043d88）：QualityTab 触发
    // 成功后递增，重启已停的轮询接管新链展示。retryKey 同理：回前台递增，
    // 恢复被切后台掐死的轮询（2026-09-25 事故）。
  }, [active, project, restartKey, retryKey]);

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
  // 终止渲染判定（非纯别名）：phase 终态，或连续读取失败停轮询——后者下最后一帧
  // 可能 running=true，以 exception 呈现而非无限 active（ocr 收尾审查）。
  const stopped = terminal || readFailed;
  // 自愈等待态判定：readFailed 时一律不走自愈样式（读取失败须以 exception
  // 呈现停轮询事实，见上）。
  const selfhealWait =
    !readFailed &&
    phase === 'blocked' &&
    reason !== '' &&
    isSelfhealWait(reason);
  const alarm = stopped && !selfhealWait;

  // 条级进度文案（add-code-fix-item-level-progress 5.1）：仅 fixing 阶段渲染。
  // item_done 为 null（明细尚未产生/不可得）时**整段不渲染**（用户 2026-09-23
  // 要求：不留「尚未产生」占位，等有明细再显示；D4 的 null 与 0 区分语义
  // 保留——只是从「渲染可读提示」改为「静默不渲染」）。
  const itemDone = progress.item_done;
  const batchTotal = progress.batch_total;
  const currentItem = progress.current_item;
  let itemProgressText = '';
  if (itemDone !== null) {
    itemProgressText =
      batchTotal !== null
        ? `本批已处置 ${itemDone}/${batchTotal} 条`
        : `本批已处置 ${itemDone} 条`;
    // status/file 由后端从 agent 产物行拷贝（仅校验 item_id），可合法为空——
    // 模板字面量会把 null/undefined 串成 "null"（渲染出「刚完成：null：null」）。
    // 任一缺失即跳过刚完成段，已处置计数行不受影响（code-review item 0ee611edb94e）
    if (currentItem?.status && currentItem.file) {
      const statusLabel = ITEM_STATUS_LABELS[currentItem.status] ?? currentItem.status;
      const titlePart = currentItem.title ? ` ${currentItem.title}` : '';
      itemProgressText += ` · 刚完成：${statusLabel}：${currentItem.file}${titlePart}`;
    }
  }

  // 准备段文案（add-code-fix-startup-stage-visibility D4）：item_done=null 且
  // startup_stage 非空时在原「本批已处置」行位置渲染阶段短语 + 已等待时长
  // （waited_minutes 取不到 birth time 时只显示短语）；startup_stage 为 null
  // 时维持 2026-09-23 口径整段不渲染（不显示误导性 0 计数）。item_done 有值
  // 时准备段完全不进入（条级计数优先，spec「处置开始后收敛」）。
  const startupStage = progress.startup_stage;
  // 宽松等值（== null）被审查规则禁止：两字段类型均为 `T | null`，用显式
  // 严格比较表达同一判定；waited_minutes 是数值再用 typeof 收窄。
  const showStartupStage = itemDone === null && startupStage !== null;
  let startupStageText = '';
  if (showStartupStage && startupStage) {
    startupStageText =
      typeof startupStage.waited_minutes === 'number'
        ? `${startupStage.stage}（已等待 ${startupStage.waited_minutes} 分钟）`
        : startupStage.stage;
  }

  // 进度条显示口径（用户 2026-09-23）：链级 done 只在合回核销后增长，修复中
  // 恒 0%，与「本批已处置 x/y」实时明细割裂——修复中把本批实时处置数并入
  // （封顶 total 防溢出）；合回收尾时 item_done 让位为 null，口径无缝切回
  // done/total，不双计。
  const liveDone = Math.min(
    total > 0 ? total : Number.MAX_SAFE_INTEGER,
    done + (typeof itemDone === 'number' ? itemDone : 0),
  );

  // 次级文案段：已处置条数已由 ProgressBarTile 头部「已完成 x / y」承载，这里
  // 保留当前文件/条级进度/终止原因/读取失败提示（段间「 · 」连接）。条级进度
  // 并入本行（用户 2026-09-23 要求不换行，接在前段后同排显示）。
  const sub: string[] = [];
  if (current) sub.push(current);
  if (startupStageText) sub.push(startupStageText);
  if (phase === 'fixing' && itemProgressText) sub.push(itemProgressText);
  // 原因行换人类可读文案（2026-09-25 用户要求：不能只透传英文 reason 原码），
  // 已知 reason 带「可读原因（原码）」括注，未知原样回显（宁严勿松）。
  if (alarm && reason) sub.push(`原因：${blockedReasonDisplay(reason)}`);
  // readFailed 停轮询事实始终呈现（code-review item 8ade78a418fc）：停轮询前
  // 末帧可能仍是 blocked 且带 reason（含自愈等待类陈旧原因），只给红条+陈旧
  // 原因会把「读取失败停轮询」误呈为链故障本身——此行与原因行并列展示。
  if (alarm && readFailed) sub.push('进度读取失败，已停止轮询');

  // 次级文案段的 testid（嵌套三元被审查规则禁止，抽为 if/else 局部计算）：
  // 准备段 → startup-stage；fixing 阶段且条级进度文案确已进本行
  // （itemProgressText 非空）→ item-progress；其余不挂——item_done=null 时
  // 条级进度整段不渲染，testid 不得漂移到仅含 current/reason 的行上。
  let subTestId: string | undefined;
  if (showStartupStage) {
    subTestId = 'code-fix-startup-stage';
  } else if (phase === 'fixing' && itemProgressText) {
    subTestId = 'code-fix-item-progress';
  }

  // 进度条 status（嵌套三元被审查规则禁止，抽为 if/else 局部计算）：
  // 需人工终止/读取失败 → exception；自愈等待 → normal；其余 → active。
  let barStatus: 'exception' | 'normal' | 'active' = 'active';
  if (alarm) {
    barStatus = 'exception';
  } else if (selfhealWait) {
    barStatus = 'normal';
  }

  return (
    <Card
      size="small"
      style={{ marginTop: 8, marginBottom: 12, background: '#fafafa' }}
      data-testid="code-fix-progress-card"
    >
      <Space direction="vertical" style={{ width: '100%' }} size={4}>
        <Typography.Text strong>
          自动修复代码问题（第 {progress.batch_no} 批 ·{' '}
        {selfhealWait ? '等待下一轮' : PHASE_LABELS[phase] || phase})
        </Typography.Text>
        {/* spec 详情页同款进度条控件（ProgressBarTile）；需人工终止态/读取
            失败传 exception + 纯红 strokeColor——antd 的 strokeColor 会压过
            status 配色，渐变缺省下须显式给红才保得住失败视觉信号。自愈等待
            态走中性 normal（等待是设计内行为，不渲染成故障）。 */}
        <ProgressBarTile
          done={liveDone}
          total={total}
          status={barStatus}
          strokeColor={alarm ? '#ff4d4f' : undefined}
        />
        {sub.length > 0 && (
          <Typography.Text
            type="secondary"
            style={{ fontSize: 12 }}
            data-testid={subTestId}
          >
            {sub.join(' · ')}
          </Typography.Text>
        )}
        {/* blocked 终态处置指引（2026-09-25 用户要求：不能仅提示「已阻塞」，
            必须明确告知如何处理）。独立成行，alarm 时 warning 色与次级灰字
            区分；自愈等待类（failed_batch_retained/wip_gate_blocked）指引
            本身是「无需处理」，保持中性 secondary 不渲染成故障。readFailed
            停轮询不在此列（停轮询事实已由次级文案行覆盖）。 */}
        {phase === 'blocked' && !readFailed && (
          <Typography.Text
            type={selfhealWait ? 'secondary' : 'warning'}
            style={{ fontSize: 12 }}
            data-testid="code-fix-blocked-guidance"
          >
            {`如何处理：${blockedReasonInfo(reason).guidance}`}
          </Typography.Text>
        )}
      </Space>
    </Card>
  );
}
