/**
 * SpecStatusModal.tsx — 「修改状态」弹窗（add-spec-status-modal-budget / spec-status-actions-modal /
 * add-spec-approve-push-modal）。
 *
 * 按当前状态条件渲染五个区块（审批推送/归档/冻结/晋升/预算），走既有后端 API，
 * 零新状态语义。受控 props：project/spec/open/onClose/summary/onDone。
 *
 * 审批推送区块（done 态专用，pushed 不渲染）：确认后写 .fenix/approve_push_request.json
 * 文件信号，daemon 主循环拾取后调 pm_engine.approve_push 执行推送——main 先行+
 * 分支尽力，成功后 SPEC 推进 pushed 终态；失败走既有退避重试，超限升级 push_failed 告警。
 *
 * 冻结态判定：status === 'blocked' && （后端 summary.frozen 为真 || error 以
 * 「用户指令冻结：」开头）。自动冻结（内容完整性闸门 / 预算闸门 / env 阻塞）
 * 只写结构化 frozen 字段 + 自有文案，故 MUST 以后端字段为准——此前只认文本
 * 前缀，三种自动冻结在弹窗里一律显示为「未冻结」，而点击「冻结 SPEC」会经
 * freeze_spec 覆写 error，把预算/环境诊断信息冲掉。预算区块由 nonTerminal
 * 独立控制，与冻结态无关，照常可用。
 */

import {
  Alert,
  App,
  Button,
  DatePicker,
  Divider,
  InputNumber,
  Modal,
  Radio,
  Space,
  Tag,
  Typography,
} from 'antd';
import { useIntl } from '@umijs/max';
import dayjs from 'dayjs';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  approveSpecPush,
  archiveSpec,
  freezeSpec,
  promoteSpec,
  reflowSpec,
  setSpecBudget,
  setSpecFreezeConfig,
  activateSpec,
  resumeSpec,
  setSpecStartAfter,
} from '@/services/dashboard';
import type { SpecSummary } from '@/services/dashboard';

/** 存量文本契约回退（结构化 frozen 字段缺席时的兼容路径）。 */
const FREEZE_ERROR_PREFIX = '用户指令冻结：';
const TERMINAL = new Set(['done', 'pushed']);

interface SpecStatusModalProps {
  project: string;
  spec: string;
  open: boolean;
  onClose: () => void;
  summary: SpecSummary | null;
  onDone: () => void;
}

/** 判断 spec 是否处于冻结态（后端单点判定：结构化字段优先，文本前缀回退）。 */
const isFrozen = (summary: SpecSummary | null) =>
  summary?.status === 'blocked' &&
  (summary.frozen === true || (summary.error || '').startsWith(FREEZE_ERROR_PREFIX));

/** 终态判定（done/pushed）。 */
const isTerminal = (summary: SpecSummary | null) =>
  TERMINAL.has(summary?.status || '');

/** task-gap 缺口结论前缀（fix-impl-tasks-completion-gate P1′：回炉区块的渲染判据）。 */
const TASK_GAP_ERROR_PREFIX = 'task-gap:';

/** 预算兜底默认值（summary 字段缺席时的回退，与后端默认一致）。 */
const BUDGET_EFFECTIVE_FALLBACK = 6;
const BUDGET_MAX_FALLBACK = 100;

/** task-gap 拦截滞留判定：status=verified 且 error 以 task-gap: 开头。 */
const isTaskGapStuck = (summary: SpecSummary | null) =>
  summary?.status === 'verified' &&
  (summary.error || '').startsWith(TASK_GAP_ERROR_PREFIX);

export default function SpecStatusModal({
  project,
  spec,
  open,
  onClose,
  summary,
  onDone,
}: SpecStatusModalProps) {
  const intl = useIntl();
  const { message, modal: appModal } = App.useApp();
  // 各区块按钮的 pending 动作 key（单值：同一时刻弹窗内只有一个确认动作在跑），
  // 按钮按 key 判定自身 loading——此前是单一 loading 被所有区块共用，多个区块
  // 同时渲染（done 态同显审批推送+归档；taskGapStuck/cancelledHold 非终态同显
  // 回炉或恢复+冻结+调度）时点任一按钮会让其余区块按钮一起转圈。
  // 在飞期间其余写动作按钮统一 disabled（code-review item 4011bc5fcc60），使
  // 「同一时刻只有一个确认动作在跑」在 UI 层成立而非仅注释声明。
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  // 弹窗级单飞重入守卫（code-review item 1ff7a536272c，比照既有分面/
  // HooksPanel 的 savingRef 口径）：防重若只靠 pendingAction state 驱动的
  // 按钮 disabled，setPendingAction 渲染生效存在 React 调度间隙，间隙内
  // 连点会并发发出两次写请求；经 pendingActionRef 写读同帧原子短路，state
  // 只负责按钮视觉反馈。全部确认动作（预算「保存」「恢复跟随全局」与冻结
  // 配置「应用」三个直连入口 + 九个 confirm 类 onOk）共用这一把锁（同
  // pendingAction 单值口径：同一时刻弹窗内只有一个确认动作在跑，交叉并发
  // 同样竞速）。
  const pendingActionRef = useRef(false);
  // 预算区状态（预算动作同样走 pendingAction 单值，防与冻结等并发写竞速）
  const [budgetOverride, setBudgetOverride] = useState<number | null>(null);
  // 冻结管理状态
  const [freezeMode, setFreezeMode] = useState<'permanent' | 'scheduled'>('permanent');
  const [freezeUntil, setFreezeUntil] = useState<dayjs.Dayjs | null>(null);
  // 晋升 lint 违规明细（null=无；非 null 时逐条内联渲染在晋升区块）
  const [promoteViolations, setPromoteViolations] = useState<string[] | null>(null);
  // code-review item 51344ba010ba：写动作按钮统一的双 prop 口径（自身动作
  // loading、其他动作在飞时 disabled，见上方 pendingAction 单值不变式）收敛
  // 为单一 helper 展开使用，新增动作只写一处，防漏写 disabled 半边造成
  // 「可并发触发」回归。个别按钮的额外校验条件以覆盖 prop 接在展开后合并。
  const actionButtonProps = (key: string) => ({
    loading: pendingAction === key,
    disabled: pendingAction !== null && pendingAction !== key,
  });

  const frozen = isFrozen(summary);
  const terminal = isTerminal(summary);
  const drafted = summary?.status === 'drafted';
  const nonTerminal = summary && !terminal;
  // fix-impl-tasks-completion-gate P1′：task-gap 拦截滞留 verified 的可回炉判定
  const taskGapStuck = isTaskGapStuck(summary);
  // add-cancelled-spec-resume-action D4：取消保持态（人工取消 run 的有意等待）
  // 的「恢复运行」区块渲染判据——终态之外才可恢复。
  const cancelledHold = summary?.cancelled_hold === true;

  // 打开时初始化预算覆盖值。常规仅在 open false→true 的瞬间执行：summary 来自
  // SSE 增量 patch 的 specMap，弹窗开着期间 frozen_until/budget_override 因后台
  // 动作变化会触发依赖更新，若随依赖重跑初始化会把用户未保存的预算编辑打回
  // 服务端值、并清空正在阅读的晋升 lint 违规明细。例外（code-review item
  // 8aa5e9dea9bb）：打开瞬间 summary 尚为 null（SSE specMap 未回填）时只能以
  // 空缺省占位，首个非 null summary 补达且用户尚未手动编辑过（editDirtyRef 为
  // 假；summary 为 null 时各区块不渲染、正常路径下不可能已编辑，此处防的是
  // 「补达→被置空→再补达」途中已编辑的形态）时补一次初始化，避免用户对着
  // 「跟随全局/永久冻结」空缺省编辑而覆写服务端已有值；补达机会一次性消费，
  // 此后的 summary 更新仍不打回（保持上方既有取舍）。
  const prevOpenRef = useRef(false);
  // open 期间待 summary 补达的哨（true = 当前 summary 为 null，等待首个非 null）
  const awaitingSummaryRef = useRef(false);
  // 用户本轮打开后是否手动编辑过预算/冻结输入（下方三处 onChange 置位；编辑过
  // 则不再补初始化，防打回用户未保存的编辑）
  const editDirtyRef = useRef(false);
  useEffect(() => {
    if (open && !prevOpenRef.current) editDirtyRef.current = false;
    // open 期间 summary 置 null 即进入「待补达」等待（打开瞬间未就绪，或开着
    // 期间被 SSE 置空后等待再次补达）
    if (open && summary === null) awaitingSummaryRef.current = true;
    if (
      open &&
      summary !== null &&
      (!prevOpenRef.current || (awaitingSummaryRef.current && !editDirtyRef.current))
    ) {
      setBudgetOverride(summary.budget_override ?? null);
      setPromoteViolations(null);
      // 初始化冻结管理状态
      if (summary.frozen_until) {
        setFreezeMode('scheduled');
        setFreezeUntil(dayjs(summary.frozen_until));
      } else {
        setFreezeMode('permanent');
        setFreezeUntil(null);
      }
      awaitingSummaryRef.current = false;
    }
    prevOpenRef.current = open;
  }, [open, summary]);

  // 九个 confirm 类 onOk（code-review item 93bcc49c9893）共用的不变样板收口：
  // 单飞守卫（ref 判重 → 置位 → setPendingAction）+ 异常文案 + finally 复位。
  // 动作专属的 API 调用、成功/降级/拒绝分支与 onDone 时机留在各 handler 的
  // action 闭包内；errorPrefix 须带全角冒号，与既有「XX失败：{err}」文案逐字一致。
  // 冻结配置「应用」与预算「保存」「恢复跟随全局」三个直连入口同样收口于此
  // （code-review item be995f3fdec5），动作体内前置校验失败时提前 return，
  // 复位统一落在 finally。
  const runAction = useCallback(
    async (key: string, errorPrefixId: string, action: () => Promise<void>) => {
      if (pendingActionRef.current) return;
      pendingActionRef.current = true;
      setPendingAction(key);
      try {
        await action();
      } catch (err) {
        message.error(intl.formatMessage({ id: errorPrefixId }, { msg: err instanceof Error ? err.message : String(err) }));
      } finally {
        pendingActionRef.current = false;
        setPendingAction(null);
      }
    },
    [message, intl],
  );

  // ── 归档（终态 done/pushed） ───────────────────────
  const handleArchive = useCallback(() => {
    if (!summary) return;
    appModal.confirm({
      title: intl.formatMessage({ id: 'projects.specStatus.title.archive' }),
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {intl.formatMessage({ id: 'projects.specStatus.confirmArchiveHead' }, { name: summary.name })}
          {intl.formatMessage({ id: 'projects.specStatus.archivePrefix' })}{' '}<Typography.Text code>spec/changes/{summary.name}/</Typography.Text>{intl.formatMessage({ id: 'projects.specStatus.archiveMid' })}
          （<Typography.Text code>archive/YYYY-MM-DD-{summary.name}/</Typography.Text>），{intl.formatMessage({ id: 'projects.specStatus.archiveSuffix' })}
          {'\n'}{intl.formatMessage({ id: 'projects.specStatus.archiveTail' })}
        </div>
      ),
      okText: intl.formatMessage({ id: 'projects.specStatus.ok.archive' }),
      cancelText: intl.formatMessage({ id: 'projects.specStatus.cancel' }),
      onOk: () =>
        runAction('archive', 'projects.specStatus.errPrefix.archive', async () => {
          await archiveSpec(project, spec);
          message.success(intl.formatMessage({ id: 'projects.specStatus.msg.archived' }, { spec }));
          onDone();
        }),
    });
  }, [project, spec, summary, onDone, message, appModal, runAction, intl]);

  // ── 冻结（非终态：未冻结→冻结） ────────────────────
  const handleFreeze = useCallback(() => {
    appModal.confirm({
      title: intl.formatMessage({ id: 'projects.specStatus.title.freeze' }),
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {intl.formatMessage({ id: 'projects.specStatus.confirmFreeze' }, { spec })}
        </div>
      ),
      okText: intl.formatMessage({ id: 'projects.specStatus.ok.freeze' }),
      okButtonProps: { danger: true },
      cancelText: intl.formatMessage({ id: 'projects.specStatus.cancel' }),
      onOk: () =>
        runAction('freeze', 'projects.specStatus.errPrefix.freeze', async () => {
          // add-freeze-stop-inflight-agents 6.3：冻结成功后若返回
          // stopped_agents > 0 提示已停止的在跑 agent 计数与续做语义；
          // 为 0 或缺省时不提示（无在跑 agent，交互与现状一致）。
          const result = await freezeSpec(project, spec);
          if (result?.stopped_agents) {
            message.success(
              intl.formatMessage({ id: 'projects.specStatus.msg.frozenStoppedAgents' }, { spec, n: result.stopped_agents }),
            );
          } else {
            message.success(intl.formatMessage({ id: 'projects.specStatus.msg.frozen' }, { spec }));
          }
          onDone();
        }),
    });
  }, [project, spec, onDone, message, appModal, runAction, intl]);

  // ── 解冻（已冻结→立即解冻） ────────────────────────
  const handleUnfreeze = useCallback(() => {
    appModal.confirm({
      title: intl.formatMessage({ id: 'projects.specStatus.title.unfreeze' }),
      content: intl.formatMessage({ id: 'projects.specStatus.confirmUnfreeze' }, { spec }),
      okText: intl.formatMessage({ id: 'projects.specStatus.ok.unfreeze' }),
      cancelText: intl.formatMessage({ id: 'projects.specStatus.cancel' }),
      onOk: () =>
        runAction('unfreeze', 'projects.specStatus.errPrefix.unfreeze', async () => {
          await setSpecFreezeConfig(project, spec, 'unfreeze');
          message.success(intl.formatMessage({ id: 'projects.specStatus.msg.unfrozen' }, { spec }));
          onDone();
        }),
    });
  }, [project, spec, onDone, message, appModal, runAction, intl]);

  // ── 切换冻结模式（永久↔定时） ─────────────────────
  // code-review item 931e241c6437：「切换为永久冻结」会清除既有定时解冻时间、把对
  // daemon 调度的拦截无限期延长，与 handleFreeze/handleUnfreeze 属同级防误触风险，
  // 同样走 appModal.confirm 二次确认；定时「应用」只设置/延长到期自动解冻（调度
  // 拦截只收窄不扩大），保留直执行不另加确认。
  // 直连入口同样走 runAction 单飞收口（code-review item be995f3fdec5）：单飞锁的
  // 置位/复位与异常文案由 runAction 统一持有；定时解冻时间三查在 action 内提前
  // return，复位统一落在 runAction 的 finally。返回 promise 供 confirm onOk
  // 保持「结算后才关框」的既有确认框流程。
  const applyFreezeConfig = useCallback(
    () =>
      runAction('freeze-config', 'projects.specStatus.errPrefix.op', async () => {
        if (freezeMode === 'scheduled') {
          if (!freezeUntil) {
            message.error(intl.formatMessage({ id: 'projects.specStatus.msg.pickUnfreezeTime' }));
            return;
          }
          if (!freezeUntil.isValid()) {
            message.error(intl.formatMessage({ id: 'projects.specStatus.msg.unfreezeTimeInvalid' }));
            return;
          }
          if (freezeUntil.isBefore(dayjs())) {
            message.error(intl.formatMessage({ id: 'projects.specStatus.msg.unfreezeTimePast' }));
            return;
          }
          await setSpecFreezeConfig(project, spec, 'scheduled', freezeUntil.toISOString());
          message.success(intl.formatMessage({ id: 'projects.specStatus.msg.scheduledSet' }));
        } else {
          await setSpecFreezeConfig(project, spec, 'permanent');
          message.success(intl.formatMessage({ id: 'projects.specStatus.msg.permanentSet' }));
        }
        onDone();
      }),
    [project, spec, freezeMode, freezeUntil, onDone, message, runAction, intl],
  );

  const handleFreezeConfig = useCallback(() => {
    if (freezeMode !== 'permanent') {
      void applyFreezeConfig();
      return;
    }
    appModal.confirm({
      title: intl.formatMessage({ id: 'projects.specStatus.title.switchPermanent' }),
      content: intl.formatMessage({ id: 'projects.specStatus.confirmSwitchPermanent' }, { spec }),
      okText: intl.formatMessage({ id: 'projects.specStatus.title.switchPermanent' }),
      okButtonProps: { danger: true },
      cancelText: intl.formatMessage({ id: 'projects.specStatus.cancel' }),
      onOk: applyFreezeConfig,
    });
  }, [freezeMode, spec, appModal, applyFreezeConfig, intl]);

  // ── 晋升（drafted→ready） ─────────────────────────
  const handlePromote = useCallback(() => {
    appModal.confirm({
      title: intl.formatMessage({ id: 'projects.specStatus.title.promote' }),
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {intl.formatMessage({ id: 'projects.specStatus.confirmPromoteHead' }, { spec })}
          {intl.formatMessage({ id: 'projects.specStatus.promoteBody' })}
        </div>
      ),
      okText: intl.formatMessage({ id: 'projects.specStatus.ok.promote' }),
      cancelText: intl.formatMessage({ id: 'projects.specStatus.cancel' }),
      onOk: () =>
        runAction('promote', 'projects.specStatus.errPrefix.promote', async () => {
          const result = await promoteSpec(project, spec);
          if (result.ok) {
            message.success(intl.formatMessage({ id: 'projects.specStatus.msg.promoted' }, { spec }));
            onDone();
          } else {
            // lint 违规：SPEC 停留 drafted（STATE 已写入错误明细）。不关闭弹窗，
            // 违规明细逐条内联渲染在晋升区块（Alert 列表），用户可对照 STATE
            // 中的错误定位声明问题后再手动关闭；后端未返回明细时回退展示
            // reason/error。
            setPromoteViolations(
              result.violations?.length
                ? result.violations
                : [result.reason || result.error || intl.formatMessage({ id: 'projects.specStatus.msg.promoteViolationsFallback' })],
            );
            message.error(intl.formatMessage({ id: 'projects.specStatus.msg.promoteLintBlocked' }));
          }
        }),
    });
  }, [project, spec, onDone, message, appModal, runAction, intl]);

  // ── 审批推送（done，add-spec-approve-push-modal） ──────────
  // done 态的唯一闭环动作：确认后写 .fenix/approve_push_request.json 文件信号，
  // daemon 主循环（≤2s）拾取并调 pm_engine.approve_push 执行推送（main 先行+
  // 分支尽力、SHA 去重、退避重试、归档收口全部沿用既有语义）；推送成功后 SPEC
  // 推进 pushed 终态。状态非 done（pushed 幂等/其他非法）或 daemon 未运行/
  // 已有进行中信号时后端 403/409，此处展示后端 error 文案。
  const handleApprovePush = useCallback(() => {
    if (!summary) return;
    appModal.confirm({
      title: intl.formatMessage({ id: 'projects.specStatus.title.approvePush' }),
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {intl.formatMessage({ id: 'projects.specStatus.confirmApprovePushHead' }, { name: summary.name })}
          {intl.formatMessage({ id: 'projects.specStatus.approvePushBody' })}
        </div>
      ),
      // okText 与弹窗标题分键（验证修复第 1 轮）：标题=审批推送 SPEC、按钮=审批推送，
      // 保持 zh 与抽取前逐字一致（原 okText 字面量「审批推送」）
      okText: intl.formatMessage({ id: 'projects.specStatus.ok.approvePush' }),
      cancelText: intl.formatMessage({ id: 'projects.specStatus.cancel' }),
      onOk: () =>
        runAction('approve-push', 'projects.specStatus.errPrefix.approvePush', async () => {
          await approveSpecPush(project, spec);
          message.success(intl.formatMessage({ id: 'projects.specStatus.msg.pushSubmitted' }));
          onDone();
        }),
    });
  }, [project, spec, summary, onDone, message, appModal, runAction, intl]);

  // ── 回炉（verified + task-gap 错误，fix-impl-tasks-completion-gate P1′） ──
  // task-gap 拦截（verified→done 任务完成度门禁检出未完成任务）滞留 verified 的
  // SPEC 的唯一闭环动作：确认后调用 /api/spec-task-reflow 把 SPEC 复位为 ready，
  // 由 daemon 重新派发实现者承接剩余任务。危险操作（等于用新预算重跑同一件事），
  // 确认文案必须明示「将重新派发实现」。被拒绝（非 task-gap 形态/冻结/幂等重复）
  // 时展示后端返回的拒绝原因，SPEC 状态保持不变。
  const handleReflow = useCallback(() => {
    if (!summary) return;
    const err = summary.error || '';
    const gapNote = err.startsWith(TASK_GAP_ERROR_PREFIX)
      ? `（${err.slice(TASK_GAP_ERROR_PREFIX.length)}）`
      : '';
    appModal.confirm({
      title: intl.formatMessage({ id: 'projects.specStatus.title.reflow' }),
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {intl.formatMessage({ id: 'projects.specStatus.confirmReflowHead' }, { name: summary.name })}
          {intl.formatMessage({ id: 'projects.specStatus.reflowBody1' }, { note: gapNote })}
          {'\n'}
          {intl.formatMessage({ id: 'projects.specStatus.reflowBody2' })}
        </div>
      ),
      okText: intl.formatMessage({ id: 'projects.specStatus.ok.reflow' }),
      okButtonProps: { danger: true },
      cancelText: intl.formatMessage({ id: 'projects.specStatus.cancel' }),
      onOk: () =>
        runAction('reflow', 'projects.specStatus.errPrefix.reflow', async () => {
          const result = await reflowSpec(project, spec);
          if (result.ok) {
            message.success(intl.formatMessage({ id: 'projects.specStatus.msg.reflowed' }, { spec }));
            onDone();
          } else {
            // 被后端拒绝（非 task-gap 形态/冻结/幂等重复等）：展示明确拒绝原因
            const reason = result.reason || result.error || intl.formatMessage({ id: 'projects.specStatus.msg.reflowRejectedFallback' });
            message.error(intl.formatMessage({ id: 'projects.specStatus.msg.reflowRejected' }, { reason }));
          }
        }),
    });
  }, [project, spec, summary, onDone, message, appModal, runAction, intl]);

  // ── 恢复运行（取消保持态，add-cancelled-spec-resume-action D4） ──────────
  // 取消保持态（_cancelled_hold: true）是「有意等待」：全部自动恢复链路对其
  // 跳过，本区块是其唯一界面出口。确认后调用 /api/spec-resume 复位 ready：
  // 有保留分支时按保留分支续做（不丢已提交成果），无可保留分支时降级全新重派
  // （degraded=true 独立提示）。恢复=立即派发实现，消耗一次实现尝试预算，
  // 确认文案必须明示。被拒绝（非保持态/冻结/终态）时展示后端拒绝原因。
  const handleResume = useCallback(() => {
    if (!summary) return;
    appModal.confirm({
      title: intl.formatMessage({ id: 'projects.specStatus.title.resume' }),
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {intl.formatMessage({ id: 'projects.specStatus.confirmResumeHead' }, { name: summary.name })}
          {intl.formatMessage({ id: 'projects.specStatus.resumeBody1' })}
          {'\n'}{intl.formatMessage({ id: 'projects.specStatus.resumeBudgetNote' })}
        </div>
      ),
      okText: intl.formatMessage({ id: 'projects.specStatus.ok.resume' }),
      okButtonProps: { danger: true },
      cancelText: intl.formatMessage({ id: 'projects.specStatus.cancel' }),
      onOk: () =>
        runAction('resume', 'projects.specStatus.errPrefix.resume', async () => {
          const result = await resumeSpec(project, spec);
          if (result.ok) {
            if (result.degraded) {
              // reason 缺失时回退，避免消息尾部悬空冒号（code-review item
              // a9385102d8f7）；回退链口径与 handleReflow 拒绝分支一致
              const reason = result.reason || result.error || intl.formatMessage({ id: 'projects.specStatus.msg.noReasonFallback' });
              message.warning(intl.formatMessage({ id: 'projects.specStatus.msg.resumeDegraded' }, { spec, reason }));
            } else if (result.warning) {
              // fix-scheduling-kick-single-slot D3 对齐（code-review item
              // f3cf514cacb9）：即时唤醒信号写出失败时如实告知（warning 自带
              // 「将由下次扫描派发」语义），不以确定性成功文案替代
              message.warning(result.warning);
            } else {
              message.success(intl.formatMessage({ id: 'projects.specStatus.msg.resumeSuccess' }, { spec }));
            }
            // 即时唤醒信号写出失败：降级分支的消息不携带「由下次扫描派发」
            // 语义，仍须单独补提示；非降级分支已由上方 warning 替代成功文案，
            // 不重复提示
            if (result.warning && result.degraded) {
              message.warning(result.warning);
            }
            onDone();
          } else {
            // 被后端拒绝（非保持态/冻结/终态等）：回退链口径与 handleReflow 拒绝
            // 分支一致，兜底不做出具体状态断言（code-review item ee66dd12e1ca）
            const reason = result.reason || result.error || intl.formatMessage({ id: 'projects.specStatus.msg.noReasonFallback' });
            message.error(intl.formatMessage({ id: 'projects.specStatus.msg.resumeRejected' }, { reason }));
          }
        }),
    });
  }, [project, spec, summary, onDone, message, appModal, runAction, intl]);

  // ── 预算保存（setSpecBudget） ──────────────────────
  // 直连入口同样走 runAction 单飞收口（code-review item be995f3fdec5）：前置校验
  // 在 action 内提前 return（同步执行、无 await 调度间隙），失败走 warning，
  // 复位统一落在 runAction 的 finally。
  const handleBudgetSave = useCallback(
    () =>
      runAction('budget-save', 'projects.specStatus.errPrefix.save', async () => {
        // antd InputNumber 的 min/max 不拦截 onChange，失焦前键入的越界值仍可被提交，保存前须校验
        const budgetMax = summary?.budget_max ?? BUDGET_MAX_FALLBACK;
        if (budgetOverride !== null && (budgetOverride < 1 || budgetOverride > budgetMax)) {
          message.warning(intl.formatMessage({ id: 'projects.specStatus.msg.budgetRange' }, { max: budgetMax }));
          return;
        }
        // step=1 不拦手动键入的小数（如 2.5），保存前与后端整数口径在前端对齐，免一次 400 往返
        if (budgetOverride !== null && !Number.isInteger(budgetOverride)) {
          message.warning(intl.formatMessage({ id: 'projects.specStatus.msg.budgetInteger' }));
          return;
        }
        await setSpecBudget(project, spec, budgetOverride);
        message.success(budgetOverride !== null ? intl.formatMessage({ id: 'projects.specStatus.msg.budgetSaved' }) : intl.formatMessage({ id: 'projects.specStatus.msg.budgetFollowGlobal' }));
        onDone();
      }),
    [project, spec, budgetOverride, summary, onDone, message, runAction, intl],
  );

  const handleBudgetReset = useCallback(
    () =>
      runAction('budget-reset', 'projects.specStatus.errPrefix.op', async () => {
        await setSpecBudget(project, spec, null);
        setBudgetOverride(null);
        message.success(intl.formatMessage({ id: 'projects.specStatus.msg.budgetFollowGlobal' }));
        onDone();
      }),
    [project, spec, onDone, message, runAction, intl],
  );

  // ── 调度区：手工激活 / 激活（add-spec-manual-activation D10） ──────────
  const isManualPending = summary?.start_after === 'manual';

  const handleActivate = useCallback(() => {
    appModal.confirm({
      title: intl.formatMessage({ id: 'projects.specStatus.title.activate' }),
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {intl.formatMessage({ id: 'projects.specStatus.confirmActivateHead' }, { spec })}
          {intl.formatMessage({ id: 'projects.specStatus.activateBody' })}
        </div>
      ),
      okText: intl.formatMessage({ id: 'projects.specStatus.ok.activate' }),
      cancelText: intl.formatMessage({ id: 'projects.specStatus.cancel' }),
      onOk: () =>
        runAction('activate', 'projects.specStatus.errPrefix.activate', async () => {
          const result = await activateSpec(project, spec);
          if (result.ok) {
            // fix-scheduling-kick-single-slot D3：激活成功但即时唤醒信号写出失败时
            // 如实告知（MUST NOT 无条件宣称「daemon 将立即拾取」）。冻结态与
            // start_after: manual 可同时成立（调度区块对任意非终态放宽，后端
            // activate 只拒终态），激活只清 manual 哨兵、冻结拦截仍在，daemon
            // 实际不会派发，此分支文案须限定为解冻后才恢复调度。
            if (result.warning) {
              message.warning(result.warning);
            } else if (frozen) {
              message.success(intl.formatMessage({ id: 'projects.specStatus.msg.activatedFrozen' }, { spec }));
            } else {
              message.success(intl.formatMessage({ id: 'projects.specStatus.msg.activated' }, { spec }));
            }
            onDone();
          } else {
            // 被后端拒绝（终态等）：回退链口径与 handleReflow 拒绝分支一致，兜底
            // 不做出具体状态断言（code-review item ee66dd12e1ca）
            const reason = result.reason || result.error || intl.formatMessage({ id: 'projects.specStatus.msg.noReasonFallback' });
            message.error(intl.formatMessage({ id: 'projects.specStatus.msg.activateRejected' }, { reason }));
          }
        }),
    });
  }, [project, spec, frozen, onDone, message, appModal, runAction, intl]);

  const handleSetManual = useCallback(() => {
    appModal.confirm({
      title: intl.formatMessage({ id: 'projects.specStatus.title.setManual' }),
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {intl.formatMessage({ id: 'projects.specStatus.confirmSetManualHead' }, { spec })}
          {intl.formatMessage({ id: 'projects.specStatus.setManualBody' })}
        </div>
      ),
      okText: intl.formatMessage({ id: 'projects.specStatus.title.setManual' }),
      cancelText: intl.formatMessage({ id: 'projects.specStatus.cancel' }),
      onOk: () =>
        runAction('set-manual', 'projects.specStatus.errPrefix.op', async () => {
          await setSpecStartAfter(project, spec, 'manual');
          message.success(intl.formatMessage({ id: 'projects.specStatus.msg.setManualSuccess' }, { spec }));
          onDone();
        }),
    });
  }, [project, spec, onDone, message, appModal, runAction, intl]);

  // Modal 常挂载（code-review item 4dec1650864f）：关闭只交给 open prop，让 antd
  // 走标准关闭流程播放淡出动画（与 SpecDocModal 一致）。summary 为空时各区块
  // 均按状态条件渲染（不应出现，菜单入口按状态屏蔽），无空转副作用。
  // 内部状态并不随 destroyOnHidden 重置（它只卸载 Modal 的 children 子树，
  // 不触及宿主组件的 useState，code-review item 7c1f36b39bd8）：预算覆盖/
  // 晋升违规/冻结各态由上方打开时初始化 effect 复位；pendingAction 例外——
  // 在飞动作的 promise 结算经各 handler 的 finally 复位，期间保持置位以维持
  // 4011bc5fcc60 的「同一时刻只有一个确认动作在跑」单飞 UI 不变式。
  return (
    <Modal
      title={intl.formatMessage({ id: 'projects.specStatus.title.modal' }, { spec })}
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
      width={520}
    >
      <Space direction="vertical" style={{ width: '100%' }} size={0}>
        {/* ── 审批推送区块（done 专用，pushed 不渲染；add-spec-approve-push-modal D5：
            done 态首要意图是审批推送（闭环动作），故置于归档区块之前） ── */}
        {summary?.status === 'done' && (
          <div style={{ marginBottom: 16 }}>
            <Typography.Text strong style={{ fontSize: 14 }}>{intl.formatMessage({ id: 'projects.specStatus.section.approvePush' })}</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
              {intl.formatMessage({ id: 'projects.specStatus.section.approvePushDesc' })}
            </Typography.Paragraph>
            <Button
              type="primary"
              onClick={handleApprovePush}
              {...actionButtonProps('approve-push')}
            >
              {intl.formatMessage({ id: 'projects.specStatus.section.approvePush' })}
            </Button>
          </div>
        )}

        {/* ── 恢复运行区块（取消保持态非终态；add-cancelled-spec-resume-action D4） ── */}
        {cancelledHold && nonTerminal && (
          <div style={{ marginBottom: 16 }}>
            <Typography.Text strong style={{ fontSize: 14 }}>{intl.formatMessage({ id: 'projects.specStatus.section.resume' })}</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
              {intl.formatMessage({ id: 'projects.specStatus.section.resumeDesc' })}
            </Typography.Paragraph>
            <Button
              danger
              onClick={handleResume}
              {...actionButtonProps('resume')}
            >
              {intl.formatMessage({ id: 'projects.specStatus.section.resume' })}
            </Button>
          </div>
        )}

        {/* ── 回炉区块（verified + task-gap 错误；fix-impl-tasks-completion-gate P1′） ── */}
        {/* summary 空值守卫为类型收窄所需（taskGapStuck 派生自 summary，语义等价） */}
        {taskGapStuck && summary && (
          <div style={{ marginBottom: 16 }}>
            <Typography.Text strong style={{ fontSize: 14 }}>{intl.formatMessage({ id: 'projects.specStatus.section.reflow' })}</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
              {intl.formatMessage({ id: 'projects.specStatus.section.reflowDesc' })}
            </Typography.Paragraph>
            {summary.error && (
              <Typography.Paragraph type="secondary" style={{ margin: '0 0 8px', fontSize: 12 }}>
                {intl.formatMessage({ id: 'projects.specStatus.section.gapConclusion' }, { err: summary.error })}
              </Typography.Paragraph>
            )}
            <Button
              danger
              onClick={handleReflow}
              {...actionButtonProps('reflow')}
            >
              {intl.formatMessage({ id: 'projects.specStatus.btn.reflowNow' })}
            </Button>
          </div>
        )}

        {/* ── 归档区块（终态 done/pushed） ─────────────── */}
        {terminal && (
          <div style={{ marginBottom: 16 }}>
            <Typography.Text strong style={{ fontSize: 14 }}>{intl.formatMessage({ id: 'projects.specStatus.section.archive' })}</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
              {intl.formatMessage({ id: 'projects.specStatus.section.archiveDesc' }, { spec })}
            </Typography.Paragraph>
            <Button
              onClick={handleArchive}
              {...actionButtonProps('archive')}
            >
              {intl.formatMessage({ id: 'projects.specStatus.title.archive' })}
            </Button>
          </div>
        )}

        {/* ── 冻结区块（非终态） ─────────────────────── */}
        {nonTerminal && (
          <div style={{ marginBottom: 16 }}>
            <Divider style={{ margin: '4px 0 12px' }} />
            <Typography.Text strong style={{ fontSize: 14 }}>{intl.formatMessage({ id: 'projects.specStatus.section.freeze' })}</Typography.Text>
            {!frozen ? (
              <>
                <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
                  {intl.formatMessage({ id: 'projects.specStatus.section.notFrozenDesc' })}
                </Typography.Paragraph>
                <Button
                  danger
                  onClick={handleFreeze}
                  {...actionButtonProps('freeze')}
                >
                  {intl.formatMessage({ id: 'projects.specStatus.title.freeze' })}
                </Button>
              </>
            ) : (
              <>
                <div style={{ margin: '4px 0 8px' }}>
                  <Space size={4}>
                    <Typography.Text type="secondary">{intl.formatMessage({ id: 'projects.specStatus.freezeModeLabel' })}</Typography.Text>
                    <Tag color={summary.frozen_until ? 'blue' : 'default'}>
                      {summary.frozen_until ? intl.formatMessage({ id: 'projects.specStatus.tag.scheduled' }) : intl.formatMessage({ id: 'projects.specStatus.tag.permanent' })}
                    </Tag>
                  </Space>
                </div>
                {summary.frozen_until && (
                  <Typography.Paragraph type="secondary" style={{ margin: '0 0 8px', fontSize: 12 }}>
                    {intl.formatMessage({ id: 'projects.specStatus.targetTimePrefix' })}{dayjs(summary.frozen_until).format('YYYY-MM-DD HH:mm')}
                    {intl.formatMessage({ id: 'projects.specStatus.targetTimeSuffix' })}
                  </Typography.Paragraph>
                )}
                {summary.error && (
                  <Typography.Paragraph type="secondary" style={{ margin: '0 0 8px', fontSize: 12 }}>
                    {intl.formatMessage({ id: 'projects.specStatus.section.freezeReason' }, { err: summary.error })}
                  </Typography.Paragraph>
                )}
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  <Space>
                    <Button
                      danger
                      onClick={handleUnfreeze}
                      {...actionButtonProps('unfreeze')}
                    >
                      {intl.formatMessage({ id: 'projects.specStatus.btn.unfreezeNow' })}
                    </Button>
                  </Space>
                  <Radio.Group
                    value={freezeMode}
                    onChange={(e) => {
                      editDirtyRef.current = true; // 用户编辑哨（见 editDirtyRef 注释）
                      setFreezeMode(e.target.value as 'permanent' | 'scheduled');
                    }}
                    options={[
                      { label: intl.formatMessage({ id: 'projects.specStatus.tag.permanent' }), value: 'permanent' },
                      { label: intl.formatMessage({ id: 'projects.specStatus.tag.scheduled' }), value: 'scheduled' },
                    ]}
                  />
                  {freezeMode === 'scheduled' && (
                    <Space>
                      <DatePicker
                        showTime
                        style={{ width: 260 }}
                        value={freezeUntil}
                        onChange={(d) => {
                          editDirtyRef.current = true; // 用户编辑哨（见 editDirtyRef 注释）
                          setFreezeUntil(d);
                        }}
                        placeholder={intl.formatMessage({ id: 'projects.specStatus.placeholder.unfreezeTime' })}
                      />
                      <Button
                        type="primary"
                        onClick={() => void handleFreezeConfig()}
                        {...actionButtonProps('freeze-config')}
                      >
                        {intl.formatMessage({ id: 'projects.specStatus.btn.apply' })}
                      </Button>
                    </Space>
                  )}
                  {freezeMode === 'permanent' && summary.frozen_until && (
                    <Button
                      onClick={() => void handleFreezeConfig()}
                      {...actionButtonProps('freeze-config')}
                    >
                      {intl.formatMessage({ id: 'projects.specStatus.title.switchPermanent' })}
                    </Button>
                  )}
                </Space>
              </>
            )}
          </div>
        )}

        {/* ── 调度区块（非终态，add-spec-manual-activation D10）──
            D10 原限定 status==='ready'——reviewing 态诞生（add-spec-review-gate）且
            start_after 门下沉 drafted/reviewing 派发口（fix-start-after-premature-pickup）
            后，manual 哨兵可合法存在于任意非终态；后端 activate/start-after 本就只拒
            终态（admin_actions.py），故放宽为 nonTerminal 对齐后端契约（2026-09-22 热修）。 */}
        {nonTerminal && (
          <div style={{ marginBottom: 16 }}>
            <Divider style={{ margin: '4px 0 12px' }} />
            <Typography.Text strong style={{ fontSize: 14 }}>{intl.formatMessage({ id: 'projects.specStatus.section.schedule' })}</Typography.Text>
            {isManualPending ? (
              <>
                <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
                  {intl.formatMessage({ id: 'projects.specStatus.section.scheduleManualDesc' })}
                </Typography.Paragraph>
                <Button
                  type="primary"
                  onClick={handleActivate}
                  {...actionButtonProps('activate')}
                >
                  {intl.formatMessage({ id: 'projects.specStatus.btn.activateNow' })}
                </Button>
              </>
            ) : (
              <>
                <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
                  {intl.formatMessage({ id: 'projects.specStatus.section.scheduleAutoDesc' })}
                </Typography.Paragraph>
                <Button
                  onClick={handleSetManual}
                  {...actionButtonProps('set-manual')}
                >
                  {intl.formatMessage({ id: 'projects.specStatus.title.setManual' })}
                </Button>
              </>
            )}
          </div>
        )}

        {/* ── 晋升区块（drafted） ───────────────────── */}
        {drafted && (
          <div style={{ marginBottom: 16 }}>
            <Divider style={{ margin: '4px 0 12px' }} />
            <Typography.Text strong style={{ fontSize: 14 }}>{intl.formatMessage({ id: 'projects.specStatus.section.promote' })}</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
              {intl.formatMessage({ id: 'projects.specStatus.section.promoteDesc' })}
            </Typography.Paragraph>
            {promoteViolations !== null && (
              <Alert
                type="error"
                showIcon
                style={{ marginBottom: 8 }}
                message={intl.formatMessage({ id: 'projects.specStatus.section.promoteLintBlocked' })}
                description={
                  <div style={{ maxHeight: 220, overflowY: 'auto' }}>
                    {promoteViolations.map((v, i) => (
                      <Typography.Paragraph
                        key={i}
                        style={{ margin: '0 0 4px', fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
                      >
                        {`${i + 1}. ${v}`}
                      </Typography.Paragraph>
                    ))}
                  </div>
                }
              />
            )}
            <Button
              onClick={handlePromote}
              {...actionButtonProps('promote')}
            >
              {intl.formatMessage({ id: 'projects.specStatus.title.promote' })}
            </Button>
          </div>
        )}

        {/* ── 预算区块（非终态） ───────────────────── */}
        {nonTerminal && (
          <div>
            <Divider style={{ margin: '4px 0 12px' }} />
            <Typography.Text strong style={{ fontSize: 14 }}>{intl.formatMessage({ id: 'projects.specStatus.section.budget' })}</Typography.Text>
            <div style={{ margin: '4px 0 8px' }}>
              <Typography.Text>
                {intl.formatMessage({ id: 'projects.specStatus.budgetUsedPrefix' })}{' '}<Typography.Text strong>{summary.budget_used ?? 0}</Typography.Text>
                {intl.formatMessage({ id: 'projects.specStatus.budgetEffectiveMid' })}
                <Typography.Text strong>{summary.budget_effective ?? BUDGET_EFFECTIVE_FALLBACK}</Typography.Text>
              </Typography.Text>
            </div>
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              <div>
                <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 4, fontSize: 12 }}>
                  {intl.formatMessage(
                    { id: 'projects.specStatus.budgetOverrideHint' },
                    { max: summary.budget_max ?? BUDGET_MAX_FALLBACK, effective: summary.budget_effective ?? BUDGET_EFFECTIVE_FALLBACK },
                  )}
                </Typography.Text>
                <InputNumber
                  min={1}
                  max={summary.budget_max ?? BUDGET_MAX_FALLBACK}
                  step={1}
                  style={{ width: 120 }}
                  value={budgetOverride}
                  onChange={(v) => {
                    editDirtyRef.current = true; // 用户编辑哨（见 editDirtyRef 注释）
                    setBudgetOverride(v);
                  }}
                  placeholder={intl.formatMessage({ id: 'projects.specStatus.placeholder.followGlobal' })}
                />
              </div>
              <Space>
                <Button
                  type="primary"
                  onClick={() => void handleBudgetSave()}
                  {...actionButtonProps('budget-save')}
                >
                  {intl.formatMessage({ id: 'projects.specStatus.btn.save' })}
                </Button>
                {/* 「恢复跟随全局」额外校验条件（未改值禁用）以覆盖 prop 与
                    helper 合并，布尔语义与原内联表达式完全一致 */}
                <Button
                  onClick={() => void handleBudgetReset()}
                  {...actionButtonProps('budget-reset')}
                  disabled={budgetOverride === null || actionButtonProps('budget-reset').disabled}
                >
                  {intl.formatMessage({ id: 'projects.specStatus.btn.followGlobal' })}
                </Button>
              </Space>
            </Space>
          </div>
        )}
      </Space>
    </Modal>
  );
}
